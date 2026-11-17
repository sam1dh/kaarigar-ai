"""CLI: python -m scripts.eval_search [--k 8] [--rerank] [--plant shree]

Runs every case in backend/eval/search_eval.yaml through search() directly
(no HTTP, no LLM). A case is a HIT at n if ANY of the top-n results matches
ANY item in expect_any. Saves results to backend/eval/results/<ts>.json and
exits 1 below the targets: hit@8 >= 0.85, hit@3 >= 0.65 (rerank off).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import yaml

from app.core.db import db
from app.services import search

TARGETS = {"hit@8": 0.85, "hit@3": 0.65}
EVAL_FILE = os.path.join(os.path.dirname(__file__), "..", "eval", "search_eval.yaml")


def _match(result: dict, expect: dict) -> bool:
    if expect.get("type") == "record":
        return result["meta"].get("seed_key") == expect.get("key")
    if expect.get("type") == "manual":
        if result.get("model") != expect.get("model"):
            return False
        return expect.get("contains", "").lower() in (result.get("text") or "").lower()
    if expect.get("type") == "log":
        if result.get("machine_code") != expect.get("machine"):
            return False
        return expect.get("contains", "").lower() in (result.get("text") or "").lower()
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description="Score search against the Phase 1 eval set.")
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--rerank", action="store_true")
    ap.add_argument("--plant", default="shree")
    args = ap.parse_args()

    with open(EVAL_FILE, encoding="utf-8") as f:
        cases = yaml.safe_load(f)["cases"]

    with db() as conn:
        tenant = conn.execute("select id from tenants where slug = %s", (args.plant,)).fetchone()
    if not tenant:
        raise SystemExit(f"plant '{args.plant}' not found")
    tenant_id = str(tenant[0])

    from app.services import embeddings

    embeddings.wait_ready()

    rows = []
    latencies = []
    for case in cases:
        started = time.perf_counter()
        out = search.search(
            tenant_id,
            case["q"],
            machine_code=case.get("machine") or None,
            k=args.k,
            rerank=args.rerank or None,
        )
        ms = (time.perf_counter() - started) * 1000
        latencies.append(ms)

        results, expect_any = out["results"], case["expect_any"]

        def first_hit_rank(n: int, results=results, expect=expect_any) -> int | None:
            for i, r in enumerate(results[:n], 1):
                if any(_match(r, e) for e in expect):
                    return i
            return None

        rows.append(
            {
                "id": case["id"],
                "q": case["q"],
                "first_hit": first_hit_rank(args.k),
                "hit_at_1": first_hit_rank(1) is not None,
                "hit_at_3": first_hit_rank(3) is not None,
                "hit_at_8": first_hit_rank(args.k) is not None,
                "took_ms": round(ms, 1),
                "top3": [r["title"] for r in out["results"][:3]],
            }
        )
        hit = rows[-1]["first_hit"]
        print(
            f"{case['id']}: {'rank ' + str(hit) if hit else 'MISS'} "
            f"({rows[-1]['took_ms']:.0f} ms)  |  " + " // ".join(rows[-1]["top3"])
        )

    n = len(rows)
    hits3 = sum(r["hit_at_3"] for r in rows)
    hits8 = sum(r["hit_at_8"] for r in rows)
    hits1 = sum(r["hit_at_1"] for r in rows)
    mrr = sum(1 / r["first_hit"] for r in rows if r["first_hit"]) / n
    p50 = statistics.median(latencies)
    p95 = sorted(latencies)[int(0.95 * len(latencies)) - 1 if len(latencies) > 1 else 0]

    print(f"\n=== {args.plant} — {n} cases, rerank={'on' if args.rerank else 'off'} ===")
    print(f"hit@1 {hits1 / n:.2f}  hit@3 {hits3 / n:.2f}  hit@{args.k} {hits8 / n:.2f}  MRR {mrr:.3f}")
    print(f"latency p50 {p50:.0f} ms  p95 {p95:.0f} ms")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = os.path.join(os.path.dirname(__file__), "..", "eval", "results")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, f"{stamp}{'-rerank' if args.rerank else ''}.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "plant": args.plant,
                "rerank": bool(args.rerank),
                "hit@1": hits1 / n,
                "hit@3": hits3 / n,
                f"hit@{args.k}": hits8 / n,
                "mrr": mrr,
                "p50_ms": round(p50, 1),
                "p95_ms": round(p95, 1),
                "cases": rows,
            },
            f,
            indent=2,
        )
    print(f"saved {os.path.relpath(out_file)}")

    if not args.rerank and (hits8 / n < TARGETS[f"hit@{args.k}"] or hits3 / n < TARGETS["hit@3"]):
        print(
            f"FAILED targets: hit@{args.k} {hits8 / n:.2f} < {TARGETS[f'hit@{args.k}']} "
            f"or hit@3 {hits3 / n:.2f} < {TARGETS['hit@3']}"
        )
        sys.exit(1)
    print("PASSED targets" if not args.rerank else "(rerank run — targets not enforced)")


if __name__ == "__main__":
    main()
