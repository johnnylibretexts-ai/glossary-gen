from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

from glossary_gen.ledger import Ledger

PRICES_PATH = Path(__file__).parent / "prices.json"


def load_prices(path: Path = PRICES_PATH) -> dict[str, dict[str, float]]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def actual_cost(
    model: str, tokens_in: int, tokens_out: int, prices: dict[str, dict[str, float]]
) -> float | None:
    """USD cost of tokens already spent, or None when the model has no configured price.

    Lives here because the run is the only thing that prices real spend: the estimators in
    each CLI price a guess, before any tokens exist.

    A None means the model has no configured price, so no ceiling can be computed — and the
    run treats that as "do not trip", never as "over budget". Reversing that would abort
    every run against a model missing from prices.json, on its first subject. The guard
    against silently ignoring a ceiling is not here: both CLIs refuse to start when
    --budget-usd is given for a model they cannot price.
    """
    entry = prices.get(model)
    if not entry:
        return None
    return (tokens_in * entry["input_per_mtok"] + tokens_out * entry["output_per_mtok"]) / 1_000_000


class ModelCall(StrEnum):
    """What happened to the paid call for one subject.

    Three states, not two, because the run's failure counter needs all three and a boolean
    can only say two of them. See ADR-0002.
    """

    ANSWERED = "answered"
    FAILED = "failed"
    NOT_MADE = "not_made"


@dataclass(frozen=True)
class Attempt:
    """One try at a subject: the row to record, and what the model did.

    The producer builds the record — only it knows what belongs in one — and the run
    appends it. The run never reads `record.status`; `model_call` is all it needs.
    """

    record: BaseModel
    model_call: ModelCall


@dataclass
class RunResult:
    """What the run itself owns. Every domain counter belongs to the producer."""

    skipped: int = 0
    aborted: bool = False


def execute_run[T](
    items: Sequence[T],
    ledger: Ledger,
    *,
    subject_of: Callable[[T], str],
    # Handed the subject the run keyed on, so the producer never recomputes it. Two
    # independent computations that must agree are one edit away from not agreeing, and a
    # row written under a key `ledger.has()` cannot match is re-paid for on every resume.
    attempt: Callable[[T, str], Attempt],
    prompt_version: str,
    model: str,
    budget_usd: float | None = None,
    max_consecutive_failures: int = 5,
) -> RunResult:
    """Attempt each subject not already done, recording every attempt."""
    result = RunResult()
    consecutive_failures = 0
    prices = load_prices()  # once, not per subject: prices.json does not change mid-run
    # Seeded from the ledger, not from zero: the ceiling bounds TOTAL spend across resumes
    # of this ledger file. Restarting the count each invocation lets it be crossed once per
    # resume. Records of every status are summed, because a failed attempt was still billed.
    tokens_in_spent = sum(r.tokens_in for r in ledger.records()) if budget_usd is not None else 0
    tokens_out_spent = sum(r.tokens_out for r in ledger.records()) if budget_usd is not None else 0

    def over_ceiling() -> bool:
        if budget_usd is None:
            return False
        spent = actual_cost(model, tokens_in_spent, tokens_out_spent, prices)
        # `actual_cost` returns None for an unpriced model; that must not read as "over
        # budget", because a ceiling that cannot be computed must not abort the run.
        return spent is not None and spent > budget_usd

    for item in items:
        subject = subject_of(item)
        # Checked before the ceiling, because the ceiling bounds SPEND and a skip spends
        # nothing. Reversed, a resumed run already over budget could not even walk past its
        # own finished subjects to let a human use what was already paid for.
        if ledger.has(subject, prompt_version, model):
            result.skipped += 1
            continue

        if over_ceiling():
            result.aborted = True
            break

        outcome = attempt(item, subject)
        # Appended before anything else happens, so a crash costs one subject rather than
        # the run. Charged from that same record, so what was billed and what was written
        # down can never disagree.
        ledger.append(outcome.record)
        tokens_in_spent += outcome.record.tokens_in
        tokens_out_spent += outcome.record.tokens_out

        # Three states, and `NOT_MADE` is deliberately neither branch: a subject the model
        # was never asked about is not a failure, and is not evidence the provider recovered.
        # Compared by value, not identity: `ModelCall` is a StrEnum precisely so a producer
        # may hand back a plain "failed", and `is` would match neither branch — leaving the
        # counter dead and the run paying its way through a whole book against an outage.
        if outcome.model_call == ModelCall.FAILED:
            consecutive_failures += 1
            if consecutive_failures >= max_consecutive_failures:
                result.aborted = True
                break
        elif outcome.model_call == ModelCall.ANSWERED:
            consecutive_failures = 0

        # The second of exactly two ceiling checks, and the reason the loop body has no
        # branches: the check above needs a NEXT subject to fire, so without this one a run
        # whose final subject crosses the ceiling would report success. A run that only
        # skips never reaches here, which is why a skip-only resume is not aborted.
        if over_ceiling():
            result.aborted = True
            break
    return result
