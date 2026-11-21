"""The Capture graph (LangGraph).

  START
    -> transcribe     audio -> English transcript (Sarvam, mode=translate)     stage: transcribing
    -> extract        transcript -> structured fields (gpt-oss-20b)            stage: extracting
    -> link           match symptom/cause/fix to the plant's lists (pg_trgm)
    -> check          AI review against manual excerpts (gpt-oss-120b)         stage: checking
    -> localize       fields -> expert's language (gpt-oss-20b)                stage: translating
    -> expert_review  INTERRUPT #1 (status expert_review, stage ready)
         |-- discard -> END (record + audio deleted)
         '-- submit  -> apply_expert   edits -> English, status pending
    -> supervisor_review  INTERRUPT #2
    -> finalize       approve: taxonomy ids + approved + search chunk
                      reject:  rejected + reason (chunk removed)
    -> END

Rules that keep it safe to resume:
- The DB row is the source of truth for the UI. Graph state only carries ids and human decisions.
- Nodes that call interrupt() do nothing else: LangGraph re-runs that node from the top on resume.
- Every node is idempotent: re-running after a failure (retry) gives the same result.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from . import prompts, translate
from .audio import prepare
from .errors import USER_MESSAGES, CaptureError
from .languages import is_english
from .repo import Repo, norm_label
from .schemas import AI_CHECK_SCHEMA, EXTRACTION_SCHEMA, AICheck, Extraction
from .settings import CaptureSettings

log = logging.getLogger("kaarigar.capture.graph")


class CaptureState(TypedDict, total=False):
    record_id: str
    tenant_id: str
    expert: dict | None     # {"action": "submit"|"discard", "edits": {...}, "edit_language": "mr-IN"}
    review: dict | None     # {"action": "approve"|"reject", "edits": {...}, "reason": str, "reviewer_id": str}
    outcome: str | None     # discarded | approved | rejected


@dataclass
class CaptureDeps:
    repo: Repo
    settings: CaptureSettings
    stt_factory: Callable[[], Any]                       # -> SarvamClient-like (transcribe_segments)
    llm_factory: Callable[[], Any]                       # -> GroqLLM-like (structured)
    download_audio: Callable[[str], bytes]               # audio_path -> bytes
    delete_audio: Callable[[str], None]                  # audio_path -> None
    manual_excerpts: Callable[[str, str, str | None, int], list[dict]]
    rebuild_chunks: Callable[[str], None]
    invalidate_answer_cache: Callable[[str], Any] | None = None   # tenant_id -> delete cached answers
    now: Callable[[], datetime] = field(default=lambda: datetime.now(timezone.utc))


def _machine(rec: dict) -> dict:
    return {"code": rec["machine_code"], "model": rec.get("machine_model"), "type": rec.get("machine_type")}


def _fields(rec: dict) -> dict:
    return dict(rec.get("fields") or {})


def link_taxonomy(deps: CaptureDeps, tenant_id: str, fields: dict) -> tuple[dict, dict]:
    """Suggest existing symptom/cause/fix rows for the record. Returns (links, ids)."""
    links: dict = {}
    ids: dict = {}
    for kind in ("symptom", "cause", "fix"):
        text = fields.get(kind)
        if not text:
            links[kind] = None
            ids[f"{kind}_id"] = None
            continue
        m = deps.repo.match_taxonomy(tenant_id, kind, text)
        if m and m["sim"] >= deps.settings.TAXONOMY_MATCH_MIN:
            links[kind] = {"id": m["id"], "name": m["name"], "sim": round(m["sim"], 3), "new": False}
            ids[f"{kind}_id"] = m["id"]
        else:
            links[kind] = {"id": None, "name": norm_label(text), "sim": round(m["sim"], 3) if m else 0.0, "new": True}
            ids[f"{kind}_id"] = None
    return links, ids


def build_graph(deps: CaptureDeps, checkpointer: Any):
    s = deps.settings

    def _get(state: CaptureState) -> dict:
        rec = deps.repo.get(state["tenant_id"], state["record_id"])
        if rec is None:
            raise CaptureError("internal", USER_MESSAGES["internal"], retryable=False)
        return rec

    def _upd(state: CaptureState, **cols: Any) -> None:
        deps.repo.update(state["tenant_id"], state["record_id"], **cols)

    def _invalidate_cache(d: CaptureDeps, tenant_id: str) -> None:
        if not d.invalidate_answer_cache:
            return
        try:
            d.invalidate_answer_cache(tenant_id)
        except Exception as e:  # noqa: BLE001  knowledge is already saved; stale cache expires in 7 days
            log.info("answer cache invalidation skipped: %s", type(e).__name__)

    # ------------------------------------------------------------------ nodes
    def transcribe(state: CaptureState) -> dict:
        rec = _get(state)
        if rec.get("transcript_en"):            # dev text mode, or retry after STT already worked
            return {}
        _upd(state, stage="transcribing", error=None)
        if not rec.get("audio_path"):
            raise CaptureError("bad_audio", USER_MESSAGES["bad_audio"], retryable=False)
        raw = deps.download_audio(rec["audio_path"])
        audio = prepare(raw, segment_sec=s.STT_SEGMENT_SEC, min_sec=s.MIN_RECORDING_SEC,
                        max_sec=s.MAX_RECORDING_SEC)
        stt = deps.stt_factory().transcribe_segments(audio.segments)
        if len(stt.transcript.split()) < 3:
            raise CaptureError("no_speech", USER_MESSAGES["no_speech"], retryable=False)
        f = _fields(rec)
        f["stt"] = {"segments": len(audio.segments), "language_detected": stt.language_code,
                    "request_ids": stt.request_ids[:10]}
        _upd(state, transcript_en=stt.transcript, audio_seconds=audio.seconds, fields=f)
        return {}

    def extract(state: CaptureState) -> dict:
        rec = _get(state)
        _upd(state, stage="extracting", error=None)
        ext: Extraction = deps.llm_factory().structured(
            model=s.GROQ_MODEL_SMALL, system=prompts.EXTRACT_SYSTEM,
            user=prompts.extract_user(_machine(rec), rec["transcript_en"], deps.repo.glossary(state["tenant_id"])),
            schema_name="repair_record", schema=EXTRACTION_SCHEMA, out=Extraction, max_tokens=1800,
        )
        f = _fields(rec)
        f.update(ext.model_dump())
        _upd(state, fields=f, safety_note=ext.safety_note)
        return {}

    def link(state: CaptureState) -> dict:
        rec = _get(state)
        f = _fields(rec)
        links, ids = link_taxonomy(deps, state["tenant_id"], f)
        f["links"] = links
        _upd(state, fields=f, **ids)
        return {}

    def check(state: CaptureState) -> dict:
        rec = _get(state)
        _upd(state, stage="checking")
        f = _fields(rec)
        query = f.get("symptom") or (rec.get("transcript_en") or "")[:200]
        excerpts = deps.manual_excerpts(state["tenant_id"], query, rec["machine_code"], s.CHECK_MANUAL_CONTEXT)
        chk: AICheck = deps.llm_factory().structured(
            model=s.GROQ_MODEL_LARGE, system=prompts.CHECK_SYSTEM,
            user=prompts.check_user(_machine(rec), f, rec.get("transcript_en") or "", excerpts),
            schema_name="ai_check", schema=AI_CHECK_SCHEMA, out=AICheck, max_tokens=1500,
        )
        data = chk.model_dump()
        if f.get("is_repair_note") is False and not any(i["field"] == "general" for i in data["issues"]):
            data["issues"].insert(0, {"field": "general", "severity": "high",
                                      "message": "This doesn't sound like a repair note. Please record again."})
        data["manual_sources"] = [e.get("title") for e in excerpts]
        _upd(state, ai_check=data)
        return {}

    def localize(state: CaptureState) -> dict:
        rec = _get(state)
        local = None
        if not is_english(rec.get("language")):
            _upd(state, stage="translating")
            try:
                local = translate.to_local(deps.llm_factory(), s.GROQ_MODEL_SMALL, _fields(rec),
                                           rec.get("ai_check"), rec["language"])
            except CaptureError:
                local = None   # show English rather than block the expert
                log.info("translation skipped for record %s", state["record_id"])
        _upd(state, fields_local=local, stage="ready", status="expert_review", error=None)
        return {}

    def expert_review(state: CaptureState) -> dict:
        decision = interrupt({"stage": "expert_review", "record_id": state["record_id"]})
        return {"expert": decision}

    def route_expert(state: CaptureState) -> str:
        return "discard" if (state.get("expert") or {}).get("action") == "discard" else "apply_expert"

    def discard(state: CaptureState) -> dict:
        rec = deps.repo.get(state["tenant_id"], state["record_id"])
        if rec:
            if rec.get("audio_path"):
                deps.delete_audio(rec["audio_path"])
            deps.repo.delete(state["tenant_id"], state["record_id"])
        return {"outcome": "discarded"}

    def apply_expert(state: CaptureState) -> dict:
        rec = _get(state)
        d = state.get("expert") or {}
        edits = dict(d.get("edits") or {})
        lang = d.get("edit_language") or "en-IN"
        f = _fields(rec)
        local = dict(rec.get("fields_local") or {}) or None
        cols: dict = {}
        if edits:
            edits_en = translate.edits_to_english(deps.llm_factory(), s.GROQ_MODEL_SMALL, edits, lang)
            f.update(edits_en)
            if local is not None and not is_english(lang):
                for k, v in edits.items():          # keep what the expert typed for their own view
                    if k in local:
                        local[k] = v
            if {"symptom", "cause", "fix"} & set(edits):
                links, ids = link_taxonomy(deps, state["tenant_id"], f)
                f["links"] = links
                cols.update(ids)
            f["missing"] = [k for k in ("symptom", "cause", "fix", "steps", "safety_note") if not f.get(k)]
        _upd(state, fields=f, fields_local=local, safety_note=f.get("safety_note"),
             status="pending", submitted_at=deps.now(), edited_by_expert=bool(edits), stage=None, error=None,
             **cols)
        return {}

    def supervisor_review(state: CaptureState) -> dict:
        decision = interrupt({"stage": "supervisor_review", "record_id": state["record_id"]})
        return {"review": decision}

    def finalize(state: CaptureState) -> dict:
        rec = _get(state)
        d = state.get("review") or {}
        t, rid = state["tenant_id"], state["record_id"]
        if d.get("action") == "approve":
            edits = dict(d.get("edits") or {})
            f = _fields(rec)
            f.update(edits)
            ids: dict = {}
            for kind in ("symptom", "cause", "fix"):
                name = f.get(kind)
                if not name:
                    ids[f"{kind}_id"] = None
                    continue
                m = deps.repo.match_taxonomy(t, kind, name)
                if m and m["sim"] >= s.TAXONOMY_MATCH_MIN:
                    ids[f"{kind}_id"] = m["id"]
                    if kind == "symptom" and m["sim"] < 0.95:
                        deps.repo.add_symptom_alias(t, m["id"], name)   # new phrasing helps graph search
                else:
                    ids[f"{kind}_id"] = deps.repo.ensure_taxonomy(t, kind, name)
            _upd(state, fields=f, safety_note=f.get("safety_note"), status="approved",
                 reviewed_by=d.get("reviewer_id"), reviewed_at=deps.now(), reject_reason=None,
                 edited_by_reviewer=bool(edits), **ids)
            deps.rebuild_chunks(rid)
            _invalidate_cache(deps, t)
            return {"outcome": "approved"}
        _upd(state, status="rejected", reject_reason=(d.get("reason") or "")[:500],
             reviewed_by=d.get("reviewer_id"), reviewed_at=deps.now())
        deps.rebuild_chunks(rid)   # makes sure no chunk exists for a rejected record
        _invalidate_cache(deps, t)
        return {"outcome": "rejected"}

    # ------------------------------------------------------------------ wiring
    g = StateGraph(CaptureState)
    for name, fn in [("transcribe", transcribe), ("extract", extract), ("link", link), ("check", check),
                     ("localize", localize), ("expert_review", expert_review), ("discard", discard),
                     ("apply_expert", apply_expert), ("supervisor_review", supervisor_review),
                     ("finalize", finalize)]:
        g.add_node(name, fn)
    g.add_edge(START, "transcribe")
    g.add_edge("transcribe", "extract")
    g.add_edge("extract", "link")
    g.add_edge("link", "check")
    g.add_edge("check", "localize")
    g.add_edge("localize", "expert_review")
    g.add_conditional_edges("expert_review", route_expert, {"discard": "discard", "apply_expert": "apply_expert"})
    g.add_edge("discard", END)
    g.add_edge("apply_expert", "supervisor_review")
    g.add_edge("supervisor_review", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)
