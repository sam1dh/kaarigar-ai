"""Audio handling: any browser recording (webm/opus, mp4/aac, ogg, wav) -> 16 kHz mono WAV segments.

Uses the ffmpeg binary bundled with `imageio-ffmpeg`, so nobody has to install ffmpeg
(works the same on Windows, macOS, Linux and in Docker).
"""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import USER_MESSAGES, CaptureError

SAMPLE_RATE = 16000
BYTES_PER_SEC = SAMPLE_RATE * 2  # 16-bit mono
WAV_HEADER = 44
MIN_TAIL_SEC = 0.6                # drop a last segment shorter than this

# Accepted upload types -> file extension we store
ALLOWED_TYPES = {
    "audio/webm": "webm",
    "video/webm": "webm",           # some Android Chrome builds label audio-only webm as video
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
}


def ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def extension_for(content_type: str | None) -> str | None:
    if not content_type:
        return None
    base = content_type.split(";")[0].strip().lower()
    return ALLOWED_TYPES.get(base)


@dataclass
class PreparedAudio:
    segments: list[bytes]   # WAV bytes, each <= segment_sec
    seconds: float


def _wav_seconds(data: bytes) -> float:
    return max(0.0, (len(data) - WAV_HEADER) / BYTES_PER_SEC)


def prepare(raw: bytes, *, segment_sec: int = 25, min_sec: float = 2.0, max_sec: float = 180.0) -> PreparedAudio:
    """Decode, resample to 16 kHz mono and split into WAV segments.

    Raises CaptureError(bad_audio | too_short | too_long).
    """
    if not raw:
        raise CaptureError("bad_audio", USER_MESSAGES["bad_audio"], retryable=False)

    with tempfile.TemporaryDirectory(prefix="kaarigar_audio_") as tmp:
        src = Path(tmp) / "input.bin"
        src.write_bytes(raw)
        pattern = str(Path(tmp) / "seg_%03d.wav")
        cmd = [
            ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin",
            "-i", str(src),
            "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le",
            "-f", "segment", "-segment_time", str(segment_sec), "-reset_timestamps", "1",
            pattern,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=120)
        except subprocess.TimeoutExpired as e:
            raise CaptureError("bad_audio", USER_MESSAGES["bad_audio"], retryable=False) from e
        files = sorted(Path(tmp).glob("seg_*.wav"))
        if proc.returncode != 0 or not files:
            raise CaptureError("bad_audio", USER_MESSAGES["bad_audio"], retryable=False)

        segments = [f.read_bytes() for f in files]

    lengths = [_wav_seconds(s) for s in segments]
    total = sum(lengths)
    # Drop a tiny trailing piece (often just the button click)
    if len(segments) > 1 and lengths[-1] < MIN_TAIL_SEC:
        segments, lengths = segments[:-1], lengths[:-1]

    if total < min_sec:
        raise CaptureError("too_short", USER_MESSAGES["too_short"], retryable=False)
    if total > max_sec + 2:  # small tolerance for encoder padding
        raise CaptureError("too_long", USER_MESSAGES["too_long"], retryable=False)
    return PreparedAudio(segments=segments, seconds=round(total, 1))
