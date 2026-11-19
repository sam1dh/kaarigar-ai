"""Assist quality check: real Phase 1 search + real Groq, no Sarvam, nothing written to the database.

    python -m scripts.eval_assist                    # all cases in eval/assist_eval.yaml
    python -m scripts.eval_assist --only A01,U02     # some cases
    python -m scripts.eval_assist --sleep 10         # slower, for Groq's free tier (default 8 s between cases)
    python -m scripts.eval_assist --model openai/gpt-oss-20b   # try the small model as the writer

Prints one line per case, then: answered, cited correctly, mentions, abstained, language, p50/p95 timings.
Saves eval/results/assist-<timestamp>.json. Exit code 1 if below the targets in the yaml header.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {"answered": 0.85, "cited": 0.80, "abstained": 0.80, "first_word_p50_ms": 3000}
SCRIPT_RANGES = {"hi-IN": ("ऀ", "ॿ"), "mr-IN": ("ऀ", "ॿ"), "ta-IN": ("஀", "௿"),
                 "te-IN": ("ఀ", "౿"), "kn-IN": ("ಀ", "೿"), "ml-IN": ("ഀ", "ൿ"),
                 "bn-IN": ("ঀ", "৿"), "gu-IN": ("઀", "૿"), "pa-IN": ("਀", "੿"),
                 "od-IN": ("଀", "୿")}


class MemoryRepo:
    """Stands in for the queries table so the eval never writes to Supabase."""

    def __init__(self):
        self.rows: dict[str, dict] = {}

    def update_query(self, tenant_id, query_id, **cols):
        self.rows.setdefault(query_id, {}).update(cols)


def matches(expect: dict, src: dict, text: str) -> bool:
    kind = expect["type"]
    if kind == "record":
        return src["source_type"] == "record" and src.get("seed_key") == expect["key"]
    if kind == "manual":
        return (src["source_type"] == "manual" and expect["model"].lower() in (src.get("title") or "").lower()
                and expect["contains"].lower() in text.lower())
    if kind == "log":
        return src["source_type"] == "log" and expect["machine"].lower() in (src.get("title") or "").lower() \
            and expect["contains"].lower() in text.lower()
    return False


def in_script(text: str, language: str) -> bool:
    rng = SCRIPT_RANGES.get(language)
    if not rng:
        return True
    return sum(1 for ch in text if rng[0] <= ch <= rng[1]) >= 10


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    k = max(0, min(len(values) - 1, round(p * (len(values) - 1))))
    return values[k]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(ROOT / "eval" / "assist_eval.yaml"))
    ap.add_argument("--only", default="")
    ap.add_argument("--sleep", type=float, default=8.0)
    ap.add_argument("--model", default=None, help="override GROQ_MODEL_ANSWER")
    args = ap.parse_args()

    from app.assist import adapters
    from app.assist.pipeline import AskRequest, AssistDeps, AssistPipeline
    from app.assist.settings import get_assist_settings
    from app.capture.audio import prepare
    from app.capture.llm import GroqLLM
    from app.assist.llm import GroqWriter
    from app.services import embeddings

    # This script runs outside the API process, so nothing has loaded Phase 1's
    # embedding model yet; without it every search returns embed_not_ready.
    embeddings.start_loading()
    embeddings.wait_ready(180)

    data = yaml.safe_load(Path(args.file).read_text())
    cases = data["cases"]
    if args.only:
        wanted = {x.strip() for x in args.only.split(",")}
        cases = [c for c in cases if c["id"] in wanted]

    s = get_assist_settings()
    if args.model:
        s = s.model_copy(update={"GROQ_MODEL_ANSWER": args.model})

    with adapters.db_conn() as conn:
        row = conn.execute("select id from tenants where slug = %s", (data.get("plant", "shree"),)).fetchone()
    if not row:
        print("plant not found: run the Phase 0/1 seed first")
        return 2
    tenant_id = str(row["id"] if isinstance(row, dict) else row[0])

    seen_results: dict[tuple, dict] = {}

    def search(tenant, q, machine_code, k):
        res = adapters.hybrid_search(tenant, q, machine_code, k)
        for r in res["results"]:
            seen_results[(r["source_type"], r["source_id"], r.get("chunk_id"))] = r
        return res

    from app.assist.repo import PostgresAssistRepo

    repo = MemoryRepo()
    codes = PostgresAssistRepo(adapters.db_conn).machine_codes(tenant_id)
    deps = AssistDeps(repo=repo, settings=s, search=search, stt_factory=lambda: None,
                      writer_factory=lambda: GroqWriter(s.GROQ_API_KEY, timeout=s.GROQ_TIMEOUT_SEC),
                      structured_factory=lambda: GroqLLM(s.GROQ_API_KEY, timeout=s.GROQ_TIMEOUT_SEC),
                      prepare_audio=prepare, machine_codes=lambda t: codes)
    pipe = AssistPipeline(deps)

    results = []
    for i, c in enumerate(cases):
        if i:
            time.sleep(args.sleep)
        machine = None
        if c.get("machine"):
            from app.assist.repo import PostgresAssistRepo

            machine = PostgresAssistRepo(adapters.db_conn).machine_by_code(tenant_id, c["machine"])
        qid = str(uuid.uuid4())
        events: list[tuple[str, dict]] = []
        t0 = time.monotonic()
        status = pipe.run(AskRequest(query_id=qid, tenant_id=tenant_id, user_id="eval", language=c["language"],
                                     machine=machine, text=c["q"]), lambda e, d: events.append((e, d)))
        total_ms = int((time.monotonic() - t0) * 1000)
        row = repo.rows.get(qid, {})
        sources = row.get("sources") or []
        used = set((row.get("answer_parts") or {}).get("refs_used") or [])
        cited = [s_ for s_ in sources if s_["ref"] in used]
        text = (row.get("answer_local") or "") + "\n" + (row.get("answer") or "")

        r = {"id": c["id"], "q": c["q"], "status": status, "answerable": c["answerable"], "total_ms": total_ms,
             "first_ms": row.get("first_token_ms"), "model": row.get("model"), "answer": row.get("answer_local"),
             "cited": [f"{s_['ref']} {s_.get('seed_key') or s_['title']}" for s_ in cited]}
        if c["answerable"]:
            r["answered"] = status == "answered"
            r["cited_ok"] = r["answered"] and any(
                matches(e, s_, (seen_results.get((s_["source_type"], s_["source_id"], s_.get("chunk_id"))) or {}).get("text", ""))
                for e in c.get("expect_any", []) for s_ in cited)
            r["mention_ok"] = all(m.lower() in text.lower() for m in c.get("must_mention", []))
            r["language_ok"] = (not r["answered"]) or in_script(row.get("answer_local") or "", c["language"])
            flag = "ok " if (r["answered"] and r["cited_ok"] and r["mention_ok"] and r["language_ok"]) else "BAD"
        else:
            r["abstained"] = status == "no_answer"
            flag = "ok " if r["abstained"] else "BAD"
        results.append(r)
        print(f"{flag} {c['id']:4} {status:9} first={r['first_ms']}ms total={total_ms}ms cited={r['cited']} | {c['q'][:50]}")

    ans = [r for r in results if r["answerable"]]
    una = [r for r in results if not r["answerable"]]
    firsts = [r["first_ms"] for r in results if r["first_ms"]]
    summary = {
        "answered": round(sum(r["answered"] for r in ans) / len(ans), 3) if ans else None,
        "cited": round(sum(r["cited_ok"] for r in ans) / len(ans), 3) if ans else None,
        "mentions": round(sum(r["mention_ok"] for r in ans) / len(ans), 3) if ans else None,
        "language": round(sum(r["language_ok"] for r in ans) / len(ans), 3) if ans else None,
        "abstained": round(sum(r["abstained"] for r in una) / len(una), 3) if una else None,
        "first_word_p50_ms": pct(firsts, 0.5), "first_word_p95_ms": pct(firsts, 0.95),
        "total_p50_ms": pct([r["total_ms"] for r in results], 0.5),
        "total_p95_ms": pct([r["total_ms"] for r in results], 0.95),
        "writer_model": s.GROQ_MODEL_ANSWER, "cases": len(results),
    }
    print("\n" + json.dumps(summary, indent=2))
    out = ROOT / "eval" / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"assist-{datetime.now():%Y%m%d-%H%M%S}.json").write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2, default=str))

    fails = []
    for k in ("answered", "cited", "abstained"):
        if summary[k] is not None and summary[k] < TARGETS[k]:
            fails.append(f"{k} {summary[k]} < {TARGETS[k]}")
    if summary["first_word_p50_ms"] and summary["first_word_p50_ms"] > TARGETS["first_word_p50_ms"]:
        fails.append(f"first word p50 {summary['first_word_p50_ms']} ms > {TARGETS['first_word_p50_ms']} ms")
    if fails:
        print("BELOW TARGET: " + "; ".join(fails))
        return 1
    print("All targets met.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
