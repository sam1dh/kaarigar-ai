"""Server-side clean-up of a spoken question before speech-to-text (shop floors are loud).

One ffmpeg pass (the binary bundled with imageio-ffmpeg, same as Phase 2):
  highpass 100 Hz + lowpass 7.5 kHz   cut motor hum and hiss outside the voice band
  afftdn                              FFT noise reduction (steady compressor/pump noise)
  silenceremove                       energy-based VAD on the server: trims silence at the start and end and
                                      shortens long pauses in the middle (keeps 0.25 s so words don't run together)
  dynaudnorm                          evens out loud and quiet parts (phone far from the mouth)
Output: 16 kHz mono WAV + how many seconds of speech are left.

Why: Sarvam hears less noise (better transcript), gets shorter audio (faster, cheaper), and a recording with no
speech at all is refused here without spending a Sarvam call. If the filters fail on some machine, the original
audio is used unchanged (cleaning is an improvement, never a blocker).
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

from app.capture.audio import ffmpeg_exe

from .errors import AssistError

log = logging.getLogger("kaarigar.assist.audio_clean")

FILTERS = (
    "highpass=f=100,lowpass=f=7500,afftdn=nf=-25,"
    "silenceremove=start_periods=1:start_duration=0.1:start_threshold=-42dB:"
    "stop_periods=-1:stop_duration=0.6:stop_threshold=-42dB:stop_silence=0.25,"
    "dynaudnorm=f=150:g=15"
)


@dataclass
class CleanAudio:
    data: bytes                 # WAV if cleaned, else the original bytes
    speech_seconds: float | None
    cleaned: bool


def _wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate() or 16000)


def clean_audio(raw: bytes, *, max_sec: float = 60.0, min_speech_sec: float = 0.4) -> CleanAudio:
    """Raises AssistError("no_speech") if nothing louder than background noise is left after trimming."""
    if not raw:
        raise AssistError("bad_audio")
    with tempfile.TemporaryDirectory(prefix="kaarigar_q_") as tmp:
        src = Path(tmp) / "in.bin"
        dst = Path(tmp) / "clean.wav"
        src.write_bytes(raw)
        cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(src),
               "-t", str(int(max_sec) + 5), "-vn", "-af", FILTERS, "-ac", "1", "-ar", "16000",
               "-c:a", "pcm_s16le", "-map_metadata", "-1", "-fflags", "+bitexact", str(dst)]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=60)
        except subprocess.TimeoutExpired:
            log.info("audio clean timed out; using original")
            return CleanAudio(raw, None, False)
        if proc.returncode != 0 or not dst.exists():
            # Undecodable input is reported by Phase 2's prepare() (bad_audio); a missing filter just skips cleaning.
            log.info("audio clean skipped (ffmpeg rc=%s)", proc.returncode)
            return CleanAudio(raw, None, False)
        try:
            seconds = _wav_seconds(dst)
        except (wave.Error, EOFError):
            return CleanAudio(raw, None, False)
        if seconds < min_speech_sec:
            raise AssistError("no_speech")
        return CleanAudio(dst.read_bytes(), round(seconds, 2), True)
