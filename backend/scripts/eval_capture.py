"""Score extraction + AI check on backend/eval/capture_eval.yaml (no audio, no DB writes).

Usage:  python -m scripts.eval_capture [--sleep 4] [--only C03]
Uses ~2 Groq calls per case and sleeps between cases to stay under free-tier limits.
Exit code 1 if fewer than 85% of checks pass.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import yaml

from app.capture import prompts
from app.capture.llm import GroqLLM
from app.capture.schemas import AI_CHECK_SCHEMA, EXTRACTION_SCHEMA, AICheck, Extraction
from app.capture.settings import get_capture_settings

MACHINES = {
    "HP-07": {"code": "HP-07", "model": "HPX-200", "type": "hydraulic press"},
    "HP-02": {"code": "HP-02", "model": "HPX-200", "type": "hydraulic press"},
    "CNC-03": {"code": "CNC-03", "model": "CL-40", "type": "cnc lathe"},
    "AC-01": {"code": "AC-01", "model": "AC-75", "type": "air compressor"},
}
GLOSSARY = [{"term": "thak-thak", "meaning": "knocking sound"}, {"term": "dabav", "meaning": "pressure"}]


def has_any(value, words) -> bool:
    text = (value or "").lower() if isinstance(value, str) else " ".join(value or []).lower()
    return any(str(w).lower() in text for w in words)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sleep", type=float, default=4.0)
    ap.add_argument("--only")
    args = ap.parse_args()
    s = get_capture_settings()
    llm = GroqLLM(s.GROQ_API_KEY, timeout=s.GROQ_TIMEOUT_SEC)
    cases = yaml.safe_load((Path(__file__).resolve().parents[1] / "eval" / "capture_eval.yaml").read_text())["cases"]
    total = passed = 0
    for i, c in enumerate(cases):
        if args.only and c["id"] != args.only:
            continue
        m = MACHINES[c["machine"]]
        t0 = time.time()
        ext: Extraction = llm.structured(model=s.GROQ_MODEL_SMALL, system=prompts.EXTRACT_SYSTEM,
                                         user=prompts.extract_user(m, c["transcript"], GLOSSARY),
                                         schema_name="repair_record", schema=EXTRACTION_SCHEMA, out=Extraction)
        chk: AICheck = llm.structured(model=s.GROQ_MODEL_LARGE, system=prompts.CHECK_SYSTEM,
                                      user=prompts.check_user(m, ext.model_dump(), c["transcript"], []),
                                      schema_name="ai_check", schema=AI_CHECK_SCHEMA, out=AICheck)
        ms = int((time.time() - t0) * 1000)
        e = c["expect"]
        results = []
        for key, field in (("symptom_has", "symptom"), ("cause_has", "cause"), ("fix_has", "fix")):
            if key in e:
                results.append((key, has_any(getattr(ext, field), e[key])))
        for field in e.get("null", []):
            results.append((f"{field} is null", getattr(ext, field) in (None, [], "")))
        if e.get("safety") == "present":
            results.append(("safety present", ext.safety_note is not None))
        if e.get("safety") == "absent":
            results.append(("safety absent", ext.safety_note is None))
        if e.get("check_flags_safety"):
            results.append(("check flags safety", chk.safety_ok is False))
        if "is_repair_note" in e:
            results.append(("is_repair_note", ext.is_repair_note == e["is_repair_note"]))
        ok = sum(1 for _, r in results if r)
        total += len(results)
        passed += ok
        fails = [k for k, r in results if not r]
        print(f"{c['id']}  {ok}/{len(results)}  {ms:>5} ms  symptom={ext.symptom!r}  fix={ext.fix!r}"
              + (f"  FAILED: {', '.join(fails)}" if fails else ""))
        if i < len(cases) - 1:
            time.sleep(args.sleep)
    rate = passed / total if total else 0
    print(f"\nchecks passed: {passed}/{total} = {rate:.0%}  (target 85%)")
    return 0 if rate >= 0.85 else 1


if __name__ == "__main__":
    sys.exit(main())
