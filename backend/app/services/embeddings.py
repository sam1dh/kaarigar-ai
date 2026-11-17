"""fastembed embeddings, loaded once in a background thread at startup.

The stored chunk text stays plain; only the text sent to the model gets the
manual title/section prefix (see embed_passages callers).
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import numpy as np

from app.core.config import get_settings

logger = logging.getLogger("kaarigar.embeddings")

BATCH = 32

_state: dict[str, Any] = {
    "embed": None,          # TextEmbedding | None
    "embed_status": "loading",  # loading | ready | error
    "embed_error": None,
    "rerank": None,         # TextCrossEncoder | None
    "rerank_status": "off",  # off | loading | ready | error
    "lock": threading.Lock(),
}


def start_loading() -> None:
    """Kick off model loading in a background thread (call at app startup). Safe twice."""
    if _state.get("started"):
        return
    _state["started"] = True
    s = get_settings()
    threading.Thread(target=_load_embed, args=(s.embed_model, s.fastembed_cache_path), daemon=True).start()
    if s.rerank_enabled:
        threading.Thread(target=_load_rerank, args=(s.rerank_model, s.fastembed_cache_path), daemon=True).start()


def _load_embed(model: str, cache_dir: str) -> None:
    try:
        from fastembed import TextEmbedding

        with _state["lock"]:
            _state["embed"] = TextEmbedding(model_name=model, cache_dir=cache_dir)
        _state["embed_status"] = "ready"
        logger.info("embed model ready: %s", model)
    except Exception as e:  # pragma: no cover - depends on network
        _state["embed_status"] = "error"
        _state["embed_error"] = str(e)
        logger.exception("embed model failed to load: %s", e)


def _load_rerank(model: str, cache_dir: str) -> None:
    try:
        try:  # fastembed >= 1.x exports it at top level
            from fastembed import TextCrossEncoder
        except ImportError:  # 0.x keeps it in the rerank subpackage
            from fastembed.rerank.cross_encoder import TextCrossEncoder

        with _state["lock"]:
            _state["rerank"] = TextCrossEncoder(model_name=model, cache_dir=cache_dir)
        _state["rerank_status"] = "ready"
        logger.info("rerank model ready: %s", model)
    except Exception as e:  # pragma: no cover
        _state["rerank_status"] = "error"
        logger.exception("rerank model failed to load: %s", e)


def status() -> dict[str, str]:
    return {"embed": _state["embed_status"], "rerank": _state["rerank_status"]}


def ready() -> bool:
    return _state["embed_status"] == "ready"


def rerank_ready() -> bool:
    return _state["rerank_status"] == "ready"


def wait_ready(timeout: int = 180) -> None:
    """Block until the embed model is loaded (CLI scripts). Starts loading if needed."""
    import time

    if not _state.get("started") and not ready():
        start_loading()
    start = time.time()
    while not ready():
        if _state["embed_status"] == "error":
            raise RuntimeError(f"embed model failed to load: {_state['embed_error']}")
        if time.time() - start > timeout:
            raise RuntimeError(f"embed model did not load in {timeout}s")
        time.sleep(2)


def embed_passages(texts: list[str]) -> list[np.ndarray]:
    """Embed chunk texts (batches of 32)."""
    model: Any = _state["embed"]
    if model is None:
        raise RuntimeError("embed model not ready")
    out: list[np.ndarray] = []
    for start in range(0, len(texts), BATCH):
        batch = [t if t.strip() else " " for t in texts[start : start + BATCH]]
        out.extend(np.asarray(v) for v in model.passage_embed(batch))
    return out


def embed_query(text: str) -> np.ndarray:
    model: Any = _state["embed"]
    if model is None:
        raise RuntimeError("embed model not ready")
    return np.asarray(next(model.query_embed([text if text.strip() else " "])))


def rerank_scores(query: str, texts: list[str]) -> list[float]:
    model: Any = _state["rerank"]
    if model is None:
        raise RuntimeError("rerank model not ready")
    return list(model.rerank(query, texts))
