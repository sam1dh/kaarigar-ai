"""Runs the Capture graph: start in the background, resume on human decisions, retry after failures.

Checkpoints are stored with PostgresSaver in the `langgraph` schema (see 0003_phase2.sql),
so a note waiting for the expert or supervisor survives server restarts.
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langgraph.types import Command

from .errors import USER_MESSAGES, CaptureError
from .graph import CaptureDeps, build_graph

log = logging.getLogger("kaarigar.capture.runner")


class NotWaiting(Exception):
    """The record isn't paused at the step the caller wants to resume."""


class CaptureRunner:
    def __init__(self, deps: CaptureDeps, checkpointer: Any):
        self.deps = deps
        self.checkpointer = checkpointer
        self.graph = build_graph(deps, checkpointer)
        self._pool = ThreadPoolExecutor(max_workers=max(1, deps.settings.CAPTURE_WORKERS),
                                        thread_name_prefix="capture")
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._locks_guard = threading.Lock()

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def thread_id(record_id: str) -> str:
        return f"capture:{record_id}"

    def config(self, record_id: str) -> dict:
        return {"configurable": {"thread_id": self.thread_id(record_id)}}

    def _lock(self, record_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks[record_id]

    def next_nodes(self, record_id: str) -> tuple[str, ...]:
        snap = self.graph.get_state(self.config(record_id))
        return tuple(snap.next or ())

    # ------------------------------------------------------------------ background run
    def _run(self, record_id: str, tenant_id: str, graph_input: Any) -> None:
        with self._lock(record_id):
            try:
                self.graph.invoke(graph_input, self.config(record_id))
            except CaptureError as e:
                log.info("capture %s failed: %s", record_id, e.code)
                self._mark_failed(tenant_id, record_id, e.code)
            except Exception:  # noqa: BLE001
                log.exception("capture %s crashed", record_id)   # stack trace only, no content
                self._mark_failed(tenant_id, record_id, "internal")

    def _mark_failed(self, tenant_id: str, record_id: str, code: str) -> None:
        try:
            if self.deps.repo.get(tenant_id, record_id):
                self.deps.repo.update(tenant_id, record_id, stage="failed", error=code)
        except Exception:  # noqa: BLE001
            log.exception("could not mark capture %s failed", record_id)

    def start(self, record_id: str, tenant_id: str):
        """Returns a Future (tests wait on it; the API doesn't)."""
        return self._pool.submit(self._run, record_id, tenant_id, {"record_id": record_id, "tenant_id": tenant_id})

    def retry(self, record_id: str, tenant_id: str):
        """Continue from the last good checkpoint (the failed node runs again)."""
        self.deps.repo.update(tenant_id, record_id, stage="queued", error=None)
        if self.next_nodes(record_id):
            return self._pool.submit(self._run, record_id, tenant_id, None)
        # nothing checkpointed yet (failed before the first node finished): start fresh
        return self.start(record_id, tenant_id)

    def run_sync(self, record_id: str, tenant_id: str) -> None:
        """For tests and scripts: run the background part in this thread."""
        self._run(record_id, tenant_id, {"record_id": record_id, "tenant_id": tenant_id})

    # ------------------------------------------------------------------ human decisions
    def _resume(self, record_id: str, waiting_node: str, after_node: str, key: str, decision: dict) -> None:
        with self._lock(record_id):
            cfg = self.config(record_id)
            nxt = self.next_nodes(record_id)
            if waiting_node in nxt:
                self.graph.invoke(Command(resume=decision), cfg)
            elif after_node in nxt:
                # A previous resume failed after the interrupt (e.g. translation timed out).
                # Replace the decision and continue from there.
                self.graph.update_state(cfg, {key: decision})
                self.graph.invoke(None, cfg)
            else:
                raise NotWaiting(f"record {record_id} is not waiting at {waiting_node} (next={nxt})")

    def submit_expert(self, record_id: str, decision: dict) -> None:
        self._resume(record_id, "expert_review", "apply_expert", "expert", decision)

    def review(self, record_id: str, decision: dict) -> None:
        self._resume(record_id, "supervisor_review", "finalize", "review", decision)

    def discard(self, record_id: str, tenant_id: str) -> None:
        """Delete a draft. Works whether or not the graph reached the expert check."""
        nxt = self.next_nodes(record_id)
        if "expert_review" in nxt:
            self.submit_expert(record_id, {"action": "discard"})
        else:
            with self._lock(record_id):
                rec = self.deps.repo.get(tenant_id, record_id)
                if rec:
                    if rec.get("audio_path"):
                        self.deps.delete_audio(rec["audio_path"])
                    self.deps.repo.delete(tenant_id, record_id)
        self.forget(record_id)

    def forget(self, record_id: str) -> None:
        try:
            self.checkpointer.delete_thread(self.thread_id(record_id))
        except Exception:  # noqa: BLE001
            log.info("checkpoint cleanup skipped for %s", record_id)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


# ---------------------------------------------------------------------- app wiring

_runner: CaptureRunner | None = None
_checkpoint_pool: Any = None


def make_postgres_checkpointer(database_url: str):
    """PostgresSaver on its own small pool, with search_path pinned to the `langgraph` schema."""
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    def _configure(conn):
        conn.execute("set search_path to langgraph")

    pool = ConnectionPool(
        conninfo=database_url, min_size=1, max_size=2, open=True, configure=_configure,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    saver = PostgresSaver(pool)
    try:
        saver.setup()
    except Exception as e:  # noqa: BLE001
        pool.close()
        raise RuntimeError("LangGraph checkpoint setup failed. Did you run supabase/migrations/0003_phase2.sql "
                           "(it creates the `langgraph` schema)?") from e
    return saver, pool


def init_capture() -> CaptureRunner:
    """Call once on app startup (lifespan). Builds the real dependencies."""
    global _runner, _checkpoint_pool
    from app.core.answer_cache import AnswerCache
    from app.core.breaker import CircuitBreaker
    from app.core.llm_chain import ChainStructured
    from app.core.openai_compat import OpenAICompatClient
    from app.core.provider_config import llm_candidates, stt_candidates
    from app.core.stt_chain import STTChain

    from . import adapters
    from .errors import USER_MESSAGES as CAPTURE_MESSAGES
    from .repo import PostgresRepo
    from .settings import get_capture_settings

    s = get_capture_settings()
    repo = PostgresRepo(adapters.db_conn)
    llm_breaker = CircuitBreaker(s.PROVIDER_BREAKER_FAILURES, s.PROVIDER_BREAKER_COOLDOWN_SEC)
    stt_breaker = CircuitBreaker(s.PROVIDER_BREAKER_FAILURES, s.PROVIDER_BREAKER_COOLDOWN_SEC)
    llm_http = OpenAICompatClient(timeout=s.LLM_TIMEOUT_SEC)
    llm = llm_candidates(s)
    cache = AnswerCache(adapters.db_conn)
    deps = CaptureDeps(
        repo=repo,
        settings=s,
        stt_factory=lambda: STTChain(stt_candidates(s), breaker=stt_breaker, timeout=s.SARVAM_TIMEOUT_SEC,
                                     error_factory=lambda: CaptureError("stt_failed",
                                                                        CAPTURE_MESSAGES["stt_failed"])),
        llm_factory=lambda: ChainStructured(llm, breaker=llm_breaker, client=llm_http, timeout=s.LLM_TIMEOUT_SEC,
                                            error_factory=lambda: CaptureError(
                                                "llm_failed", CAPTURE_MESSAGES["llm_failed"])),
        download_audio=lambda path: adapters.storage_download("audio", path),
        delete_audio=lambda path: adapters.storage_delete("audio", path),
        manual_excerpts=adapters.manual_excerpts,
        rebuild_chunks=adapters.rebuild_record_chunks,
        invalidate_answer_cache=cache.invalidate_tenant,
    )
    saver, _checkpoint_pool = make_postgres_checkpointer(s.DATABASE_URL)
    n = repo.mark_stuck_failed("server_restarted")
    if n:
        log.info("marked %s interrupted capture(s) as failed", n)
    _runner = CaptureRunner(deps, saver)
    return _runner


def shutdown_capture() -> None:
    global _runner, _checkpoint_pool
    if _runner:
        _runner.shutdown()
    if _checkpoint_pool:
        _checkpoint_pool.close()
    _runner, _checkpoint_pool = None, None


def get_runner() -> CaptureRunner:
    if _runner is None:
        raise RuntimeError("Capture runner not started: call init_capture() in the app lifespan")
    return _runner


def set_runner(r: CaptureRunner | None) -> None:
    """Tests only."""
    global _runner
    _runner = r


__all__ = ["CaptureRunner", "NotWaiting", "init_capture", "shutdown_capture", "get_runner", "set_runner",
           "USER_MESSAGES"]
