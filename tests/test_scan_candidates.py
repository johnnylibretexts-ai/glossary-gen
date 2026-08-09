from glossary_gen.models import Block, Page
from glossary_gen.scan.candidates import (
    CUE_BONUS,
    HEADING_BONUS,
    MIN_EVIDENCE_CHARS,
    MULTIPAGE_BONUS,
    has_heading_match,
    merge,
    score_on_page,
    verify,
)
from glossary_gen.scan.models import ScoredCandidate, Candidate

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


def test_has_heading_match_is_false_when_term_and_aliases_are_all_blank():
    # Candidate validation now rejects a whitespace-only term, so build one that
    # bypasses validation to prove the `has_heading_match` guard itself holds:
    # without it, an empty needle list degenerates to `\b()\b`, which matches at
    # essentially every word boundary and would spuriously return True here.
    candidate = Candidate.model_construct(
        term=" ", aliases=["  ", ""], evidence="Recursion is a technique", confidence=0.9
    )
    assert has_heading_match(candidate, PAGE) is False


def test_has_heading_match_is_true_for_a_normal_term():
    candidate = Candidate(term="Recursion", evidence="calls itself", confidence=0.5)
    assert has_heading_match(candidate, PAGE) is True


def _scored(term, page_url, score, aliases=None):
    return ScoredCandidate(
        term=term, aliases=aliases or [], evidence="e", page_url=page_url, score=score
    )


def test_merge_deduplicates_by_slug_and_unions_pages():
    merged = merge([_scored("Recursion", "https://a", 0.6), _scored("recursion", "https://b", 0.4)])

    assert len(merged) == 1
    assert merged[0].pages == ["https://a", "https://b"]


def test_merge_keeps_the_highest_score_and_adds_the_multipage_bonus():
    merged = merge([_scored("Recursion", "https://a", 0.6), _scored("Recursion", "https://b", 0.4)])

    assert merged[0].score == 0.6 + MULTIPAGE_BONUS


def test_merge_does_not_add_the_multipage_bonus_for_a_single_page():
    merged = merge([_scored("Recursion", "https://a", 0.6)])
    assert merged[0].score == 0.6


def test_merge_unions_aliases_without_duplicates():
    merged = merge(
        [
            _scored("Recursion", "https://a", 0.6, ["recursive"]),
            _scored("Recursion", "https://b", 0.4, ["recursive", "recurse"]),
        ]
    )

    assert merged[0].aliases == ["recursive", "recurse"]


def test_merge_records_a_variant_surface_form_as_an_alias():
    merged = merge([_scored("Recursion", "https://a", 0.6), _scored("recursion", "https://b", 0.4)])
    assert "recursion" in merged[0].aliases


def test_merge_orders_output_by_descending_score():
    merged = merge([_scored("Low", "https://a", 0.2), _scored("High", "https://b", 0.9)])
    assert [t.term for t in merged] == ["High", "Low"]


def test_merge_emits_no_duplicate_slugs():
    merged = merge([_scored("List", "https://a", 0.5), _scored("list", "https://b", 0.5)])
    assert len({t.slug for t in merged}) == len(merged)
