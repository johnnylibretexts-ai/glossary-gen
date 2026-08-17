"""Comparing a generated definition against the one a book's authors wrote."""

import pytest
from pydantic import ValidationError

from glossary_gen.compare import Verdict, judge_prompt, parse_verdict, structural_flags

AUTHOR = "a number that is equal to the square root of the variance and measures spread"


def test_a_definition_that_ends_mid_thought_is_flagged():
    assert "no-sentence" in structural_flags(
        term="Panel data", definition="Multidimensional structured datasets", reference=AUTHOR
    )


def test_a_complete_sentence_is_not_flagged():
    definition = "A measure of how far the values in a dataset sit from their mean."

    flags = structural_flags(term="Standard deviation", definition=definition, reference=AUTHOR)

    assert flags == ()


def test_a_definition_that_only_restates_the_term_is_flagged():
    assert "restates-term" in structural_flags(
        term="Random sample",
        definition="A random sample, which is used throughout statistics.",
        reference=AUTHOR,
    )


def test_a_definition_that_opens_with_the_term_and_then_defines_it_is_not_flagged():
    """Opening with the term is normal prose, not circularity. Only a first clause
    that is the term and nothing else says the definition added nothing.
    """
    definition = "A random sample is one in which every member has an equal chance of selection."

    flags = structural_flags(term="Random sample", definition=definition, reference=AUTHOR)

    assert "restates-term" not in flags


def test_a_definition_under_half_the_authors_length_is_flagged():
    assert "much-shorter" in structural_flags(
        term="Variance", definition="How spread out data is.", reference=AUTHOR
    )


def test_flags_are_returned_in_a_stable_order():
    """They land in a CSV column that gets diffed across runs; set iteration order
    would make identical results look changed.
    """
    flags = structural_flags(term="Mode", definition="the mode", reference=AUTHOR)

    assert flags == tuple(sorted(flags))


def test_the_judge_prompt_carries_both_definitions_and_the_term():
    prompt = judge_prompt(term="Variance", author=AUTHOR, generated="A measure of spread.")

    assert "Variance" in prompt
    assert AUTHOR in prompt
    assert "A measure of spread." in prompt


def test_a_verdict_parses_out_of_a_fenced_json_reply():
    raw = '```json\n{"verdict": "contradicts", "reason": "the sign is inverted"}\n```'

    assert parse_verdict(raw) == Verdict(verdict="contradicts", reason="the sign is inverted")


def test_an_unknown_verdict_is_refused_rather_than_coerced():
    """A judge that answers "mostly consistent" must fail loudly: silently mapping
    it onto `consistent` would turn an unparsed reply into a clean result.
    """
    with pytest.raises(ValidationError):
        parse_verdict('{"verdict": "mostly consistent", "reason": "close enough"}')


def test_a_verdict_without_a_reason_is_refused():
    with pytest.raises(ValidationError):
        parse_verdict('{"verdict": "contradicts"}')
