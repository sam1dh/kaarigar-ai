"""The answer line format: sources, parsing, ref checking, the NO_ANSWER gate, confidence."""
from app.assist import answer_format as af

from .fakes import GOOD_ANSWER, search_results

VALID = {"E1", "M1", "H1"}


def test_build_sources_gives_refs_per_label_in_rank_order():
    res = search_results() + [dict(search_results()[0], source_id="x2", chunk_id="c2")]
    src = af.build_sources(res, 6)
    assert [s["ref"] for s in src] == ["E1", "M1", "H1", "E2"]
    assert src[0]["seed_key"] == "R01" and src[0]["same_machine"] is True
    assert "_text" in src[0]
    pub = af.public_sources(src)
    assert all(not any(k.startswith("_") for k in s) for s in pub)
    assert len(pub[0]["snippet"]) <= 180


def test_build_sources_respects_context_k():
    assert len(af.build_sources(search_results(), 2)) == 2


def test_parse_good_answer():
    p = af.parse_answer(GOOD_ANSWER, VALID)
    assert not p.no_answer
    assert len(p.safety) == 1 and p.safety[0]["refs"] == ["E1"]
    assert [s["n"] for s in p.steps] == [1, 2]
    assert p.steps[1]["refs"] == ["E1", "M1"]
    assert "210 bar" in p.steps[1]["text"] and "[" not in p.steps[1]["text"]
    assert p.check and p.check["refs"] == ["M1"]
    assert p.refs_used == ["E1", "M1"]


def test_unknown_refs_are_dropped_and_reported():
    p = af.parse_answer("1. Do this. [E1][E9]\n2. Then that. [M4]", VALID)
    assert p.steps[0]["refs"] == ["E1"]
    assert p.steps[1]["refs"] == []
    assert p.dropped_refs == ["E9", "M4"]
    assert p.cited_steps == 1


def test_comma_refs_markdown_and_bullets():
    text = "**SAFETY:** Lock out the motor [E1, M1]\n- 1) Check the fuse [H1]\n2. Replace it [e1]"
    p = af.parse_answer(text, VALID)
    assert p.safety[0]["refs"] == ["E1", "M1"]
    assert p.steps[0]["text"] == "Check the fuse" and p.steps[0]["refs"] == ["H1"]
    assert p.steps[1]["refs"] == ["E1"]


def test_wrapped_line_joins_previous_step():
    p = af.parse_answer("1. Fit the gauge on the\npump outlet. [E1]\n2. Set 210 bar [M1]", VALID)
    assert p.steps[0]["text"] == "Fit the gauge on the pump outlet."
    assert p.steps[0]["refs"] == ["E1"]


def test_free_text_without_format_becomes_one_step():
    p = af.parse_answer("Set the relief valve to 210 bar using the test gauge [E1].", VALID)
    assert len(p.steps) == 1 and p.steps[0]["refs"] == ["E1"]
    assert p.steps[0]["text"].endswith("gauge.")


def test_no_answer_variants():
    for t in ("NO_ANSWER", "  no_answer ", "`NO_ANSWER`", "NO ANSWER", "NO_ANSWER."):
        assert af.parse_answer(t, VALID).no_answer, t
    assert af.parse_answer("", VALID).no_answer
    assert af.parse_answer("[E1]", VALID).no_answer          # refs only, no words


def test_render_round_trip_and_speakable():
    p = af.parse_answer(GOOD_ANSWER, VALID)
    again = af.parse_answer(af.render_answer(p), VALID)
    assert again.as_dict() == p.as_dict()
    speech = af.speakable(p)
    assert "[" not in speech and speech.startswith("Safety.") and "1." in speech
    assert af.render_answer(af.ParsedAnswer(no_answer=True)) == "NO_ANSWER"


def test_confidence():
    src = af.build_sources(search_results(), 6)
    full = af.parse_answer(GOOD_ANSWER, VALID)
    assert af.confidence(full, src, None) == 0.95                # fully cited + same-machine expert record
    half = af.parse_answer("1. a [M1]\n2. b", VALID)
    assert 0.5 <= af.confidence(half, src, None) < 0.7
    none = af.parse_answer("1. a\n2. b", VALID)
    assert af.confidence(none, src, None) == 0.2
    assert af.confidence(full, src, 0.3) == 0.55                 # capped by the reranker's confidence
    assert af.confidence(af.ParsedAnswer(no_answer=True), src, None) == 0.0


def feed_all(chunks):
    g = af.NoAnswerGate()
    out = "".join(g.feed(c) for c in chunks) + g.flush()
    return out, g.no_answer


def test_gate_passes_normal_text_unchanged():
    out, no = feed_all(["SAF", "ETY: x [E1]\n1. y [E1]"])
    assert out == "SAFETY: x [E1]\n1. y [E1]" and not no


def test_gate_holds_no_answer_split_across_chunks():
    out, no = feed_all(["N", "O_", "ANS", "WER"])
    assert out == "" and no


def test_gate_releases_short_text_that_only_looks_like_no():
    out, no = feed_all(["No"])          # e.g. a one-word answer: released at the end
    assert out == "No" and not no
    out, no = feed_all(["NO", "TE: check [E1]"])
    assert out == "NOTE: check [E1]" and not no


def test_gate_strips_leading_whitespace():
    out, _ = feed_all(["\n  ", "1. a [E1]"])
    assert out == "1. a [E1]"
