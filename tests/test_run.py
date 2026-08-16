from pydantic import BaseModel

from glossary_gen.ledger import Ledger
from glossary_gen.run import Attempt, ModelCall, RunResult, execute_run

# A model that prices.json prices. `actual_cost` returns None for an unpriced model and the
# ceiling short-circuits on None, so a made-up name would let every budget test pass through
# the guard it means to prove. gemini-3.5-flash is 0.3 in / 2.5 out per Mtok.
MODEL = "gemini-3.5-flash"


class _Rec(BaseModel):
    """The minimum a record must expose to be run through the ledger.

    Deliberately not `LedgerRecord` or `ScanRecord`: the run must work for any record type
    satisfying the contract in `Ledger`'s docstring, and using a producer's own record here
    would let the run acquire a dependency on one without the tests noticing.
    """

    subject: str
    prompt_version: str
    model: str
    status: str
    tokens_in: int = 0
    tokens_out: int = 0


def rec(subject, status="ok", tokens_in=0, tokens_out=0):
    return _Rec(
        subject=subject,
        prompt_version="v1",
        model=MODEL,
        status=status,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )


def ledger_at(tmp_path):
    return Ledger(tmp_path / "run.jsonl", record_cls=_Rec)


def run(items, ledger, attempt, **kwargs):
    return execute_run(
        items,
        ledger,
        subject_of=lambda item: item,
        attempt=attempt,
        prompt_version="v1",
        model=MODEL,
        **kwargs,
    )


def test_each_subject_is_attempted_and_its_record_appended(tmp_path):
    ledger = ledger_at(tmp_path)
    seen = []

    def attempt(item):
        seen.append(item)
        return Attempt(record=rec(item), model_call=ModelCall.ANSWERED)

    result = run(["a", "b"], ledger, attempt)

    assert seen == ["a", "b"]
    assert [r.subject for r in ledger.records()] == ["a", "b"]
    assert result == RunResult(skipped=0, aborted=False)


def test_a_subject_already_done_is_never_attempted(tmp_path):
    """The whole point of the ledger: a second run must not re-pay for finished work."""
    ledger = ledger_at(tmp_path)
    ledger.append(rec("a"))  # status ok, so `a` is done
    seen = []

    def attempt(item):
        seen.append(item)
        return Attempt(record=rec(item), model_call=ModelCall.ANSWERED)

    result = run(["a", "b"], ledger, attempt)

    assert seen == ["b"]
    assert result.skipped == 1


def test_the_ceiling_is_seeded_from_the_ledger_not_from_zero(tmp_path):
    """The ceiling bounds TOTAL spend across resumes of one ledger, not spend per run.

    Restarting the count at zero on every resume lets the ceiling be crossed once per
    invocation, which for a book-sized run is the difference between a cap and a suggestion.
    1,000,000 tokens_in at 0.3/Mtok is $0.30, comfortably over the $0.01 ceiling here.
    """
    ledger = ledger_at(tmp_path)
    ledger.append(rec("already-done", tokens_in=1_000_000))
    seen = []

    def attempt(item):
        seen.append(item)
        return Attempt(record=rec(item), model_call=ModelCall.ANSWERED)

    result = run(["a"], ledger, attempt, budget_usd=0.01)

    assert seen == []  # nothing attempted: the ceiling was already crossed
    assert result.aborted is True


def test_spend_is_charged_from_the_record_the_producer_wrote(tmp_path):
    """One number, not two. The row that lands in the ledger IS what gets charged.

    Carrying token counts on the attempt as well as on the record would let the two
    disagree, and a row saying 300 while the ceiling was charged 0 is precisely the shape of
    the defect fixed in a62b3d6.
    """
    ledger = ledger_at(tmp_path)
    seen = []

    def attempt(item):
        seen.append(item)
        return Attempt(record=rec(item, tokens_in=1_000_000), model_call=ModelCall.ANSWERED)

    result = run(["a", "b"], ledger, attempt, budget_usd=0.01)

    assert seen == ["a"]  # `a` cost $0.30, so `b` was never attempted
    assert result.aborted is True


def test_the_last_subject_crossing_the_ceiling_still_aborts(tmp_path):
    """A top-of-loop check needs a NEXT subject to fire, and the last one has none.

    Without a check after spending, a run whose final subject blows the ceiling reports
    success and exits 0 — the operator learns nothing, and the overspend is invisible until
    someone reads the ledger.
    """
    ledger = ledger_at(tmp_path)

    def attempt(item):
        return Attempt(record=rec(item, tokens_in=1_000_000), model_call=ModelCall.ANSWERED)

    result = run(["only"], ledger, attempt, budget_usd=0.01)

    assert result.aborted is True


def test_a_resume_with_nothing_left_to_do_is_not_aborted(tmp_path):
    """The ceiling bounds SPEND, and a run that only skips spends nothing.

    A resumed run whose recorded spend already exceeds the ceiling must still be able to
    walk past every finished subject and report cleanly — otherwise work already paid for
    can never be collected. This is why the post-spend check sits inside the loop body after
    an attempt, rather than once after the loop: a skip-only run must never reach it.
    """
    ledger = ledger_at(tmp_path)
    ledger.append(rec("a", tokens_in=1_000_000))
    ledger.append(rec("b", tokens_in=1_000_000))

    def attempt(item):
        raise AssertionError(f"{item} is already done and must not be attempted")

    result = run(["a", "b"], ledger, attempt, budget_usd=0.01)

    assert result.skipped == 2
    assert result.aborted is False


def test_the_run_stops_after_n_consecutive_provider_failures(tmp_path):
    """A provider that is down stays down. Walking the whole book to prove it costs money."""
    ledger = ledger_at(tmp_path)
    seen = []

    def attempt(item):
        seen.append(item)
        return Attempt(record=rec(item, status="llm_error"), model_call=ModelCall.FAILED)

    result = run(["a", "b", "c", "d", "e"], ledger, attempt, max_consecutive_failures=3)

    assert seen == ["a", "b", "c"]
    assert result.aborted is True


def test_an_answered_call_clears_the_failure_count(tmp_path):
    """Consecutive means consecutive: a provider that answers is not down."""
    ledger = ledger_at(tmp_path)
    seen = []

    def attempt(item):
        seen.append(item)
        if item == "c":
            return Attempt(record=rec(item), model_call=ModelCall.ANSWERED)
        return Attempt(record=rec(item, status="llm_error"), model_call=ModelCall.FAILED)

    result = run(["a", "b", "c", "d", "e"], ledger, attempt, max_consecutive_failures=3)

    assert seen == ["a", "b", "c", "d", "e"]  # `c` reset the count, so d+e only reach 2
    assert result.aborted is False


def test_a_call_that_was_never_made_leaves_the_failure_count_untouched(tmp_path):
    """The third state, and the reason `model_call` is not a boolean. See ADR-0002.

    A subject the model was never asked about is evidence of nothing: it is not a failure,
    and it is not proof the provider recovered. Clearing the count on one would buy a fourth
    failed call here; counting it as a failure would abort a run over a term the provider
    never saw. Both producers already behave this way — a term with no excerpt, a page with
    no article — and those characterization tests are what this generalises.
    """
    ledger = ledger_at(tmp_path)
    seen = []

    def attempt(item):
        seen.append(item)
        if item == "c":
            return Attempt(record=rec(item), model_call=ModelCall.NOT_MADE)
        return Attempt(record=rec(item, status="llm_error"), model_call=ModelCall.FAILED)

    result = run(["a", "b", "c", "d", "e"], ledger, attempt, max_consecutive_failures=3)

    assert seen == ["a", "b", "c", "d"]  # a(1) b(2) c(still 2) d(3) -> stop
    assert result.aborted is True
