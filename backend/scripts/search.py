"""CLI: python -m scripts.search "pump thak thak" --machine HP-07 [--rerank] [--debug]"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.db import db
from app.core.errors import ApiError
from app.services import embeddings, search


def main() -> None:
    ap = argparse.ArgumentParser(description="Run a hybrid search from the command line.")
    ap.add_argument("query")
    ap.add_argument("--machine", default=None)
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--rerank", action="store_true")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--plant", default="shree")
    args = ap.parse_args()

    embeddings.wait_ready()

    with db() as conn:
        tenant = conn.execute("select id from tenants where slug = %s", (args.plant,)).fetchone()
    if not tenant:
        raise SystemExit(f"plant '{args.plant}' not found")

    try:
        out = search.search(
            str(tenant[0]),
            args.query,
            machine_code=args.machine,
            k=args.k,
            rerank=args.rerank or None,
            debug=args.debug,
        )
    except ApiError as e:
        raise SystemExit(f"error {e.status_code} {e.code}: {e.message}") from None

    print(
        f"query: {out['query']!r}  expanded: {out['expanded_query']!r}  "
        f"machine: {out['machine']}  took: {out['took_ms']}ms  confidence: {out['confidence']}"
    )
    if args.debug:
        d = out["debug"]
        print(f"  symptoms: {d['symptoms_matched']}  glossary: {d['glossary_used']}")
    print(f"{'#':>2} {'L':1} {'score':>6}  {'ranks':<22} title")
    for i, r in enumerate(out["results"], 1):
        ranks = ",".join(f"{k}:{v}" for k, v in sorted(r["ranks"].items()))
        mark = "*" if r.get("same_machine") else " "
        print(f"{i:>2} {r['label']}{mark} {r['score']:>6.4f}  {ranks:<22} {r['title']}  [{r['text'][:60]}…]")


if __name__ == "__main__":
    main()
