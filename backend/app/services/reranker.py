"""Optional cross-encoder reranker behind RERANK_ENABLED (default off)."""

from __future__ import annotations

from app.core.config import get_settings
from app.services import embeddings


def enabled(request_flag: bool | None = None) -> bool:
    s = get_settings()
    if request_flag is not None:
        return request_flag
    return s.rerank_enabled


def rerank(query: str, candidates: list[dict]) -> list[dict]:
    """Score (q, section + text) pairs, order by score, set confidence = sigmoid(top score).

    Mutates and re-orders the candidates list in place; also returns it.
    """
    if not candidates:
        return candidates
    texts = [f"{c.get('section') or ''} {c.get('text') or ''}".strip() for c in candidates]
    scores = embeddings.rerank_scores(query, texts)
    for c, sc in zip(candidates, scores, strict=True):
        c["rerank_score"] = round(float(sc), 4)
    candidates.sort(key=lambda c: c["rerank_score"], reverse=True)
    if candidates:
        top = candidates[0]["rerank_score"]
        # sigmoid, numerically safe
        import math

        candidates[0]["confidence"] = round(1 / (1 + math.exp(-top)), 4)
    return candidates
