"""In-memory fakes so Assist can be tested without Supabase, Sarvam or Groq."""
from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timedelta, timezone

from app.assist.errors import AssistError
from app.assist.llm import QuestionEn
from app.assist.pipeline import AssistDeps
from app.assist.repo import QUERY_UPDATABLE
from app.assist.service import AssistService, Storage
from app.assist.settings import AssistSettings
from app.assist.understand import Understanding
from app.capture.audio import PreparedAudio
from app.capture.errors import USER_MESSAGES as CAPTURE_MESSAGES
from app.capture.errors import CaptureError
from app.capture.sarvam import SttResult
from app.capture.schemas import Translated

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT = "22222222-2222-2222-2222-222222222222"
TECH = "aaaaaaaa-0000-0000-0000-000000000412"        # Amit Kale, technician, Hindi
TECH2 = "aaaaaaaa-0000-0000-0000-000000000518"       # Karthik Raman, technician, Tamil
EXPERT = "aaaaaaaa-0000-0000-0000-000000000107"      # Ramesh Patil, expert, Marathi
EXPERT2 = "aaaaaaaa-0000-0000-0000-000000000233"     # Anil Deshmukh, expert, Hindi
SUPERVISOR = "aaaaaaaa-0000-0000-0000-000000000001"  # Suresh Kulkarni, supervisor
OTHER_SUP = "bbbbbbbb-0000-0000-0000-000000000001"   # supervisor in another plant

USERS = {
    TECH: {"id": TECH, "tenant_id": TENANT, "name": "Amit Kale", "role": "technician", "language": "hi-IN"},
    TECH2: {"id": TECH2, "tenant_id": TENANT, "name": "Karthik Raman", "role": "technician", "language": "ta-IN"},
    EXPERT: {"id": EXPERT, "tenant_id": TENANT, "name": "Ramesh Patil", "role": "expert", "language": "mr-IN"},
    EXPERT2: {"id": EXPERT2, "tenant_id": TENANT, "name": "Anil Deshmukh", "role": "expert", "language": "hi-IN"},
    SUPERVISOR: {"id": SUPERVISOR, "tenant_id": TENANT, "name": "Suresh Kulkarni", "role": "supervisor",
                 "language": "hi-IN"},
    OTHER_SUP: {"id": OTHER_SUP, "tenant_id": OTHER_TENANT, "name": "Elsewhere", "role": "supervisor",
                "language": "en-IN"},
}

HP07 = {"id": "mmmmmmmm-0000-0000-0000-000000000007", "code": "HP-07", "name": "Hydraulic press", "line": "Line 2",
        "model_id": "model-hpx", "model": "HPX-200", "type": "hydraulic press", "qr_token": "a1b2c3d4e5f6a1b2c3d4e5f6"}
CNC03 = {"id": "mmmmmmmm-0000-0000-0000-000000000003", "code": "CNC-03", "name": "CNC lathe", "line": "Line 1",
         "model_id": "model-cl40", "model": "CL-40", "type": "cnc lathe", "qr_token": "ffeeddccbbaa99887766554433"}
MACHINES = [HP07, CNC03]

REC_R01 = "e0000000-0000-0000-0000-000000000001"     # approved, HP-07, by Ramesh
REC_DRAFT = "e0000000-0000-0000-0000-000000000099"   # pending, by Anil (not visible to technicians)
DOC_HPX = "dddddddd-0000-0000-0000-000000000200"
LOG_1 = "f0000000-0000-0000-0000-000000000001"

R01_TEXT = ("Machine HP-07 (HPX-200 hydraulic press). Symptom: pressure not building. Cause: relief valve "
            "loosened. Fix: reset relief valve to 210 bar. Steps: fit test gauge; set relief valve to 210 bar; "
            "tighten lock nut. Safety: lower the ram onto safety blocks first.")


def search_results(machine_code: str | None = "HP-07") -> list[dict]:
    same = machine_code == "HP-07"
    return [
        {"label": "E", "source_type": "record", "source_id": REC_R01, "chunk_id": "c-r01",
         "title": "Repair record · HP-07 · 14 Jan 2026 · Ramesh Patil", "section": None, "page": None,
         "text": R01_TEXT, "score": 0.05, "same_machine": same, "meta": {"seed_key": "R01"}},
        {"label": "M", "source_type": "manual", "source_id": DOC_HPX, "chunk_id": "c-m3",
         "title": "HPX-200 Service Manual · p.3", "section": "Troubleshooting", "page": 3,
         "text": "Pressure not building: check relief valve setting (210 bar). Check pump suction strainer.",
         "score": 0.04, "same_machine": False, "meta": {}},
        {"label": "H", "source_type": "log", "source_id": LOG_1, "chunk_id": "c-h1",
         "title": "Breakdown log · HP-07 · 3 Oct 2025", "section": None, "page": None,
         "text": "HP-07 pressure low. Replaced SK-200-R seal kit. 150 min down.", "score": 0.03,
         "same_machine": same, "meta": {"row": 14}},
    ]


GOOD_ANSWER = ("SAFETY: रैम को सेफ्टी ब्लॉक पर नीचे करें। [E1]\n"
               "1. पंप आउटलेट पर टेस्ट गेज लगाएँ। [E1]\n"
               "2. रिलीफ वाल्व को 210 bar पर सेट करें और लॉक नट कसें। [E1][M1]\n"
               "CHECK: प्रेशर 210 bar तक पहुँचना चाहिए। [M1]")


class FakeSearch:
    def __init__(self, results: list[dict] | None = None, confidence: float | None = None, fail: bool = False):
        self.results = results
        self.confidence = confidence
        self.fail = fail
        self.calls: list[tuple] = []

    def __call__(self, tenant_id, q, machine_code, k):
        self.calls.append((tenant_id, q, machine_code, k))
        if self.fail:
            raise AssistError("search_failed")
        res = search_results(machine_code) if self.results is None else self.results
        return {"results": copy.deepcopy(res), "confidence": self.confidence, "expanded_query": q}


class FakeWriter:
    """stream() yields the scripted answer in small chunks."""

    def __init__(self, answer: str = GOOD_ANSWER, chunk: int = 7, fail_before: bool = False,
                 fail_after: int | None = None, english: str | None = "AUTO", on_chunk=None):
        self.answer = answer
        self.chunk = chunk
        self.fail_before = fail_before
        self.fail_after = fail_after
        self.english = english
        self.on_chunk = on_chunk
        self.model_used = None
        self.stream_calls: list[dict] = []
        self.text_calls: list[dict] = []

    def stream(self, *, models, system, user, max_tokens=900):
        self.stream_calls.append({"models": models, "system": system, "user": user})
        if self.fail_before:
            raise AssistError("llm_failed")
        self.model_used = models[0]
        n = 0
        for i in range(0, len(self.answer), self.chunk):
            if self.fail_after is not None and n >= self.fail_after:
                raise AssistError("llm_failed")
            n += 1
            if self.on_chunk:
                self.on_chunk(n)
            yield self.answer[i:i + self.chunk]

    def text(self, *, model, system, user, max_tokens=900):
        self.text_calls.append({"model": model, "system": system, "user": user})
        if self.english is None:
            return None
        if self.english == "AUTO":
            return "EN| " + user
        return self.english


class FakeStructured:
    def __init__(self, fail_question: bool = False, understanding: Understanding | None = None):
        self.fail_question = fail_question
        self.understanding = understanding
        self.calls: list[str] = []
        self.users: list[str] = []

    def structured(self, *, model, system, user, schema_name, schema, out, max_tokens=1500, reasoning_effort="low"):
        self.calls.append(schema_name)
        self.users.append(user)
        if out is Understanding:
            if self.fail_question:
                raise CaptureError("llm_failed", CAPTURE_MESSAGES["llm_failed"])
            return self.understanding or Understanding(question_en="pressure is not building on HP-07")
        if out is QuestionEn:
            if self.fail_question:
                raise CaptureError("llm_failed", CAPTURE_MESSAGES["llm_failed"])
            return QuestionEn(question_en="pressure is not building on HP-07")
        if out is Translated:
            data = json.loads(user)
            conv = lambda v: ("[local] " + v) if isinstance(v, str) else v  # noqa: E731
            return Translated(symptom=conv(data.get("symptom")), cause=conv(data.get("cause")),
                              fix=conv(data.get("fix")), steps=[conv(x) for x in data.get("steps") or []],
                              safety_note=conv(data.get("safety_note")), issues=[], summary=None)
        raise AssertionError(schema_name)


class FakeSTT:
    def __init__(self, transcript: str = "HP-07 में pressure नहीं बन रहा है", fail: bool = False):
        self.transcript = transcript
        self.fail = fail
        self.calls = 0

    def transcribe_segments(self, segments, language_code=None):
        self.calls += 1
        if self.fail:
            raise CaptureError("stt_failed", CAPTURE_MESSAGES["stt_failed"])
        return SttResult(transcript=self.transcript, language_code="hi-IN", request_ids=["r1"])


class FakeCleaner:
    """Stands in for audio_clean.clean_audio."""

    def __init__(self, speech: float | None = 3.2, fail: bool = False):
        self.speech = speech
        self.fail = fail
        self.calls: list[dict] = []

    def __call__(self, raw, **kw):
        from app.assist.audio_clean import CleanAudio

        self.calls.append(kw)
        if raw.startswith(b"SILENT"):
            raise AssistError("no_speech")
        if self.fail or raw.startswith(b"SHORT"):
            return CleanAudio(raw, None, False)
        return CleanAudio(b"CLEANWAV" + raw, self.speech, True)


def fake_prepare(raw: bytes, **kw) -> PreparedAudio:
    if raw.startswith(b"SHORT"):
        raise CaptureError("too_short", CAPTURE_MESSAGES["too_short"], retryable=False)
    return PreparedAudio(segments=[b"seg"], seconds=4.2)


class FakeTTS:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    def synthesize(self, text, language):
        self.calls.append((text, language))
        if self.fail:
            raise AssistError("tts_failed")
        return b"RIFF" + b"\x00" * 100


# ---------------------------------------------------------------------------- repo

def _now():
    return datetime.now(timezone.utc)


class FakeAssistRepo:
    def __init__(self):
        self.queries: dict[str, dict] = {}
        self.feedback: dict[tuple[str, str], str] = {}
        self.escalations: dict[str, dict] = {}
        self.records: dict[str, dict] = {
            REC_R01: {"id": REC_R01, "tenant_id": TENANT, "machine_id": HP07["id"], "author_id": EXPERT,
                      "status": "approved", "stage": None, "language": "mr-IN", "source": "seed",
                      "fields": {"symptom": "pressure not building", "cause": "relief valve loosened",
                                 "fix": "reset relief valve to 210 bar",
                                 "steps": ["Fit test gauge", "Set relief valve to 210 bar", "Tighten lock nut"],
                                 "safety_note": "Lower the ram onto safety blocks first."},
                      "fields_local": None, "safety_note": "Lower the ram onto safety blocks first.",
                      "audio_path": f"{TENANT}/{REC_R01}.webm", "audio_seconds": 41.0,
                      "created_at": _now() - timedelta(days=30), "reviewed_at": _now() - timedelta(days=29),
                      "reviewed_by": SUPERVISOR, "escalation_id": None, "transcript_en": "..."},
            REC_DRAFT: {"id": REC_DRAFT, "tenant_id": TENANT, "machine_id": HP07["id"], "author_id": EXPERT2,
                        "status": "pending", "stage": None, "language": "hi-IN", "source": "capture",
                        "fields": {"symptom": "noise"}, "fields_local": None, "safety_note": None,
                        "audio_path": None, "audio_seconds": None, "created_at": _now(), "reviewed_at": None,
                        "reviewed_by": None, "escalation_id": None, "transcript_en": "..."},
        }
        self.documents = {DOC_HPX: {"id": DOC_HPX, "tenant_id": TENANT, "title": "HPX-200 Service Manual",
                                    "type": "manual", "file_path": f"{TENANT}/hpx.pdf", "pages": 4, "status": "ready",
                                    "model": "HPX-200"}}
        self.chunks = [
            {"tenant_id": TENANT, "source_id": DOC_HPX, "section": "Troubleshooting", "page": 3, "chunk_index": 0,
             "text": "Pressure not building: check relief valve setting (210 bar)."},
            {"tenant_id": TENANT, "source_id": DOC_HPX, "section": "Specs", "page": 1, "chunk_index": 0,
             "text": "Max pressure 210 bar."},
        ]
        self.logs = {LOG_1: {"id": LOG_1, "tenant_id": TENANT, "machine_id": HP07["id"],
                             "date": datetime(2025, 10, 3).date(), "fault": "pressure low",
                             "action": "replaced SK-200-R seal kit", "downtime_min": 150, "technician": "Vijay"}}
        self.query_updates: list[tuple[str, dict]] = []

    # machines
    def _machine(self, tenant_id, pred):
        if tenant_id != TENANT:
            return None
        for m in MACHINES:
            if pred(m):
                return {k: m[k] for k in ("id", "code", "name", "line", "model_id", "model", "type")}
        return None

    def machine_by_code(self, tenant_id, code):
        return self._machine(tenant_id, lambda m: m["code"].upper() == code.strip().upper())

    def machine_by_qr(self, tenant_id, token):
        return self._machine(tenant_id, lambda m: m["qr_token"] == token)

    def machine_codes(self, tenant_id):
        return [m["code"] for m in MACHINES] if tenant_id == TENANT else []

    def _machine_by_id(self, mid):
        return next((m for m in MACHINES if m["id"] == mid), None)

    # queries
    def create_query(self, *, query_id, tenant_id, user_id, machine_id, language, input_mode, audio_path,
                     question_original):
        self.queries[query_id] = {
            "id": query_id, "tenant_id": tenant_id, "user_id": user_id, "machine_id": machine_id,
            "question_original": question_original, "question_en": None, "language": language, "answer": None,
            "answer_local": None, "answer_parts": None, "sources": [], "citations": None, "confidence": None,
            "escalated": False, "latency_ms": None, "first_token_ms": None, "status": "answering",
            "input_mode": input_mode, "audio_path": audio_path, "audio_seconds": None, "error": None,
            "model": None, "created_at": _now(),
        }

    def update_query(self, tenant_id, query_id, **cols):
        bad = set(cols) - QUERY_UPDATABLE
        assert not bad, bad
        q = self.queries[query_id]
        assert q["tenant_id"] == tenant_id
        q.update(copy.deepcopy(cols))
        self.query_updates.append((query_id, cols))

    def _query_row(self, q):
        out = copy.deepcopy(q)
        m = self._machine_by_id(q["machine_id"]) if q["machine_id"] else None
        out.update(machine_code=m["code"] if m else None, machine_name=m["name"] if m else None,
                   machine_model=m["model"] if m else None, user_name=USERS[q["user_id"]]["name"],
                   feedback=self.feedback.get((q["id"], q["user_id"])))
        e = next((e for e in self.escalations.values() if e["query_id"] == q["id"]), None)
        out.update(escalation_id=e["id"] if e else None, escalation_status=e["status"] if e else None,
                   escalation_assigned_to=e["assigned_to"] if e else None,
                   escalation_assigned_name=USERS[e["assigned_to"]]["name"] if e and e["assigned_to"] else None,
                   escalation_answered_at=e["answered_at"] if e else None)
        return out

    def get_query(self, tenant_id, query_id):
        q = self.queries.get(query_id)
        if not q or q["tenant_id"] != tenant_id:
            return None
        return self._query_row(q)

    def list_queries(self, tenant_id, user_id, limit):
        rows = [self._query_row(q) for q in self.queries.values()
                if q["tenant_id"] == tenant_id and q["user_id"] == user_id and q["status"] != "cancelled"]
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        return rows[:limit]

    def mark_stuck_answering(self, error_code):
        n = 0
        for q in self.queries.values():
            if q["status"] == "answering":
                q["status"], q["error"] = "failed", error_code
                n += 1
        return n

    # feedback
    def upsert_feedback(self, tenant_id, query_id, user_id, outcome):
        self.feedback[(query_id, user_id)] = outcome

    # escalations
    def pick_expert(self, tenant_id, machine_id, exclude_user):
        experts = [u for u in USERS.values() if u["tenant_id"] == tenant_id and u["role"] == "expert"
                   and u["id"] != exclude_user]
        if not experts:
            return None

        def score(u):
            on_machine = sum(1 for r in self.records.values() if r["author_id"] == u["id"]
                             and r["status"] == "approved" and r["machine_id"] == machine_id)
            busy = sum(1 for e in self.escalations.values() if e["assigned_to"] == u["id"] and e["status"] == "open")
            return (-on_machine, busy, u["name"])

        return sorted(experts, key=score)[0]["id"]

    def create_escalation(self, *, tenant_id, query_id, asked_by, machine_id, note, assigned_to):
        if any(e["query_id"] == query_id for e in self.escalations.values()):
            return None
        eid = str(uuid.uuid4())
        self.escalations[eid] = {
            "id": eid, "tenant_id": tenant_id, "query_id": query_id, "status": "open", "assigned_to": assigned_to,
            "assigned_at": _now() if assigned_to else None, "asked_by": asked_by, "machine_id": machine_id,
            "note": note, "reply_text": None, "reply_local": None, "replied_by": None, "new_record_id": None,
            "created_at": _now(), "answered_at": None, "closed_at": None, "close_reason": None,
        }
        self.queries[query_id]["escalated"] = True
        return eid

    def _esc_row(self, e):
        q = self.queries[e["query_id"]]
        m = self._machine_by_id(e["machine_id"]) if e["machine_id"] else None
        rr = None
        if e["new_record_id"]:
            rr = self.records.get(e["new_record_id"])
        else:
            cands = [r for r in self.records.values() if r.get("escalation_id") == e["id"]]
            rr = sorted(cands, key=lambda r: r["created_at"], reverse=True)[0] if cands else None
        row = copy.deepcopy(e)
        row.update(
            question_original=q["question_original"], question_en=q["question_en"], question_language=q["language"],
            answer=q["answer"], answer_local=q["answer_local"], answer_parts=q["answer_parts"],
            sources=q["sources"], answer_status=q["status"], confidence=q["confidence"], asked_at=q["created_at"],
            query_user_id=q["user_id"],
            machine_code=m["code"] if m else None, machine_name=m["name"] if m else None,
            machine_line=m["line"] if m else None, machine_model=m["model"] if m else None,
            asked_by_name=USERS[e["asked_by"]]["name"], asked_by_language=USERS[e["asked_by"]]["language"],
            assigned_name=USERS[e["assigned_to"]]["name"] if e["assigned_to"] else None,
            replied_name=USERS[e["replied_by"]]["name"] if e["replied_by"] else None,
            feedback=self.feedback.get((q["id"], q["user_id"])),
            reply_record_id=rr["id"] if rr else None, reply_record_status=rr["status"] if rr else None,
            reply_record_stage=rr["stage"] if rr else None, reply_fields=copy.deepcopy(rr["fields"]) if rr else None,
            reply_fields_local=copy.deepcopy(rr["fields_local"]) if rr else None,
            reply_language=rr["language"] if rr else None, reply_audio_path=rr["audio_path"] if rr else None,
            reply_author_id=rr["author_id"] if rr else None, reply_transcript_en=rr["transcript_en"] if rr else None,
        )
        return row

    def get_escalation(self, tenant_id, escalation_id):
        e = self.escalations.get(escalation_id)
        if not e or e["tenant_id"] != tenant_id:
            return None
        return self._esc_row(e)

    def escalation_id_for_query(self, tenant_id, query_id):
        e = next((e for e in self.escalations.values() if e["query_id"] == query_id and e["tenant_id"] == tenant_id),
                 None)
        return e["id"] if e else None

    def list_escalations(self, tenant_id, *, status, assigned_to, include_unassigned, limit):
        out = []
        for e in self.escalations.values():
            if e["tenant_id"] != tenant_id or (status and e["status"] != status):
                continue
            if assigned_to:
                ok = e["assigned_to"] == assigned_to or (include_unassigned and e["assigned_to"] is None)
                if not ok:
                    continue
            out.append(self._esc_row(e))
        order = {"open": 0, "answered": 1, "closed": 2}
        out.sort(key=lambda r: (order[r["status"]], r["created_at"]))
        return out[:limit]

    def escalation_counts(self, tenant_id, user_id=None):
        es = [e for e in self.escalations.values() if e["tenant_id"] == tenant_id and e["status"] == "open"]
        return {"open": len(es), "unassigned": sum(1 for e in es if e["assigned_to"] is None),
                "mine": sum(1 for e in es if user_id and e["assigned_to"] == user_id)}

    def assign_escalation(self, tenant_id, escalation_id, user_id):
        e = self.escalations.get(escalation_id)
        if not e or e["tenant_id"] != tenant_id or e["status"] != "open":
            return False
        e["assigned_to"], e["assigned_at"] = user_id, _now()
        return True

    def close_escalation(self, tenant_id, escalation_id, reason):
        e = self.escalations.get(escalation_id)
        if not e or e["tenant_id"] != tenant_id or e["status"] == "closed":
            return False
        e.update(status="closed", closed_at=_now(), close_reason=reason)
        return True

    def close_open_for_query(self, tenant_id, query_id, reason):
        for e in self.escalations.values():
            if e["tenant_id"] == tenant_id and e["query_id"] == query_id and e["status"] == "open":
                e.update(status="closed", closed_at=_now(), close_reason=reason)
                return True
        return False

    def set_reply_text(self, tenant_id, escalation_id, user_id, text):
        e = self.escalations.get(escalation_id)
        if not e or e["tenant_id"] != tenant_id or e["status"] != "open":
            return False
        e.update(reply_text=text, replied_by=user_id, status="answered", answered_at=_now(), reply_local=None)
        if not e["assigned_to"]:
            e["assigned_to"], e["assigned_at"] = user_id, _now()
        return True

    def set_reply_local(self, tenant_id, escalation_id, data):
        self.escalations[escalation_id]["reply_local"] = copy.deepcopy(data)

    def link_reply_record(self, tenant_id, record_id, escalation_id):
        r = self.records[record_id]
        r["source"], r["escalation_id"] = "escalation", escalation_id

    # simulates 0004's trigger (repair_records status -> pending)
    def record_sent_to_supervisor(self, record_id):
        r = self.records[record_id]
        r["status"] = "pending"
        e = self.escalations.get(r.get("escalation_id"))
        if e and e["status"] != "closed":
            e.update(status="answered", new_record_id=record_id, replied_by=r["author_id"],
                     answered_at=e["answered_at"] or _now(), reply_local=None)

    # people
    def experts(self, tenant_id):
        rows = self._experts(tenant_id)
        return sorted(rows, key=lambda r: (0 if r["role"] == "expert" else 1, r["name"]))   # same order as SQL

    def _experts(self, tenant_id):
        return [{"id": u["id"], "name": u["name"], "role": u["role"], "language": u["language"],
                 "open_assigned": sum(1 for e in self.escalations.values() if e["assigned_to"] == u["id"]
                                      and e["status"] == "open"),
                 "approved_records": sum(1 for r in self.records.values() if r["author_id"] == u["id"]
                                         and r["status"] == "approved")}
                for u in USERS.values() if u["tenant_id"] == tenant_id and u["role"] in ("expert", "supervisor")]

    def user_in_tenant(self, tenant_id, user_id):
        u = USERS.get(user_id)
        return dict(u) if u and u["tenant_id"] == tenant_id else None

    # sources
    def record_source(self, tenant_id, record_id):
        r = self.records.get(record_id)
        if not r or r["tenant_id"] != tenant_id:
            return None
        m = self._machine_by_id(r["machine_id"])
        out = copy.deepcopy(r)
        out.update(machine_code=m["code"], machine_name=m["name"], machine_model=m["model"],
                   author_name=USERS[r["author_id"]]["name"],
                   reviewer_name=USERS[r["reviewed_by"]]["name"] if r.get("reviewed_by") else None)
        return out

    def manual_page(self, tenant_id, document_id, page):
        d = self.documents.get(document_id)
        if not d or d["tenant_id"] != tenant_id:
            return None
        out = copy.deepcopy(d)
        out["chunks"] = [c for c in self.chunks if c["source_id"] == document_id and (page is None or c["page"] == page)]
        return out

    def log_source(self, tenant_id, log_id):
        r = self.logs.get(log_id)
        if not r or r["tenant_id"] != tenant_id:
            return None
        m = self._machine_by_id(r["machine_id"])
        out = copy.deepcopy(r)
        out.update(machine_code=m["code"], machine_name=m["name"])
        return out


# ---------------------------------------------------------------------------- deps / service

class FakeStorage:
    def __init__(self):
        self.files: dict[tuple[str, str], bytes] = {}
        self.fail_upload = False

    def upload(self, bucket, path, data, content_type):
        if self.fail_upload:
            raise RuntimeError("storage down")
        self.files[(bucket, path)] = data

    def download(self, bucket, path):
        if (bucket, path) not in self.files:
            raise FileNotFoundError(path)
        return self.files[(bucket, path)]

    def signed_url(self, bucket, path, expires=3600):
        return f"https://signed/{bucket}/{path}"


class ReplyStarter:
    """Stands in for adapters.start_reply_capture: creates a draft record linked to the escalation."""

    def __init__(self, repo: FakeAssistRepo):
        self.repo = repo
        self.calls: list[dict] = []

    def __call__(self, **kw):
        self.calls.append(kw)
        self.repo.records[kw["record_id"]] = {
            "id": kw["record_id"], "tenant_id": kw["tenant_id"], "machine_id": kw["machine_id"],
            "author_id": kw["author_id"], "status": "draft", "stage": "queued", "language": kw["language"],
            "source": "capture", "fields": {}, "fields_local": None, "safety_note": None,
            "audio_path": kw["audio_path"], "audio_seconds": None, "created_at": _now(), "reviewed_at": None,
            "reviewed_by": None, "escalation_id": None, "transcript_en": kw["transcript_en"],
        }
        self.repo.link_reply_record(kw["tenant_id"], kw["record_id"], kw["escalation_id"])


def make_deps(*, repo=None, search=None, writer=None, structured=None, stt=None, cleaner=None, cache=None,
              **settings_over):
    repo = repo or FakeAssistRepo()
    search = search or FakeSearch()
    writer = writer or FakeWriter()
    structured = structured or FakeStructured()
    stt = stt or FakeSTT()
    cleaner = cleaner or FakeCleaner()
    prepared: list[tuple[bytes, dict]] = []

    def prepare(raw, **kw):
        prepared.append((raw, kw))
        return fake_prepare(raw, **kw)

    settings = AssistSettings(_env_file=None, SARVAM_API_KEY="x", GROQ_API_KEY="x", **settings_over)
    deps = AssistDeps(repo=repo, settings=settings, search=search, stt_factory=lambda: stt,
                      writer_factory=lambda: writer, structured_factory=lambda: structured,
                      prepare_audio=prepare, clean_audio=cleaner, machine_codes=repo.machine_codes, cache=cache)
    return deps, {"repo": repo, "search": search, "writer": writer, "structured": structured, "stt": stt,
                  "cleaner": cleaner, "prepared": prepared, "cache": cache}


def make_service(**kw):
    deps, spies = make_deps(**kw)
    storage = FakeStorage()
    tts = FakeTTS()
    starter = ReplyStarter(spies["repo"])
    svc = AssistService(deps, storage=Storage(upload=storage.upload, download=storage.download,
                                              signed_url=storage.signed_url),
                        tts_factory=lambda: tts, start_reply=starter)
    spies.update(storage=storage, tts=tts, starter=starter, service=svc)
    return svc, spies
