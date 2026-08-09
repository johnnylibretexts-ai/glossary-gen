from glossary_gen.models import Block, Page
from glossary_gen.scan.candidates import (
    CUE_BONUS,
    HEADING_BONUS,
    MIN_EVIDENCE_CHARS,
    score_on_page,
    verify,
)
from glossary_gen.scan.models import Candidate

PAGE = Page(
    url="https://eng.libretexts.org/x",
    blocks=(
        Block(kind="heading", text="Recursion"),
        Block(kind="paragraph", text="Recursion is a technique where a function calls itself."),
    ),
)


def _candidate(evidence: str) -> Candidate:
    return Candidate(term="Recursion", evidence=evidence, confidence=0.9)


def test_verify_accepts_a_span_present_on_the_page():
    assert verify(_candidate("Recursion is a technique where a function calls itself."), PAGE)


def test_verify_ignores_whitespace_and_case_differences():
    assert verify(_candidate("recursion   is  a TECHNIQUE where a function calls itself."), PAGE)


def test_verify_rejects_a_hallucinated_span():
    assert not verify(_candidate("Recursion is a kind of loop unrolling optimisation."), PAGE)


def test_verify_rejects_a_span_too_short_to_be_evidence():
    short = "x" * (MIN_EVIDENCE_CHARS - 1)
    page = Page(url="https://x", blocks=(Block(kind="paragraph", text=short),))
    assert not verify(_candidate(short), page)


NO_HEADING = Page(
    url="https://eng.libretexts.org/y",
    blocks=(Block(kind="paragraph", text="A base case stops the descent."),),
)


def test_score_starts_from_the_model_confidence():
    candidate = Candidate(
        term="Base case", evidence="A base case stops the descent.", confidence=0.5
    )
    assert score_on_page(candidate, NO_HEADING) == 0.5


def test_score_adds_a_bonus_when_the_term_is_a_heading():
    # "calls itself" deliberately carries no definitional cue, so this isolates the
    # heading signal. DEFINITIONAL matches "is a|is an|is the|is called|refers to|means".
    candidate = Candidate(term="Recursion", evidence="calls itself", confidence=0.5)
    assert score_on_page(candidate, PAGE) == 0.5 + HEADING_BONUS


def test_score_matches_a_heading_through_an_alias():
    candidate = Candidate(
        term="Recursive descent", aliases=["Recursion"], evidence="calls itself", confidence=0.4
    )
    assert score_on_page(candidate, PAGE) == 0.4 + HEADING_BONUS


def test_score_adds_both_bonuses_when_both_signals_are_present():
    candidate = Candidate(
        term="Recursion",
        evidence="Recursion is a technique where a function calls itself.",
        confidence=0.5,
    )
    assert score_on_page(candidate, PAGE) == 0.5 + HEADING_BONUS + CUE_BONUS


def test_score_adds_a_bonus_for_definitional_phrasing():
    candidate = Candidate(term="Widget", evidence="A widget is a thing.", confidence=0.5)
    page = Page(url="https://z", blocks=(Block(kind="paragraph", text="A widget is a thing."),))
    assert score_on_page(candidate, page) == 0.5 + CUE_BONUS


def test_score_is_clamped_to_one():
    candidate = Candidate(term="Recursion", evidence="Recursion is the idea", confidence=1.0)
    assert score_on_page(candidate, PAGE) == 1.0
