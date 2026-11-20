"""App wiring for Assist: one AssistService per process.

    init_assist()      call once at startup (after init_capture())
    shutdown_assist()  call at shutdown
    get_service()      FastAPI dependency (tests override it)
"""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from app.capture.languages import is_english

from .pipeline import AssistDeps, AssistPipeline

log = logging.getLogger("kaarigar.assist.service")


class RateLimiter:
    """Sliding window per key (user id). In-memory: fine for one backend process."""

    def __init__(self, limit: int, window_sec: float = 60.0):
        self.limit = limit
        self.window = window_sec
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True


@dataclass
class Storage:
    upload: Callable[[str, str, bytes, str], None]
    download: Callable[[str, str], bytes]
    signed_url: Callable[[str, str, int], str | None]


class AssistService:
    def __init__(self, deps: AssistDeps, *, storage: Storage, tts_factory: Callable[[], Any],
                 start_reply: Callable[..., None]):
        self.deps = deps
        self.settings = deps.settings
        self.repo = deps.repo
        self.pipeline = AssistPipeline(deps)
        self.storage = storage
        self.tts_factory = tts_factory
        self.start_reply = start_reply
        self.executor = ThreadPoolExecutor(max_workers=max(1, self.settings.ASSIST_WORKERS),
                                           thread_name_prefix="assist")
        self.ask_limit = RateLimiter(self.settings.ASK_PER_MINUTE)
        self.tts_limit = RateLimiter(self.settings.TTS_PER_MINUTE)
        self._cache: OrderedDict[tuple, Any] = OrderedDict()
        self._cache_lock = threading.Lock()
        self._runs: dict[str, threading.Event] = {}
        self._runs_lock = threading.Lock()

    # ------------------------------------------------------------------ one live answer per person
    def begin_run(self, user_id: str) -> threading.Event:
        """A new question from this person supersedes the one still being answered (the phone was interrupted
        but the old connection may not have closed yet). Returns the new run's 'superseded' flag."""
        flag = threading.Event()
        with self._runs_lock:
            old = self._runs.get(user_id)
            if old is not None:
                old.set()
            self._runs[user_id] = flag
        return flag

    def end_run(self, user_id: str, flag: threading.Event) -> None:
        with self._runs_lock:
            if self._runs.get(user_id) is flag:
                del self._runs[user_id]

    # ------------------------------------------------------------------ helpers
    def signed(self, bucket: str, path: str | None, expires: int = 3600) -> str | None:
        if not path:
            return None
        try:
            return self.storage.signed_url(bucket, path, expires)
        except Exception:  # noqa: BLE001
            return None

    def _cached(self, key: tuple, make: Callable[[], Any]) -> Any:
        with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        value = make()
        if value is not None:
            with self._cache_lock:
                self._cache[key] = value
                while len(self._cache) > 300:
                    self._cache.popitem(last=False)
        return value

    def fields_in(self, key: str, fields: dict, language: str) -> dict | None:
        """Record fields (English) -> `language`, cached in memory. None for English or on failure."""
        if is_english(language):
            return None

        def make() -> dict | None:
            from app.capture import translate

            try:
                return translate.to_local(self.deps.structured_factory(), self.settings.GROQ_MODEL_SMALL,
                                          fields, None, language)
            except Exception as e:  # noqa: BLE001
                log.info("source translation failed: %s", type(e).__name__)
                return None

        return self._cached(("fields", key, language), make)

    def text_in(self, key: str, text: str, language: str) -> str | None:
        if is_english(language) or not text:
            return None
        from .prompts import to_language_system

        return self._cached(("text", key, language), lambda: self.deps.writer_factory().text(
            model=self.settings.GROQ_MODEL_SMALL, system=to_language_system(language), user=text[:1500],
            max_tokens=600))

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)


# ---------------------------------------------------------------------- app wiring

def _ttl_cache(fn: Callable[[str], list[str]], ttl: float) -> Callable[[str], list[str]]:
    store: dict[str, tuple[float, list[str]]] = {}
    lock = threading.Lock()

    def get(key: str) -> list[str]:
        now = time.monotonic()
        with lock:
            hit = store.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]
        value = fn(key)
        with lock:
            store[key] = (now, value)
        return value

    return get


_service: AssistService | None = None


def init_assist() -> AssistService:
    global _service
    from app.capture.audio import prepare
    from app.capture.llm import GroqLLM
    from app.capture.sarvam import SarvamClient

    from . import adapters
    from .audio_clean import clean_audio
    from .llm import GroqWriter
    from .repo import PostgresAssistRepo
    from .settings import get_assist_settings
    from .tts import SarvamTTS

    s = get_assist_settings()
    repo = PostgresAssistRepo(adapters.db_conn)
    deps = AssistDeps(
        repo=repo,
        settings=s,
        search=adapters.hybrid_search,
        stt_factory=lambda: SarvamClient(s.SARVAM_API_KEY, model=s.SARVAM_STT_MODEL, mode=s.ASSIST_STT_MODE,
                                         timeout=s.SARVAM_TIMEOUT_SEC),
        writer_factory=lambda: GroqWriter(s.GROQ_API_KEY, timeout=s.GROQ_TIMEOUT_SEC),
        structured_factory=lambda: GroqLLM(s.GROQ_API_KEY, timeout=s.GROQ_TIMEOUT_SEC),
        prepare_audio=prepare,
        clean_audio=clean_audio,
        machine_codes=_ttl_cache(repo.machine_codes, 300),
    )
    storage = Storage(upload=adapters.storage_upload, download=adapters.storage_download,
                      signed_url=adapters.storage_signed_url)
    n = repo.mark_stuck_answering("server_restarted")
    if n:
        log.info("marked %s interrupted question(s) as failed", n)
    _service = AssistService(
        deps, storage=storage,
        tts_factory=lambda: SarvamTTS(s.SARVAM_API_KEY, model=s.SARVAM_TTS_MODEL, speaker=s.SARVAM_TTS_SPEAKER,
                                      max_chars=s.TTS_MAX_CHARS),
        start_reply=adapters.start_reply_capture,
    )
    return _service


def shutdown_assist() -> None:
    global _service
    if _service:
        _service.shutdown()
    _service = None


def get_service() -> AssistService:
    if _service is None:
        raise RuntimeError("Assist not started: call init_assist() in the app lifespan")
    return _service


def set_service(s: AssistService | None) -> None:
    """Tests only."""
    global _service
    _service = s
