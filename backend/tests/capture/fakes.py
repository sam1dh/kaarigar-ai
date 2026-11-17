"""In-memory fakes so the Capture graph can be tested without Supabase, Sarvam or Groq."""
from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone

from app.capture.errors import USER_MESSAGES, CaptureError
from app.capture.graph import CaptureDeps
from app.capture.repo import TAXONOMY_TABLES, UPDATABLE, norm_label
from app.capture.schemas import AICheck, Extraction, Translated
from app.capture.sarvam import SttResult
from app.capture.settings import CaptureSettings

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT = "22222222-2222-2222-2222-222222222222"
EXPERT = "aaaaaaaa-0000-0000-0000-000000000107"      # Ramesh
SUPERVISOR = "aaaaaaaa-0000-0000-0000-000000000001"  # Suresh
TECH = "aaaaaaaa-0000-0000-0000-000000000412"        # Amit
MACHINE = {"id": "mmmmmmmm-0000-0000-0000-000000000007", "code": "HP-07", "name": "Hydraulic press",
           "line": "Line 2", "model_id": "model-hpx", "model": "HPX-200", "type": "hydraulic press"}
USERS = {EXPERT: "Ramesh Patil", SUPERVISOR: "Suresh Kulkarni", TECH: "Amit Kale"}


def _sim(a: str, b: str) -> float:
    """Tiny trigram-ish similarity good enough for tests."""
    def grams(s: str) -> set[str]:
        s = f"  {s.lower()} "
        return {s[i:i + 3] for i in range(len(s) - 2)}
    ga, gb = grams(a), grams(b)
    return len(ga & gb) / max(1, len(ga | gb))


class FakeRepo:
    def __init__(self):
        self.records: dict[str, dict] = {}
        self.taxonomy = {k: {} for k in TAXONOMY_TABLES}   # kind -> {id: {"name", "aliases"}}
        self.taxonomy["symptom"]["sym-press"] = {"name": "pressure not building", "aliases": ["low pressure"]}
        self.updates: list[tuple[str, dict]] = []

    def machine_by_code(self, tenant_id, code):
        return dict(MACHINE) if tenant_id == TENANT and code.strip().upper() == "HP-07" else None

    def create_record(self, *, record_id, tenant_id, machine_id, author_id, language, audio_path, transcript_en):
        self.records[record_id] = {
            "id": record_id, "tenant_id": tenant_id, "machine_id": machine_id, "author_id": author_id,
            "audio_path": audio_path, "transcript_en": transcript_en, "symptom_id": None, "cause_id": None,
            "fix_id": None, "safety_note": None, "fields": {}, "ai_check": None, "status": "draft",
            "reject_reason": None, "reviewed_by": None, "reviewed_at": None, "source": "capture",
            "created_at": datetime.now(timezone.utc), "language": language, "audio_seconds": None,
            "stage": "queued", "error": None, "fields_local": None, "submitted_at": None,
            "edited_by_expert": False, "edited_by_reviewer": False,
        }

    def get(self, tenant_id, record_id):
        r = self.records.get(record_id)
        if not r or r["tenant_id"] != tenant_id:
            return None
        out = copy.deepcopy(r)
        out.update(machine_code=MACHINE["code"], machine_name=MACHINE["name"], machine_line=MACHINE["line"],
                   machine_model=MACHINE["model"], machine_type=MACHINE["type"],
                   author_name=USERS.get(r["author_id"]), reviewer_name=USERS.get(r["reviewed_by"]))
        return out

    def update(self, tenant_id, record_id, **cols):
        bad = set(cols) - UPDATABLE
        assert not bad, bad
        r = self.records.get(record_id)
        assert r and r["tenant_id"] == tenant_id
        r.update(copy.deepcopy(cols))
        self.updates.append((record_id, cols))

    def delete(self, tenant_id, record_id):
        r = self.records.get(record_id)
        if r and r["tenant_id"] == tenant_id:
            del self.records[record_id]

    def glossary(self, tenant_id):
        return [{"term": "thak-thak", "meaning": "knocking sound"}]

    def match_taxonomy(self, tenant_id, kind, text):
        best = None
        for tid, row in self.taxonomy[kind].items():
            sim = max([_sim(row["name"], text)] + [_sim(a, text) for a in row["aliases"]])
            if best is None or sim > best["sim"]:
                best = {"id": tid, "name": row["name"], "sim": sim}
        return best

    def ensure_taxonomy(self, tenant_id, kind, name):
        n = norm_label(name)
        for tid, row in self.taxonomy[kind].items():
            if row["name"] == n:
                return tid
        tid = f"{kind}-{uuid.uuid4().hex[:6]}"
        self.taxonomy[kind][tid] = {"name": n, "aliases": []}
        return tid

    def add_symptom_alias(self, tenant_id, symptom_id, alias):
        row = self.taxonomy["symptom"][symptom_id]
        a = norm_label(alias)
        if a != row["name"] and a not in row["aliases"]:
            row["aliases"].append(a)

    def list_by_author(self, tenant_id, author_id, machine_id, limit):
        return [self.get(tenant_id, r["id"]) for r in self.records.values()
                if r["tenant_id"] == tenant_id and r["author_id"] == author_id][:limit]

    def review_queue(self, tenant_id, limit):
        return [self.get(tenant_id, r["id"]) for r in self.records.values()
                if r["tenant_id"] == tenant_id and r["status"] == "pending"][:limit]

    def pending_count(self, tenant_id):
        return len(self.review_queue(tenant_id, 1000))

    def mark_stuck_failed(self, error_code):
        n = 0
        for r in self.records.values():
            if r["stage"] in ("queued", "transcribing", "extracting", "checking", "translating"):
                r["stage"], r["error"] = "failed", error_code
                n += 1
        return n


class FakeSTT:
    def __init__(self, transcript="Pressure was not building on HP-07, only 150 bar. Someone loosened the relief "
                                  "valve. I set it back to 210 bar with the test gauge and tightened the lock nut. "
                                  "Before that I lowered the ram on safety blocks.", fail_times=0):
        self.transcript = transcript
        self.fail_times = fail_times
        self.calls = 0

    def transcribe_segments(self, segments, language_code=None):
        self.calls += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise CaptureError("stt_failed", USER_MESSAGES["stt_failed"])
        return SttResult(transcript=self.transcript, language_code="mr-IN", request_ids=["req-1"])


DEFAULT_EXTRACTION = Extraction(
    is_repair_note=True, symptom="Pressure not building up", cause="relief valve loosened", fix="reset relief valve to 210 bar",
    steps=["Lower ram onto safety blocks", "Fit test gauge", "Set relief valve to 210 bar", "Tighten lock nut"],
    parts=[], tools=["test gauge"], safety_note="Lower the ram onto safety blocks first.", downtime_min=None,
    missing=[],
)


class FakeLLM:
    def __init__(self, extraction: Extraction | None = None, check: AICheck | None = None,
                 fail_on: set[str] | None = None, translate_fail: bool = False):
        self.extraction = extraction or DEFAULT_EXTRACTION
        self.check = check or AICheck(issues=[], safety_ok=True, summary="Relief valve reset to restore pressure.")
        self.fail_on = set(fail_on or ())
        self.translate_fail = translate_fail
        self.calls: list[tuple[str, str]] = []   # (schema_name, model)

    def structured(self, *, model, system, user, schema_name, schema, out, max_tokens=1500, reasoning_effort="low"):
        self.calls.append((schema_name, model))
        if schema_name in self.fail_on:
            self.fail_on.discard(schema_name)     # fail once
            raise CaptureError("llm_failed", USER_MESSAGES["llm_failed"])
        if out is Extraction:
            return self.extraction
        if out is AICheck:
            return self.check
        if out is Translated:
            if self.translate_fail:
                raise CaptureError("llm_failed", USER_MESSAGES["llm_failed"])
            import json
            data = json.loads(user)
            to_english = "into English" in system
            tag = "EN:" if to_english else "[mr] "
            conv = lambda v: (tag + v) if isinstance(v, str) else v  # noqa: E731
            return Translated(
                symptom=conv(data.get("symptom")), cause=conv(data.get("cause")), fix=conv(data.get("fix")),
                steps=[conv(x) for x in data.get("steps") or []], safety_note=conv(data.get("safety_note")),
                issues=[conv(x) for x in data.get("issues") or []], summary=conv(data.get("summary")),
            )
        raise AssertionError(f"unexpected schema {schema_name}")


class Spy:
    def __init__(self):
        self.calls = []

    def __call__(self, *a):
        self.calls.append(a)


def make_deps(repo=None, stt=None, llm=None, audio=b"RIFF-fake", **settings_over) -> tuple[CaptureDeps, dict]:
    repo = repo or FakeRepo()
    stt = stt or FakeSTT()
    llm = llm or FakeLLM()
    spies = {"rebuild": Spy(), "delete_audio": Spy(), "excerpts": Spy(), "stt": stt, "llm": llm, "repo": repo}

    def excerpts(tenant_id, q, machine_code, k):
        spies["excerpts"].calls.append((tenant_id, q, machine_code, k))
        return [{"title": "HPX-200 Service Manual · p.2", "text": "Set relief valve to 210 bar with test gauge."}]

    settings = CaptureSettings(_env_file=None, SARVAM_API_KEY="x", GROQ_API_KEY="x", **settings_over)
    deps = CaptureDeps(
        repo=repo, settings=settings, stt_factory=lambda: stt, llm_factory=lambda: llm,
        download_audio=lambda path: audio, delete_audio=spies["delete_audio"], manual_excerpts=excerpts,
        rebuild_chunks=spies["rebuild"],
    )
    return deps, spies
