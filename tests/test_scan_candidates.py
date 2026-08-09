from glossary_gen.models import Block, Page
from glossary_gen.scan.candidates import MIN_EVIDENCE_CHARS, verify
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
