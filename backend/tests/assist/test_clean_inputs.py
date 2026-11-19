"""Clean inputs before Groq: server-side audio clean-up (real ffmpeg), pre_clean, the understand step,
off-topic questions, and one live answer per person (interruptions)."""
import io
import math
import threading
import time
import uuid
import wave

import pytest

from app.assist.audio_clean import clean_audio
from app.assist.errors import AssistError
from app.assist.pipeline import AskRequest, AssistPipeline
from app.assist.understand import Understanding, needs_ai, pre_clean, understand

from .fakes import HP07, TECH, TENANT, FakeCleaner, FakeSearch, FakeStructured, FakeWriter, make_deps, make_service

CODES = ["AC-01", "CNC-03", "HP-02", "HP-07"]


# ============================================================================ audio clean-up (real ffmpeg)

def _wav(parts: list[tuple[float, bool]], rate: int = 16000, noise: float = 0.002) -> bytes:
    """parts = [(seconds, voiced?)]. Voiced = harmonic tone with a 4 Hz 'syllable' rhythm; else faint noise."""
    import random

    rnd = random.Random(7)
    frames = bytearray()
    t = 0.0
    for secs, voiced in parts:
        for _ in range(int(secs * rate)):
            v = noise * (rnd.random() * 2 - 1)
            if voiced:
                env = 0.5 + 0.5 * math.sin(2 * math.pi * 4 * t)
                v += env * (0.35 * math.sin(2 * math.pi * 180 * t) + 0.2 * math.sin(2 * math.pi * 360 * t))
            frames += int(max(-1, min(1, v)) * 32767).to_bytes(2, "little", signed=True)
            t += 1 / rate
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return buf.getvalue()


def test_clean_audio_trims_silence_and_returns_16k_wav():
    raw = _wav([(1.5, False), (2.0, True), (2.5, False), (1.0, True), (1.5, False)])     # 8.5 s recorded
    out = clean_audio(raw)
    assert out.cleaned and out.data[:4] == b"RIFF"
    assert 2.0 <= out.speech_seconds <= 5.0                  # ~3 s of voice + short kept pauses
    with wave.open(io.BytesIO(out.data)) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1


def test_clean_audio_refuses_background_noise_only():
    with pytest.raises(AssistError) as e:
        clean_audio(_wav([(3.0, False)]))
    assert e.value.code == "no_speech"


def test_clean_audio_keeps_original_when_it_cannot_decode():
    out = clean_audio(b"not audio at all" * 50)
    assert out.cleaned is False and out.data.startswith(b"not audio")


# ============================================================================ pre_clean (no AI)

@pytest.mark.parametrize("raw,clean", [
    ("umm HP-07 ka pressure uh nahi ban raha", "HP-07 ka pressure nahi ban raha"),
    ("pump pump se thak thak awaaz", "pump se thak awaaz"),
    ("e 5 alarm aa raha hai", "E-05 alarm aa raha hai"),
    ("E05 dikh raha", "E-05 dikh raha"),
    ("ई 05 आ रहा है", "E-05 आ रहा है"),
    ("hp7 ka ram dheere chal raha", "HP-07 ka ram dheere chal raha"),
    ("HP 07 and hp-7 and Hp07", "HP-07 and HP-07 and HP-07"),
    ("cnc 3 chuck loose", "CNC-03 chuck loose"),
    ("ac1 compressor garam", "AC-01 compressor garam"),
    ("pressure २१० bar tak nahi", "pressure 210 bar tak nahi"),
    ("matlab achha the 5 bar valve", "the 5 bar valve"),
    ("hp 70 is not ours", "hp 70 is not ours"),
])
def test_pre_clean(raw, clean):
    assert pre_clean(raw, CODES) == clean


def test_pre_clean_never_returns_empty():
    assert pre_clean("umm uh", CODES) == "umm uh"


def test_needs_ai():
    assert needs_ai("pressure low", "en-IN", voice=True)                       # spoken: always
    assert not needs_ai("HP-07 pressure is not building", "en-IN", voice=False)
    assert needs_ai("pressure nahi ban raha", "hi-IN", voice=False)            # not English profile
    assert needs_ai("प्रेशर नहीं", "en-IN", voice=False)                        # Indian script
    assert needs_ai(" ".join(["word"] * 15), "en-IN", voice=False)             # long, likely messy


def test_understand_call_and_failure():
    s = FakeStructured(understanding=Understanding(question_en=" HP-07  oil leak ", error_codes=["e-05", " "],
                                                   already_tried="  changed the seal  "))
    u = understand(s, "m", "text", HP07)
    assert u.question_en == "HP-07 oil leak" and u.error_codes == ["E-05"] and u.already_tried == "changed the seal"
    assert "Machine: HP-07" in s.users[0]
    assert understand(FakeStructured(fail_question=True), "m", "text", HP07) is None


# ============================================================================ pipeline with clean inputs

class Ev(list):
    def __call__(self, e, d):
        self.append((e, d))

    def of(self, name):
        return [d for e, d in self if e == name]


def run(text=None, audio=None, language="hi-IN", **kw):
    deps, spies = make_deps(**kw)
    qid = str(uuid.uuid4())
    deps.repo.create_query(query_id=qid, tenant_id=TENANT, user_id=TECH, machine_id=HP07["id"], language=language,
                           input_mode="voice" if audio else "text", audio_path=None, question_original=text)
    ev = Ev()
    status = AssistPipeline(deps).run(AskRequest(query_id=qid, tenant_id=TENANT, user_id=TECH, language=language,
                                                 machine=HP07, text=text, audio=audio), ev)
    return status, ev, spies, deps.repo.queries[qid]


def test_voice_goes_through_the_cleaner_before_sarvam():
    status, _, spies, row = run(audio=b"WEBM" * 300)
    assert status == "answered"
    assert spies["cleaner"].calls[0]["max_sec"] == 60
    raw, kw = spies["prepared"][0]
    assert raw.startswith(b"CLEANWAV") and kw["min_sec"] == 0.4
    assert spies["structured"].calls == ["understanding"]


def test_silent_recording_is_refused_without_calling_sarvam():
    status, ev, spies, row = run(audio=b"SILENT" * 300)
    assert status == "failed" and ev.of("error")[0]["code"] == "no_speech"
    assert spies["stt"].calls == 0 and row["error"] == "no_speech"


def test_cleaning_can_be_switched_off():
    status, _, spies, _ = run(audio=b"WEBM" * 300, AUDIO_CLEAN=False)
    assert status == "answered" and spies["cleaner"].calls == []
    assert spies["prepared"][0][1]["min_sec"] == 1.0


def test_cleaner_fallback_uses_original_audio():
    status, _, spies, _ = run(audio=b"WEBM" * 300, cleaner=FakeCleaner(fail=True))
    assert status == "answered" and spies["prepared"][0][0].startswith(b"WEBM")


def test_llm_gets_the_pre_cleaned_text_and_already_tried_reaches_the_writer():
    u = Understanding(question_en="HP-07 pressure is not building", already_tried="relief valve already set to 210 bar")
    status, ev, spies, row = run(text="umm hp7 ka pressure pressure nahi ban raha, relief valve already 210 pe hai",
                                 structured=FakeStructured(understanding=u))
    assert status == "answered"
    sent = spies["structured"].users[0]
    assert "umm" not in sent and "HP-07 ka pressure nahi" in sent
    assert ev.of("question")[0]["already_tried"] == "relief valve already set to 210 bar"
    assert "Already tried by the technician: relief valve already set to 210 bar" in spies["writer"].stream_calls[0]["user"]
    assert row["answer_parts"]["understanding"]["already_tried"] == "relief valve already set to 210 bar"
    assert ev.of("done")[0]["understanding"]["question_en"] == "HP-07 pressure is not building"


def test_error_codes_are_never_lost():
    u = Understanding(question_en="the press shows an overheating alarm", error_codes=["E-05"])
    _, _, spies, row = run(text="E05 aa raha hai", structured=FakeStructured(understanding=u))
    assert spies["search"].calls[0][1] == "the press shows an overheating alarm (E-05)"


def test_off_topic_question_skips_search_and_writer():
    u = Understanding(question_en="what is today's canteen menu", is_repair_question=False)
    status, ev, spies, row = run(text="aaj canteen mein kya hai", structured=FakeStructured(understanding=u))
    assert status == "no_answer"
    assert spies["search"].calls == [] and spies["writer"].stream_calls == []
    assert ev.of("done")[0]["off_topic"] is True and ev.of("sources")[0]["sources"] == []


def test_short_plain_english_skips_the_ai_clean_up():
    status, _, spies, _ = run(text="HP-07 pressure not building", language="en-IN",
                              writer=FakeWriter(answer="1. Set relief valve to 210 bar. [E1]"))
    assert status == "answered" and spies["structured"].calls == []


# ============================================================================ interruptions

def test_begin_run_supersedes_the_previous_answer():
    svc, _ = make_service()
    try:
        a = svc.begin_run(TECH)
        b = svc.begin_run(TECH)
        assert a.is_set() and not b.is_set()
        svc.end_run(TECH, a)                 # the old run finishing must not drop the new one
        c = svc.begin_run(TECH)
        assert b.is_set() and not c.is_set()
        other = svc.begin_run("someone-else")
        assert not other.is_set() and not c.is_set()
    finally:
        svc.shutdown()


def test_new_question_cancels_the_one_still_streaming():
    from .test_api import build, parse_sse

    def slow(n):
        time.sleep(0.05)

    e = build(writer=FakeWriter(chunk=4, on_chunk=slow))
    try:
        first: dict = {}

        def ask_first():
            with e.client.stream("POST", "/assist/ask", data={"text": "pressure low", "machine_code": "HP-07"}) as r:
                first["events"] = parse_sse("".join(r.iter_text()))

        e.as_("tech")
        t = threading.Thread(target=ask_first)
        t.start()
        deadline = time.time() + 5
        while time.time() < deadline and not any(q["status"] == "answering" and q.get("question_en")
                                                 for q in e.repo.queries.values()):
            time.sleep(0.02)
        time.sleep(0.15)                                       # first answer is mid-stream now
        with e.client.stream("POST", "/assist/ask", data={"text": "oil leak", "machine_code": "HP-07"}) as r:
            second = parse_sse("".join(r.iter_text()))
        t.join(10)
        names_first = [ev for ev, _ in first["events"]]
        assert "delta" in names_first and "done" not in names_first
        first_id = first["events"][0][1]["query_id"]
        assert e.repo.queries[first_id]["status"] == "cancelled"
        assert [ev for ev, _ in second][-1] == "done"
    finally:
        e.svc.shutdown()


def test_escalation_note_defaults_to_what_was_already_tried():
    from .test_api import build

    u = Understanding(question_en="HP-07 pressure is not building", already_tried="changed the return filter")
    e = build(structured=FakeStructured(understanding=u))
    try:
        with e.as_("tech").stream("POST", "/assist/ask", data={"text": "pressure nahi, filter badal diya",
                                                                "machine_code": "HP-07"}) as r:
            body = "".join(r.iter_text())
        qid = next(q for q in e.repo.queries)
        assert "event: done" in body
        res = e.as_("tech").post(f"/assist/queries/{qid}/escalate", json={})
        assert e.repo.escalations[res.json()["escalation_id"]]["note"] == "changed the return filter"
    finally:
        e.svc.shutdown()
