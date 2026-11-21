"""One question, start to finish. Runs in a worker thread; talks to the client only through `emit`.

    clean audio  noise filter + trim silence on the server (ffmpeg); no speech -> refused before Sarvam
    transcribe   voice -> text in the technician's own words (Sarvam saaras:v3, mode=codemix)   stage: listening
    understand   pre_clean (fillers, repeats, E-05 / HP-07 codes) + gpt-oss-20b -> one clean English question,
                 error codes, what was already tried, off-topic check                              stage: understanding
    search       Phase 1 hybrid search -> top sources with refs E1/M1/H1                          stage: searching
    write        streamed answer in the technician's language (gpt-oss-120b, falls back to 20b)  stage: writing
    save         parse + check refs + confidence -> queries row -> `done`
    afterwards   English copy of the answer for managers (not on the technician's clock)

Rules
- Nothing is made up: no sources -> NO_ANSWER without calling the writer; an answer with no valid refs
  is saved as no_answer.
- The `queries` row is the record of what happened (status answering -> answered | no_answer | failed | cancelled).
- If the client goes away, `cancelled()` turns true and the run stops at the next check.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.capture.errors import CaptureError
from app.capture.languages import is_english
from app.core.answer_cache import chunk_key, machine_key, question_key

from . import answer_format as af
from . import prompts
from .errors import USER_MESSAGES, AssistError
from .settings import AssistSettings
from .understand import Understanding, needs_ai, pre_clean, understand

log = logging.getLogger("kaarigar.assist.pipeline")

Emit = Callable[[str, dict], None]


@dataclass
class AssistDeps:
    repo: Any
    settings: AssistSettings
    search: Callable[[str, str, str | None, int], dict]      # adapters.hybrid_search
    stt_factory: Callable[[], Any]                             # -> transcribe_segments(segments, language_code)
    writer_factory: Callable[[], Any]                          # -> GroqWriter-like (stream, text, model_used)
    structured_factory: Callable[[], Any]                      # -> Phase 2 GroqLLM-like (structured)
    prepare_audio: Callable[..., Any]                          # app.capture.audio.prepare
    clean_audio: Callable[..., Any] | None = None              # audio_clean.clean_audio (None = skip)
    machine_codes: Callable[[str], list[str]] = field(default=lambda tenant_id: [])
    cache: Any = None                                          # app.core.answer_cache.AnswerCache
    clock: Callable[[], float] = field(default=time.monotonic)


@dataclass
class AskRequest:
    query_id: str
    tenant_id: str
    user_id: str
    language: str
    machine: dict | None = None           # {id, code, name, model, type} or None for "any machine"
    text: str | None = None               # typed question
    audio: bytes | None = None            # recorded question


class AssistPipeline:
    def __init__(self, deps: AssistDeps):
        self.d = deps
        self.s = deps.settings

    # ------------------------------------------------------------------ public
    def run(self, req: AskRequest, emit: Emit, cancelled: Callable[[], bool] = lambda: False) -> str:
        t0 = self.d.clock()
        repo = self.d.repo
        try:
            original, audio_seconds = self._question_text(req, emit)
            if cancelled():
                return self._cancel(req)

            u = self._understand(req, original, emit)
            question_en = u.question_en
            understood = {"question_en": u.question_en, "error_codes": u.error_codes,
                          "already_tried": u.already_tried, "is_repair_question": u.is_repair_question}
            repo.update_query(req.tenant_id, req.query_id, question_original=original, question_en=question_en,
                              audio_seconds=audio_seconds)
            emit("question", {"original": original, "en": question_en, "language": req.language,
                              "already_tried": u.already_tried})
            if cancelled():
                return self._cancel(req)

            found: dict = {"results": [], "confidence": None}
            if u.is_repair_question:
                emit("stage", {"stage": "searching"})
                found = self.d.search(req.tenant_id, question_en, req.machine["code"] if req.machine else None,
                                      self.s.SEARCH_K)
            results = self._drop_low_scores(found.get("results") or [])
            sources = af.build_sources(results, self.s.CONTEXT_K)
            emit("sources", {"sources": af.public_sources(sources)})
            if cancelled():
                return self._cancel(req)

            m_key = machine_key(req.machine)
            q_key = question_key(question_en)
            c_key = chunk_key(sources)
            cached = None
            if sources and self.s.ANSWER_CACHE and self.d.cache is not None:
                try:
                    cached = self.d.cache.get(req.tenant_id, m_key, q_key, c_key)
                except Exception as e:  # noqa: BLE001  cache is an optimisation, never a blocker
                    log.info("answer cache read skipped: %s", type(e).__name__)

            if not sources:
                parsed = af.ParsedAnswer(no_answer=True)
                first_ms, model, provider = None, None, None
            elif cached:
                emit("stage", {"stage": "writing"})
                parsed = af.parse_answer(cached.get("answer_local") or "", {s["ref"] for s in sources})
                if not parsed.no_answer and not parsed.refs_used:
                    parsed = af.ParsedAnswer(no_answer=True)
                text_out = af.render_answer(parsed)
                emit("delta", {"text": text_out})
                first_ms, model, provider = 0, cached.get("model"), cached.get("provider")
                log.info("answer cache hit tenant=%s machine=%s", req.tenant_id, m_key)
            else:
                emit("stage", {"stage": "writing"})
                text_out, first_ms, model, provider, was_cancelled = self._write(
                    req, question_en, original, sources, emit, cancelled, t0, u.already_tried)
                if was_cancelled:
                    return self._cancel(req)
                parsed = af.parse_answer(text_out, {s["ref"] for s in sources})
                if not parsed.no_answer and not parsed.refs_used:
                    log.info("answer for %s had no valid refs: saved as no_answer", req.query_id)
                    parsed = af.ParsedAnswer(no_answer=True, dropped_refs=parsed.dropped_refs)

            conf = af.confidence(parsed, sources, found.get("confidence"))
            status = "no_answer" if parsed.no_answer else "answered"
            latency = int((self.d.clock() - t0) * 1000)
            used = [s for s in sources if s["ref"] in parsed.refs_used]
            citations = [{"ref": s["ref"], "source_type": s["source_type"], "source_id": s["source_id"],
                          "seed_key": s.get("seed_key")} for s in used]
            answer_local = af.render_answer(parsed)
            repo.update_query(
                req.tenant_id, req.query_id, status=status, answer_local=answer_local,
                answer_parts={**parsed.as_dict(), "understanding": understood}, sources=af.public_sources(sources),
                citations=citations, confidence=conf, latency_ms=latency, first_token_ms=first_ms, model=model,
                error=None,
            )
            emit("done", {
                "query_id": req.query_id, "status": status, "parts": parsed.as_dict(), "confidence": conf,
                "suggest_escalate": status == "no_answer" or conf < self.s.ESCALATE_BELOW,
                "latency_ms": latency, "off_topic": not u.is_repair_question, "understanding": understood,
                "provider": provider,                    # hidden debug: which provider wrote this answer
            })
            if status == "answered" and citations and not cached and self.s.ANSWER_CACHE and self.d.cache is not None:
                try:
                    self.d.cache.put(tenant_id=req.tenant_id, machine=m_key, q_key=q_key, c_key=c_key,
                                     answer_local=answer_local, sources=af.public_sources(sources),
                                     citations=citations, confidence=conf, model=model, provider=provider)
                except Exception as e:  # noqa: BLE001
                    log.info("answer cache write skipped: %s", type(e).__name__)
            if status == "answered":
                self._english_copy(req, parsed)
            return status
        except AssistError as e:
            return self._fail(req, emit, e.code, e.user_message)
        except CaptureError as e:        # audio checks / Sarvam errors from Phase 2 helpers
            code = e.code if e.code in USER_MESSAGES else "internal"
            return self._fail(req, emit, code, USER_MESSAGES[code])
        except Exception:  # noqa: BLE001
            log.exception("assist %s crashed", req.query_id)   # stack trace only, no content
            return self._fail(req, emit, "internal", USER_MESSAGES["internal"])

    # ------------------------------------------------------------------ steps
    def _question_text(self, req: AskRequest, emit: Emit) -> tuple[str, float | None]:
        if req.text is not None:
            return " ".join(req.text.split()), None
        emit("stage", {"stage": "listening"})
        raw, min_sec = req.audio or b"", self.s.MIN_QUESTION_SEC
        if self.d.clean_audio is not None and self.s.AUDIO_CLEAN:
            cleaned = self.d.clean_audio(raw, max_sec=self.s.MAX_QUESTION_SEC, min_speech_sec=self.s.MIN_SPEECH_SEC)
            if cleaned.cleaned:
                raw, min_sec = cleaned.data, min(self.s.MIN_SPEECH_SEC, min_sec)   # already checked: speech is there
        audio = self.d.prepare_audio(raw, segment_sec=self.s.STT_SEGMENT_SEC,
                                     min_sec=min_sec, max_sec=self.s.MAX_QUESTION_SEC + 2)
        stt = self.d.stt_factory().transcribe_segments(audio.segments)
        text = " ".join((stt.transcript or "").split())
        if len(text.split()) < 2:
            raise AssistError("no_speech")
        return text, float(audio.seconds)

    def _understand(self, req: AskRequest, original: str, emit: Emit) -> Understanding:
        """Clean question for search + writer. Never raises: falls back to the pre-cleaned text."""
        try:
            codes = self.d.machine_codes(req.tenant_id)
        except Exception:  # noqa: BLE001
            codes = []
        pre = pre_clean(original, codes)
        if not needs_ai(pre, req.language, voice=req.audio is not None):
            return Understanding(question_en=pre)
        emit("stage", {"stage": "understanding"})
        u = understand(self.d.structured_factory(), self.s.GROQ_MODEL_SMALL, pre, req.machine)
        if (u is None or not u.question_en) and self.s.GROQ_MODEL_ANSWER != self.s.GROQ_MODEL_SMALL:
            # The small model is the first to hit Groq's free-tier rate limit. The answer model
            # is usually still available, so use it rather than searching the uncleaned text.
            u = understand(self.d.structured_factory(), self.s.GROQ_MODEL_ANSWER, pre, req.machine)
        if u is None or not u.question_en:
            return Understanding(question_en=pre)   # search still finds codes like E-05 in the original text
        missing = [c for c in u.error_codes if c.upper() not in u.question_en.upper()]
        if missing:                                  # codes are the strongest search signal: never lose them
            u.question_en = f"{u.question_en} ({', '.join(missing)})"
        return u

    def _drop_low_scores(self, results: list[dict]) -> list[dict]:
        """Drop chunks much weaker than the best match: they add prompt tokens without helping."""
        if not results:
            return results
        scores = [float(r.get("score") or 0.0) for r in results]
        top = max(scores)
        if top <= 0:
            return results
        floor = top * self.s.MIN_SCORE_RATIO
        kept = [r for r, sc in zip(results, scores) if sc >= floor]
        return kept or results[:1]

    def _write(self, req: AskRequest, question_en: str, original: str, sources: list[dict], emit: Emit,
               cancelled: Callable[[], bool], t0: float,
               already_tried: str | None = None) -> tuple[str, int | None, str | None, str | None, bool]:
        writer = self.d.writer_factory()
        gate = af.NoAnswerGate()
        parts: list[str] = []
        first_ms: int | None = None
        kwargs: dict[str, Any] = {}
        if getattr(writer, "accepts_validation", False):
            valid = {s["ref"] for s in sources}

            def validate(text: str) -> bool:
                return af.is_no_answer(text) or bool(af.parse_answer(text, valid).refs_used)

            kwargs["validate"] = validate
            kwargs["flush_when"] = lambda buf: bool(af.REF_RE.search(buf))
        stream = writer.stream(
            models=[self.s.GROQ_MODEL_ANSWER, self.s.GROQ_MODEL_SMALL],
            system=prompts.answer_system(req.language),
            user=prompts.answer_user(req.machine, question_en, original, sources, self.s.SOURCE_CHARS,
                                     already_tried=already_tried, language=req.language),
            max_tokens=self.s.ANSWER_MAX_TOKENS,
            **kwargs,
        )
        try:
            for chunk in stream:
                if cancelled():
                    return ("".join(parts), first_ms, getattr(writer, "model_used", None),
                            getattr(writer, "provider_used", None), True)
                parts.append(chunk)
                out = gate.feed(chunk)
                if out:
                    if first_ms is None:
                        first_ms = int((self.d.clock() - t0) * 1000)
                    emit("delta", {"text": out})
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()
        tail = gate.flush()
        if tail:
            if first_ms is None:
                first_ms = int((self.d.clock() - t0) * 1000)
            emit("delta", {"text": tail})
        return ("".join(parts), first_ms, getattr(writer, "model_used", None),
                getattr(writer, "provider_used", None), False)

    def _english_copy(self, req: AskRequest, parsed: af.ParsedAnswer) -> None:
        """Managers and escalations read English. Runs after `done`, so the technician never waits for it."""
        try:
            local = af.render_answer(parsed)
            if is_english(req.language):
                self.d.repo.update_query(req.tenant_id, req.query_id, answer=local)
                return
            en = self.d.writer_factory().text(model=self.s.GROQ_MODEL_SMALL, system=prompts.ANSWER_EN_SYSTEM,
                                              user=local, max_tokens=700)
            if en:
                again = af.parse_answer(en, set(parsed.refs_used))
                same_shape = (not again.no_answer and len(again.safety) == len(parsed.safety)
                              and len(again.steps) == len(parsed.steps) and bool(again.check) == bool(parsed.check))
                # Keep the clean version only if no line was lost in translation; otherwise keep the raw text
                self.d.repo.update_query(req.tenant_id, req.query_id,
                                         answer=af.render_answer(again) if same_shape else en.strip()[:4000])
        except Exception:  # noqa: BLE001
            log.info("english copy skipped for %s", req.query_id)

    # ------------------------------------------------------------------ endings
    def _cancel(self, req: AskRequest) -> str:
        try:
            self.d.repo.update_query(req.tenant_id, req.query_id, status="cancelled")
        except Exception:  # noqa: BLE001
            log.info("could not mark %s cancelled", req.query_id)
        return "cancelled"

    def _fail(self, req: AskRequest, emit: Emit, code: str, message: str) -> str:
        log.info("assist %s failed: %s", req.query_id, code)
        try:
            self.d.repo.update_query(req.tenant_id, req.query_id, status="failed", error=code)
        except Exception:  # noqa: BLE001
            log.exception("could not mark %s failed", req.query_id)
        emit("error", {"query_id": req.query_id, "code": code, "message": message})
        return "failed"
