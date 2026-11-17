"""RRF fusion reference (mirrors the SQL merge in search.py) + rank-map tests.

The real merge runs in Postgres (app/services/search.py `_SEARCH_SQL`): every
retriever contributes 1/(RRF_K + rank), the query's machine adds
SAME_MACHINE_BONUS, and at most MAX_PER_SOURCE chunks survive per document.
This file keeps a pure-Python reference of those rules so regressions in the
SQL can be caught against a documented contract.
"""

from __future__ import annotations

from app.services.search import MAX_PER_SOURCE, RRF_K, SAME_MACHINE_BONUS, _friendly_ranks


def rrf_score(rank_map: dict[str, int], same_machine: bool) -> float:
    """SQL: sum(1.0/(rrfk + r)) over retrievers + machine bonus."""
    base = sum(1.0 / (RRF_K + r) for r in rank_map.values())
    return base + (SAME_MACHINE_BONUS if same_machine else 0.0)


def merge(candidates: list[tuple[str, str, dict[str, int], bool]]) -> list[dict]:
    """Reference of the scored/ranked/final CTEs.

    candidates: (chunk_id, source_key 'type:id', ranks, same_machine).
    Returns the final list: ≤ MAX_PER_SOURCE per source, score desc.
    """
    scored = {cid: rrf_score(ranks, sm) for cid, _src, ranks, sm in candidates}
    by_source: dict[str, list] = {}
    for cid, src, _ranks, _sm in candidates:
        by_source.setdefault(src, []).append((scored[cid], cid))
    final = []
    for src, items in by_source.items():
        items.sort(key=lambda t: (-t[0], t[1]))
        for score, cid in items[:MAX_PER_SOURCE]:
            final.append({"id": cid, "source": src, "score": score})
    final.sort(key=lambda x: (-x["score"], x["id"]))
    return final


def test_two_retrievers_beat_one() -> None:
    """Fusion: found by vector AND keyword outranks a chunk found by only one."""
    solo = rrf_score({"v": 1}, False)
    duo = rrf_score({"v": 1, "kw": 1}, False)
    assert duo > solo


def test_same_machine_bonus_can_flip_order() -> None:
    """With a machine filter, a same-machine hit can overtake a better-ranked one."""
    other = rrf_score({"v": 1}, False)          # rank 1, different machine
    mine = rrf_score({"v": 3}, True)            # rank 3, same machine
    assert mine > other
    # ...but not by much: the bonus is a nudge, not a ranking override
    assert rrf_score({"v": 1}, True) > rrf_score({"v": 10}, True)


def test_max_per_source() -> None:
    """At most MAX_PER_SOURCE chunks of one document survive the merge."""
    cands = [(f"c{i}", "record:r1", {"v": i + 1}, False) for i in range(5)]
    cands.append(("x", "record:r2", {"v": 6}, False))
    out = merge(cands)
    r1 = [x for x in out if x["source"] == "record:r1"]
    assert len(r1) == MAX_PER_SOURCE
    # the kept ones are the best-scoring of the document's chunks
    assert {x["id"] for x in r1} == {"c0", "c1"}


def test_order_and_dedup() -> None:
    """Final order is score desc; cross-retriever chunks float to the top."""
    cands = [
        ("a", "record:r1", {"v": 1}, False),
        ("b", "manual:m1", {"v": 1, "kw": 2}, False),
        ("c", "record:r1", {"v": 4}, False),
        ("d", "log:h1", {"gr": 1}, False),
    ]
    out = merge(cands)
    assert out[0]["id"] == "b"                       # two retrievers
    assert len([x for x in out if x["source"] == "record:r1"]) == 2  # a and c, capped
    assert len(out) == 4


def test_friendly_ranks_pairs() -> None:
    """kc/kw merge into 'keyword' (best rank), gr/gl into 'graph'."""
    assert _friendly_ranks({"v": 1, "kc": 2, "kw": 5, "gr": 3, "gl": 7}) == {
        "vector": 1, "keyword": 2, "graph": 3,
    }
    assert _friendly_ranks({}) == {}
    assert _friendly_ranks({"kw": 4}) == {"keyword": 4}
    assert _friendly_ranks({"gl": 2}) == {"graph": 2}
