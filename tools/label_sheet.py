"""Keyboard-driven labeller for the review sheets in `docs/research/`.

One row on screen at a time, one keypress per label, saved after every row and
resumable from wherever you stopped. It writes **only** what a human types: there
is no code path here that produces a label, which is the point — these sheets are
the ground truth a machine baseline gets scored against (ADR-0005).

    python3 tools/label_sheet.py                     # term fit
    python3 tools/label_sheet.py --sheet <path.csv>  # any sheet with a label column

Deliberately absent: a running yes/no/borderline tally. Progress is shown, the cut
rate is not — watching it move would let the labelling drift toward a number.
"""

from __future__ import annotations

import argparse
import csv
import os
import platform
import subprocess
import sys
import termios
import textwrap
import tty
import webbrowser
from pathlib import Path
from urllib.parse import unquote

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SHEET = REPO / "docs/research/2026-08-16-openstax-term-fit.csv"

# Every sheet's label column, and the values it accepts, keyed by the header it uses.
LABEL_COLUMNS = {
    "term_fit": ("yes", "no", "borderline"),
    "definition_sound": ("yes", "no", "borderline"),
}
QUESTION = {
    "term_fit": "Does a reader of THIS book need this term in a glossary?",
    "definition_sound": "Is this definition correct and does it stand on its own?",
}
AUDIENCE = (
    "Python Programming (OpenStax) — a first programming course. Readers have no prior "
    "programming experience, but are not new to computers."
)

BOLD, DIM, RESET = "\x1b[1m", "\x1b[2m", "\x1b[0m"
CLEAR = "\x1b[2J\x1b[H"


def getch() -> str:
    """One keypress, no Enter. Returns '' if stdin is not a terminal."""
    if not sys.stdin.isatty():
        return ""
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    if ch == "\x03":  # ctrl-c reads as a plain byte in raw mode
        raise KeyboardInterrupt
    return ch


def section_label(url: str) -> str:
    """'…/11%3A_Classes/11.01%3A_Object-Oriented…' -> '11.01: Object-Oriented…'."""
    return unquote(url.rstrip("/").rsplit("/", 1)[-1]).replace("_", " ")


def open_url(url: str) -> None:
    if platform.system() == "Darwin":
        subprocess.run(["open", url], check=False)
    else:
        webbrowser.open(url)


def read_sheet(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def write_sheet(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    """Atomic: a crash mid-write must not cost an afternoon of labels."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def render(row: dict[str, str], done: int, total: int, label_col: str, last: str) -> None:
    width = min(88, os.get_terminal_size().columns if sys.stdout.isatty() else 88)
    print(CLEAR, end="")
    print(f"{DIM}[ {done + 1} / {total} ]  {QUESTION[label_col]}{RESET}\n")
    print(f"  {BOLD}{row['term']}{RESET}")

    pages = [p for p in (row.get("pages") or "").split("|") if p]
    if pages:
        print(f"  {DIM}{' | '.join(section_label(p) for p in pages)}{RESET}")
    if row.get("aliases"):
        print(f"  {DIM}aliases: {row['aliases'].replace('|', ' · ')}{RESET}")
    if row.get("definition"):
        print()
        for line in textwrap.wrap(row["definition"], width - 4):
            print(f"  {line}")

    values = LABEL_COLUMNS[label_col]
    keys = "   ".join(f"[{v[0]}] {v}" for v in values)
    print(f"\n  {keys}")
    extras = "  [s] skip   [u] undo   [q] save + quit"
    print(f"  {DIM}{'[p] open page  ' if pages else ''}{extras.strip()}{RESET}")
    if last:
        print(f"\n  {DIM}last: {last}{RESET}")
    print("\n  > ", end="", flush=True)


def prompt_reason(term: str, verdict: str) -> str:
    """Required on anything that is not `yes` — a sentence, not a category."""
    print(f"\r\n  {DIM}why is {term} {verdict}? (a sentence){RESET}")
    while True:
        reason = input("  > ").strip()
        if reason:
            return reason
        print(f"  {DIM}required for {verdict} — say why in your own words{RESET}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    args = ap.parse_args()

    if not sys.stdin.isatty():
        print("run this in a terminal window — it reads single keypresses", file=sys.stderr)
        return 1

    columns, rows = read_sheet(args.sheet)
    label_col = next((c for c in columns if c in LABEL_COLUMNS), None)
    if label_col is None:
        print(f"no label column in {args.sheet.name}: {columns}", file=sys.stderr)
        return 1
    values = LABEL_COLUMNS[label_col]
    by_key = {v[0]: v for v in values}
    has_checked = "checked_page" in columns

    if label_col == "term_fit":
        print(f"{CLEAR}{BOLD}Term fit{RESET} — judged against this audience and nothing else:\n")
        for line in textwrap.wrap(AUDIENCE, 84):
            print(f"  {line}")
        print(f"\n{DIM}  Never 'is the definition any good' — that is the other sheet.{RESET}")
        print("\n  press any key to start ")
        getch()

    total = len(rows)
    undo: list[tuple[int, dict[str, str]]] = []
    last = ""
    i = 0
    while True:
        while i < total and (rows[i].get(label_col) or "").strip():
            i += 1
        if i >= total:
            break

        row = rows[i]
        done = sum(1 for r in rows if (r.get(label_col) or "").strip())
        render(row, done, total, label_col, last)
        key = getch().lower()

        if key == "q":
            break
        if key == "p" and row.get("pages"):
            open_url(row["pages"].split("|")[0])
            if has_checked:
                row["checked_page"] = "y"
                write_sheet(args.sheet, columns, rows)
            continue
        if key == "s":
            i += 1
            continue
        if key == "u" and undo:
            j, before = undo.pop()
            rows[j] = before
            write_sheet(args.sheet, columns, rows)
            i = j
            last = f"undone — {before['term']} is unlabelled again"
            continue
        if key not in by_key:
            continue

        verdict = by_key[key]
        undo.append((i, dict(row)))
        row[label_col] = verdict
        if verdict != "yes":
            row["reason"] = prompt_reason(row["term"], verdict)
        write_sheet(args.sheet, columns, rows)
        last = f"{row['term']} → {verdict}"
        i += 1

    labelled = sum(1 for r in rows if (r.get(label_col) or "").strip())
    write_sheet(args.sheet, columns, rows)
    print(f"{CLEAR}saved {args.sheet}")
    print(f"  {labelled} of {total} labelled, {total - labelled} to go")
    if labelled < total:
        print(f"  {DIM}rerun the same command to pick up where you stopped{RESET}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nstopped — everything labelled so far is saved")
        raise SystemExit(130) from None
