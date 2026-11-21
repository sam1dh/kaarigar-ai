"""The Assist pipeline end to end with fakes: events, saved rows, failures, cancel."""
import uuid

import pytest

from app.assist.pipeline import AskRequest, AssistPipeline

from .fakes import (HP07, TECH, TENANT, FakeSearch, FakeStructured, FakeSTT, FakeWriter, make_deps)


class Events:
    def __init__(self):
        self.items = []

    def __call__(self, ev, data):
        self.items.append((ev, data))

    def names(self):
        return [e for e, _ in self.items]

    def of(self, name):
        return [d for e, d in self.items if e == name]

    def text(self):
        return "".join(d["text"] for d in self.of("delta"))


def setup(text=None, audio=None, language="hi-IN", machine=HP07, **kw):
    deps, spies = make_deps(**kw)
    qid = str(uuid.uuid4())
    deps.repo.create_query(query_id=qid, tenant_id=TENANT, user_id=TECH, machine_id=machine["id"] if machine else None,
                           language=language, input_mode="text" if text else "voice", audio_path=None,
                           question_original=text)
    req = AskRequest(query_id=qid, tenant_id=TENANT, user_id=TECH, language=language, machine=machine,
                     text=text, audio=audio)
    return AssistPipeline(deps), req, spies


def test_typed_hindi_question_full_flow():
    p, req, spies = setup(text="HP-07 में प्रेशर नहीं बन रहा")
    ev = Events()
    assert p.run(req, ev) == "answered"
    assert ev.names()[0] == "stage" and ev.of("stage")[0]["stage"] == "understanding"
    q = ev.of("question")[0]
    assert q["en"] == "pressure is not building on HP-07" and q["original"].startswith("HP-07")
    assert spies["search"].calls[0][1:3] == ("pressure is not building on HP-07", "HP-07")
    assert [s["ref"] for s in ev.of("sources")[0]["sources"]] == ["E1", "M1", "H1"]
    assert "_text" not in ev.of("sources")[0]["sources"][0]
    assert ev.text().startswith("SAFETY:")
    done = ev.of("done")[0]
    assert done["status"] == "answered" and done["confidence"] == 0.95 and done["suggest_escalate"] is False
    assert done["parts"]["refs_used"] == ["E1", "M1"]
    row = spies["repo"].queries[req.query_id]
    assert row["status"] == "answered" and row["question_en"] == q["en"]
    assert [c["ref"] for c in row["citations"]] == ["E1", "M1"]
    assert row["citations"][0]["seed_key"] == "R01"
    assert row["model"] == "openai/gpt-oss-120b" and row["first_token_ms"] is not None
    assert row["answer"].startswith("EN| ")              # English copy for managers, made after `done`
    # the writer was told the language, the machine and the sources
    call = spies["writer"].stream_calls[0]
    assert "Hindi" in call["system"] and "[E1]" in call["user"] and "HP-07 (HPX-200 hydraulic press)" in call["user"]
    assert call["models"] == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]


def test_plain_english_question_skips_translation():
    p, req, spies = setup(text="pressure not building", language="en-IN",
                          writer=FakeWriter(answer="1. Set relief valve to 210 bar. [E1][M1]"))
    ev = Events()
    assert p.run(req, ev) == "answered"
    assert spies["structured"].calls == []
    assert "understanding" not in [d["stage"] for d in ev.of("stage")]
    row = spies["repo"].queries[req.query_id]
    assert row["answer"] == row["answer_local"]          # English user: no second LLM call
    assert spies["writer"].text_calls == []


def test_voice_question_is_transcribed_in_own_words():
    p, req, spies = setup(audio=b"WEBMDATA" * 100)
    ev = Events()
    assert p.run(req, ev) == "answered"
    assert ev.of("stage")[0]["stage"] == "listening"
    assert spies["stt"].calls == 1
    row = spies["repo"].queries[req.query_id]
    assert row["question_original"] == "HP-07 में pressure नहीं बन रहा है"
    assert row["audio_seconds"] == 4.2


def test_voice_too_short_fails_cleanly():
    p, req, spies = setup(audio=b"SHORT")
    ev = Events()
    assert p.run(req, ev) == "failed"
    assert ev.of("error")[0]["code"] == "too_short"
    assert spies["repo"].queries[req.query_id]["error"] == "too_short"


def test_voice_no_speech():
    p, req, _ = setup(audio=b"WEBM", stt=FakeSTT(transcript="hmm"))
    ev = Events()
    assert p.run(req, ev) == "failed" and ev.of("error")[0]["code"] == "no_speech"


def test_stt_failure():
    p, req, _ = setup(audio=b"WEBM", stt=FakeSTT(fail=True))
    ev = Events()
    assert p.run(req, ev) == "failed" and ev.of("error")[0]["code"] == "stt_failed"


def test_no_sources_means_no_answer_without_calling_the_writer():
    p, req, spies = setup(text="how to fix the forklift", language="en-IN", search=FakeSearch(results=[]))
    ev = Events()
    assert p.run(req, ev) == "no_answer"
    assert spies["writer"].stream_calls == []
    done = ev.of("done")[0]
    assert done["status"] == "no_answer" and done["suggest_escalate"] is True
    assert ev.of("delta") == []


def test_writer_says_no_answer_nothing_is_shown():
    p, req, spies = setup(text="canteen menu?", language="en-IN", writer=FakeWriter(answer="NO_ANSWER", chunk=2))
    ev = Events()
    assert p.run(req, ev) == "no_answer"
    assert ev.of("delta") == []
    assert spies["repo"].queries[req.query_id]["answer_local"] == "NO_ANSWER"


def test_answer_without_valid_refs_is_saved_as_no_answer():
    p, req, spies = setup(text="pressure low", language="en-IN",
                          writer=FakeWriter(answer="1. Replace the pump. [E7]\n2. Call the OEM."))
    ev = Events()
    assert p.run(req, ev) == "no_answer"
    assert ev.of("done")[0]["status"] == "no_answer"
    assert spies["repo"].queries[req.query_id]["status"] == "no_answer"


def test_low_confidence_suggests_escalation():
    p, req, _ = setup(text="pressure low", language="en-IN",
                      writer=FakeWriter(answer="1. Check the valve. [H1]\n2. Check oil.\n3. Check filter."))
    ev = Events()
    assert p.run(req, ev) == "answered"
    done = ev.of("done")[0]
    assert done["confidence"] < 0.5 and done["suggest_escalate"] is True


def test_search_failure():
    p, req, _ = setup(text="pressure low", language="en-IN", search=FakeSearch(fail=True))
    ev = Events()
    assert p.run(req, ev) == "failed" and ev.of("error")[0]["code"] == "search_failed"


def test_writer_failure_before_text():
    p, req, spies = setup(text="pressure low", language="en-IN", writer=FakeWriter(fail_before=True))
    ev = Events()
    assert p.run(req, ev) == "failed"
    assert ev.of("error")[0]["code"] == "llm_failed"
    assert spies["repo"].queries[req.query_id]["status"] == "failed"


def test_writer_failure_mid_stream():
    p, req, _ = setup(text="pressure low", language="en-IN", writer=FakeWriter(fail_after=3))
    ev = Events()
    assert p.run(req, ev) == "failed"
    assert ev.of("delta") and ev.of("error")[0]["code"] == "llm_failed"
    assert ev.names()[-1] == "error"


def test_question_translation_failure_falls_back_to_original_text():
    p, req, spies = setup(text="HP-07 में E-05 आ रहा है", structured=FakeStructured(fail_question=True))
    ev = Events()
    assert p.run(req, ev) == "answered"
    assert spies["search"].calls[0][1] == "HP-07 में E-05 आ रहा है"


def test_english_copy_failure_does_not_change_the_answer():
    p, req, spies = setup(text="प्रेशर नहीं", writer=FakeWriter(english=None))
    ev = Events()
    assert p.run(req, ev) == "answered"
    row = spies["repo"].queries[req.query_id]
    assert row["status"] == "answered" and row["answer"] is None


def test_cancel_while_writing():
    state = {"cancel": False}

    def on_chunk(n):
        if n == 3:
            state["cancel"] = True

    p, req, spies = setup(text="pressure low", language="en-IN", writer=FakeWriter(on_chunk=on_chunk))
    ev = Events()
    assert p.run(req, ev, cancelled=lambda: state["cancel"]) == "cancelled"
    assert ev.of("done") == []
    assert spies["repo"].queries[req.query_id]["status"] == "cancelled"


def test_cancel_before_search():
    p, req, spies = setup(text="pressure low", language="en-IN")
    ev = Events()
    assert p.run(req, ev, cancelled=lambda: True) == "cancelled"
    assert spies["search"].calls == []


def test_no_machine_searches_whole_plant():
    p, req, spies = setup(text="pump noise", language="en-IN", machine=None)
    ev = Events()
    assert p.run(req, ev) == "answered"
    assert spies["search"].calls[0][2] is None
    assert "not selected" in spies["writer"].stream_calls[0]["user"]


@pytest.mark.parametrize("lang,word", [("ta-IN", "Tamil"), ("mr-IN", "Marathi"), ("od-IN", "Odia")])
def test_answer_language_follows_the_profile(lang, word):
    p, req, spies = setup(text="pressure", language=lang)
    p.run(req, Events())
    assert word in spies["writer"].stream_calls[0]["system"]


def test_english_copy_is_cleaned_when_no_line_is_lost():
    en = ("SAFETY: Lower the ram onto blocks. [E1]\n1. Fit the test gauge. [E1]\n"
          "2. Set the relief valve to 210 bar. [E1][M1][E9]\nCHECK: Pressure reaches 210 bar. [M1]")
    p, req, spies = setup(text="प्रेशर नहीं", writer=FakeWriter(english=en))
    p.run(req, Events())
    row = spies["repo"].queries[req.query_id]
    assert row["answer"].splitlines()[2] == "2. Set the relief valve to 210 bar. [E1][M1]"   # bad ref removed


# ============================================================================ Phase 6: cache + token saving

from app.assist import answer_format as af
from app.assist.settings import AssistSettings
from app.core.answer_cache import chunk_key, machine_key, question_key

from .fakes import GOOD_ANSWER, FakeSearch, search_results


class FakeCache:
    def __init__(self):
        self.rows = {}
        self.gets = []
        self.puts = []

    def get(self, tenant, machine, q_key, c_key):
        self.gets.append((tenant, machine, q_key, c_key))
        return self.rows.get((tenant, machine, q_key, c_key))

    def put(self, **kw):
        self.puts.append(kw)


def _keys(question="pressure is not building on HP-07", machine=HP07):
    sources = af.build_sources(search_results(machine["code"]), 4)
    return machine_key(machine), question_key(question), chunk_key(sources), sources


def test_answer_cache_hit_skips_the_writer():
    cache = FakeCache()
    m_key, q_key, c_key, sources = _keys()
    cache.rows[(TENANT, m_key, q_key, c_key)] = {
        "answer_local": GOOD_ANSWER, "sources": af.public_sources(sources),
        "citations": [{"ref": "E1"}], "confidence": 0.91,
        "model": "groq:openai/gpt-oss-120b", "provider": "groq",
    }
    p, req, spies = setup(text="HP-07 में pressure नहीं बन रहा", cache=cache)
    ev = Events()
    assert p.run(req, ev) == "answered"
    assert spies["writer"].stream_calls == []                 # no LLM call
    assert ev.text() == GOOD_ANSWER
    done = ev.of("done")[0]
    assert done["provider"] == "groq" and done["status"] == "answered"
    assert spies["repo"].queries[req.query_id]["model"] == "groq:openai/gpt-oss-120b"


def test_grounded_answer_is_written_to_cache():
    cache = FakeCache()
    p, req, spies = setup(text="HP-07 में pressure नहीं बन रहा", cache=cache)
    ev = Events()
    assert p.run(req, ev) == "answered"
    assert len(cache.puts) == 1
    row = cache.puts[0]
    assert row["tenant_id"] == TENANT and row["answer_local"].startswith("SAFETY:")
    assert [c["ref"] for c in row["citations"]] == ["E1", "M1"]
    assert row["provider"] == "openai/gpt-oss-120b" or row["provider"] is None


def test_uncited_answer_is_not_cached():
    cache = FakeCache()
    p, req, spies = setup(text="HP-07 में pressure नहीं बन रहा", cache=cache,
                          writer=FakeWriter(answer="1. Tighten the bolt."))
    ev = Events()
    assert p.run(req, ev) == "no_answer"
    assert cache.puts == []


def test_low_score_chunks_are_dropped_before_the_prompt():
    rs = search_results(HP07["code"])
    rs[0]["score"], rs[1]["score"], rs[2]["score"] = 1.0, 0.10, 0.05
    p, req, spies = setup(text="HP-07 में pressure नहीं बन रहा", search=FakeSearch(results=rs))
    ev = Events()
    p.run(req, ev)
    assert [s["ref"] for s in ev.of("sources")[0]["sources"]] == ["E1"]


def test_token_saving_defaults():
    s = AssistSettings(_env_file=None)
    assert s.ANSWER_MAX_TOKENS == 700
    assert s.CONTEXT_K == 4
    assert s.SOURCE_CHARS == 700
    assert s.MIN_SCORE_RATIO == 0.35
