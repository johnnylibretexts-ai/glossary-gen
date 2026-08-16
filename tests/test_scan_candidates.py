from glossary_gen.models import Block, Page
from glossary_gen.scan.candidates import (
    MIN_EVIDENCE_CHARS,
    corroborations_on_page,
    has_heading_match,
    merge,
    verify,
)
from glossary_gen.scan.models import Candidate, Corroboration, VerifiedCandidate

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


def _scored(term, page_url, confidence, aliases=None):
    return VerifiedCandidate(
        term=term, aliases=aliases or [], evidence="e", page_url=page_url, confidence=confidence
    )


def test_merge_deduplicates_by_slug_and_unions_pages():
    merged = merge([_scored("Recursion", "https://a", 0.6), _scored("recursion", "https://b", 0.4)])

    assert len(merged) == 1
    assert merged[0].pages == ["https://a", "https://b"]


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


def test_merge_emits_no_duplicate_slugs():
    merged = merge([_scored("List", "https://a", 0.5), _scored("list", "https://b", 0.5)])
    assert len({t.slug for t in merged}) == len(merged)


# --- corroboration replaces the fused score (ADR-0004) ---


def test_corroborations_names_each_signal_it_found():
    got = corroborations_on_page(
        _candidate("Recursion is a technique where a function calls itself."), PAGE
    )
    assert set(got) == {Corroboration.HEADING, Corroboration.CUE}


def test_corroborations_omits_a_signal_that_did_not_fire():
    page = Page(
        url="https://a", blocks=(Block(kind="paragraph", text="We use recursion often here."),)
    )
    got = corroborations_on_page(
        Candidate(term="Recursion", evidence="We use recursion often here.", confidence=0.9), page
    )
    assert got == []


def test_multipage_is_merges_business_not_a_pages_business():
    """MULTIPAGE cannot be known from one page, so `corroborations_on_page` never emits it."""
    got = corroborations_on_page(
        _candidate("Recursion is a technique where a function calls itself."), PAGE
    )
    assert Corroboration.MULTIPAGE not in got


def _verified(term, page_url, confidence, corroborations=()):
    return VerifiedCandidate(
        term=term,
        evidence="e" * 30,
        page_url=page_url,
        confidence=confidence,
        corroborations=list(corroborations),
    )


def test_merge_promotes_the_most_confident_surface_form():
    got = merge(
        [
            _verified("recursion", "https://a", 0.4),
            _verified("Recursion", "https://b", 0.9),
        ]
    )
    assert [t.term for t in got] == ["Recursion"]
    assert got[0].aliases == ["recursion"]


def test_merge_breaks_a_confidence_tie_on_corroboration_count():
    got = merge(
        [
            _verified("recursion", "https://a", 0.9),
            _verified("Recursion", "https://b", 0.9, [Corroboration.HEADING]),
        ]
    )
    assert got[0].term == "Recursion"


def test_merge_breaks_a_total_tie_on_first_seen_for_determinism():
    got = merge(
        [
            _verified("recursion", "https://a", 0.9),
            _verified("Recursion", "https://b", 0.9),
        ]
    )
    assert got[0].term == "recursion"


def test_merge_unions_corroborations_and_adds_multipage():
    got = merge(
        [
            _verified("Recursion", "https://a", 0.9, [Corroboration.HEADING]),
            _verified("Recursion", "https://b", 0.8, [Corroboration.CUE]),
        ]
    )
    assert set(got[0].corroborations) == {
        Corroboration.HEADING,
        Corroboration.CUE,
        Corroboration.MULTIPAGE,
    }


def test_merge_does_not_add_multipage_for_a_single_page():
    got = merge([_verified("Recursion", "https://a", 0.9, [Corroboration.HEADING])])
    assert Corroboration.MULTIPAGE not in got[0].corroborations


def test_merge_orders_by_slug_because_nothing_ranks_them():
    got = merge(
        [
            _verified("Zebra", "https://a", 0.2),
            _verified("Apple", "https://b", 0.9),
        ]
    )
    assert [t.term for t in got] == ["Apple", "Zebra"]
