import pytest

from app.capture import graph as graph_mod
from app.capture.audio import PreparedAudio


@pytest.fixture
def fake_audio(monkeypatch):
    """Skip real decoding in graph tests: every recording becomes two 25 s segments."""
    calls = []

    def _prepare(raw, **kw):
        calls.append(kw)
        return PreparedAudio(segments=[b"seg1", b"seg2"], seconds=42.5)

    monkeypatch.setattr(graph_mod, "prepare", _prepare)
    return calls
