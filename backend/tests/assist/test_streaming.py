"""run_as_sse: frame format, keep-alive pings, and stopping the worker when the client leaves."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import anyio

from app.assist.streaming import run_as_sse, sse


def test_frame_format_keeps_unicode():
    f = sse("delta", {"text": "रिलीफ वाल्व [E1]"})
    assert f.startswith("event: delta\ndata: ") and f.endswith("\n\n")
    assert json.loads(f.split("data: ", 1)[1]) == {"text": "रिलीफ वाल्व [E1]"}


async def _collect(gen, limit=None):
    out = []
    async for frame in gen:
        out.append(frame)
        if limit and len(out) >= limit:
            break
    return out


def test_first_events_then_worker_events_then_end():
    ex = ThreadPoolExecutor(1)

    def work(emit, cancelled):
        emit("stage", {"stage": "searching"})
        emit("done", {"ok": True})

    frames = anyio.run(_collect, run_as_sse(ex, work, first=[("meta", {"query_id": "q"})]))
    assert [f.split("\n")[0] for f in frames] == ["event: meta", "event: stage", "event: done"]
    ex.shutdown()


def test_pings_while_the_worker_is_quiet():
    ex = ThreadPoolExecutor(1)

    def work(emit, cancelled):
        time.sleep(1.3)
        emit("done", {})

    frames = anyio.run(_collect, run_as_sse(ex, work, ping_sec=0.4))
    assert frames.count(": ping\n\n") >= 1 and frames[-1].startswith("event: done")
    ex.shutdown()


def test_client_leaving_cancels_the_worker():
    ex = ThreadPoolExecutor(1)
    seen = threading.Event()

    def work(emit, cancelled):
        emit("delta", {"text": "a"})
        for _ in range(100):
            if cancelled():
                seen.set()
                return
            time.sleep(0.02)

    async def main():
        gen = run_as_sse(ex, work)
        async for _ in gen:
            break                       # client reads one frame and goes away
        await gen.aclose()

    anyio.run(main)
    assert seen.wait(3)
    ex.shutdown()


def test_executor_shut_down_reports_restart():
    ex = ThreadPoolExecutor(1)
    ex.shutdown()
    rejected = []
    frames = anyio.run(_collect, run_as_sse(ex, lambda e, c: None, on_reject=lambda: rejected.append(1)))
    assert rejected == [1] and "server_restarted" in frames[-1]
