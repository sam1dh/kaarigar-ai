"""Audio decoding/segmenting with the real bundled ffmpeg."""
import subprocess

import pytest

from app.capture.audio import extension_for, ffmpeg_exe, prepare
from app.capture.errors import CaptureError


def make_audio(seconds: float, fmt: str = "webm", silent: bool = False) -> bytes:
    src = "anullsrc=r=48000:cl=stereo" if silent else "sine=frequency=440:sample_rate=48000"
    codec = {"webm": ["-c:a", "libopus"], "wav": ["-c:a", "pcm_s16le"], "m4a": ["-c:a", "aac", "-movflags", "frag_keyframe+empty_moov"],
             "ogg": ["-c:a", "libopus"]}[fmt]
    # m4a is written fragmented, like Safari/iOS MediaRecorder output
    muxer = {"webm": "webm", "wav": "wav", "m4a": "mp4", "ogg": "ogg"}[fmt]
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-t", str(seconds), "-i", src,
           *codec, "-f", muxer, "pipe:1"]
    return subprocess.run(cmd, capture_output=True, check=True).stdout


@pytest.mark.parametrize("fmt", ["webm", "wav", "m4a", "ogg"])
def test_browser_formats_decode(fmt):
    out = prepare(make_audio(5, fmt))
    assert len(out.segments) == 1
    assert 4.5 <= out.seconds <= 5.5
    assert out.segments[0][:4] == b"RIFF"


def test_long_recording_is_split_into_25s_segments():
    out = prepare(make_audio(60), segment_sec=25)
    assert len(out.segments) == 3
    assert 59 <= out.seconds <= 61


def test_too_short():
    with pytest.raises(CaptureError) as e:
        prepare(make_audio(1), min_sec=2)
    assert e.value.code == "too_short" and e.value.retryable is False


def test_too_long():
    with pytest.raises(CaptureError) as e:
        prepare(make_audio(20), max_sec=10)
    assert e.value.code == "too_long"


def test_garbage_bytes():
    with pytest.raises(CaptureError) as e:
        prepare(b"this is not audio at all" * 100)
    assert e.value.code == "bad_audio"


def test_empty():
    with pytest.raises(CaptureError) as e:
        prepare(b"")
    assert e.value.code == "bad_audio"


def test_content_types():
    assert extension_for("audio/webm;codecs=opus") == "webm"
    assert extension_for("video/webm") == "webm"
    assert extension_for("audio/mp4") == "m4a"
    assert extension_for("application/pdf") is None
    assert extension_for(None) is None
