"""Server-Sent Events for /assist/ask.

The pipeline runs in a worker thread (Sarvam/Groq/psycopg are blocking) and puts events on a queue.
An async generator reads the queue and writes SSE frames. If the phone disconnects, the generator is
closed, `cancel` is set, and the pipeline stops at its next check.

Wire format (one event per frame):
    event: stage      data: {"stage": "queued" | "listening" | "understanding" | "searching" | "writing"}
    event: meta       data: {"query_id": "..."}
    event: question   data: {"original", "en", "language"}
    event: sources    data: {"sources": [{ref, label, title, source_type, source_id, page, snippet, ...}]}
    event: delta      data: {"text": "..."}             (answer text, in order)
    event: done       data: {"query_id", "status", "parts", "confidence", "suggest_escalate", "latency_ms"}
    event: error      data: {"query_id", "code", "message"}
    : ping                                             (comment every SSE_PING_SEC while nothing else is sent)
"""
from __future__ import annotations

import json
import queue
import threading
import time
from concurrent.futures import Executor
from typing import AsyncIterator, Callable

import anyio

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",          # nginx/Azure front ends: don't buffer the stream
    "Connection": "keep-alive",
}

_END = object()


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


def run_as_sse(executor: Executor, work: Callable[[Callable[[str, dict], None], Callable[[], bool]], object],
               *, first: list[tuple[str, dict]] | None = None, ping_sec: float = 10.0,
               on_reject: Callable[[], None] | None = None) -> AsyncIterator[str]:
    """`work(emit, cancelled)` runs on `executor`. Returns an async iterator of SSE frames."""
    q: "queue.Queue[object]" = queue.Queue()
    cancel = threading.Event()

    def emit(event: str, data: dict) -> None:
        q.put((event, data))

    def job() -> None:
        try:
            work(emit, cancel.is_set)
        finally:
            q.put(_END)

    async def gen() -> AsyncIterator[str]:
        for ev, data in first or []:
            yield sse(ev, data)
        try:
            executor.submit(job)
        except RuntimeError:            # executor shut down (server stopping)
            if on_reject:
                on_reject()
            yield sse("error", {"code": "server_restarted", "message": "The server is restarting. Ask again."})
            return
        last = time.monotonic()
        try:
            while True:
                try:
                    item = await anyio.to_thread.run_sync(lambda: q.get(timeout=0.5))
                except queue.Empty:
                    if time.monotonic() - last >= ping_sec:
                        last = time.monotonic()
                        yield ": ping\n\n"
                    continue
                if item is _END:
                    return
                ev, data = item  # type: ignore[misc]
                last = time.monotonic()
                yield sse(ev, data)
        finally:
            cancel.set()          # client left or stream finished: stop the worker at its next check

    return gen()
