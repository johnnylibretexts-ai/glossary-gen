"""A paid run must not spend money without consent, interactive or not.

The confirmation prompt is guarded by `sys.stdin.isatty()` so a non-interactive run never
hits `input()` and dies with an undefined exit code. That guard was correct and is kept --
but because the whole condition short-circuited, a non-interactive run also skipped
consent entirely and spent. Both CLIs now refuse instead, and `--yes` is the way to say
yes ahead of time.

Dry runs are unaffected: they return before the gate.
"""

import json

import httpx

from glossary_gen import cli, scan_cli
from glossary_gen.cli import EXIT_INPUT_ERROR, EXIT_OK
from glossary_gen.scan.toc import API

BOOK = "https://eng.libretexts.org/Bookshelves/CS/Sample"

TOC_WITH_PAGES = {
    "toc": {
        "structured": {
            "title": "Sample Book",
            "url": BOOK,
            "@id": "1",
            "subdomain": "eng",
            "subpages": [{"title": "1: Intro", "url": f"{BOOK}/01"}],
        }
    }
}

_REAL_PARAGRAPH = (
    "Recursion is a technique where a function calls itself to solve a smaller "
    "instance of the same problem, continuing until it reaches a base case."
)
PAGE_HTML = f"<html><body><h2>Recursion</h2><p>{_REAL_PARAGRAPH}</p></body></html>"


def _scan_handler(request):
    if str(request.url).startswith(API):
        return httpx.Response(200, json=TOC_WITH_PAGES)
    return httpx.Response(200, text=PAGE_HTML)


def _scan_args(tmp_path, *extra):
    return [
        "--book", BOOK,
        "--delay", "0",
        "--cache-dir", str(tmp_path / "cache"),
        "--out", str(tmp_path / "out.json"),
        "--report", str(tmp_path / "report.json"),
        "--ledger", str(tmp_path / "scan.jsonl"),
        *extra,
    ]  # fmt: skip


def _generate_args(tmp_path, *extra):
    payload = {
        "book": {
            "library": "eng",
            "coverID": "1",
            "bookId": "sample",
            "title": "Sample Book",
            "index_url": BOOK,
        },
        "terms": [{"term": "Recursion", "pages": ["https://eng.libretexts.org/hit"]}],
    }
    (tmp_path / "in.json").write_text(json.dumps(payload), encoding="utf-8")
    return [
        "--input", str(tmp_path / "in.json"),
        "--cache-dir", str(tmp_path / "c"),
        "--out", str(tmp_path / "glossary.csv"),
        "--ledger", str(tmp_path / "run.jsonl"),
        *extra,
    ]  # fmt: skip


def _explode_on_input(monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("input() must not be called in a non-interactive context")

    monkeypatch.setattr("builtins.input", _boom)


def test_scan_refuses_to_spend_when_not_interactive_without_yes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        scan_cli,
        "build_http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(_scan_handler)),
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    _explode_on_input(monkeypatch)

    exit_code = scan_cli.run(_scan_args(tmp_path))

    assert exit_code == EXIT_INPUT_ERROR
    assert "refusing to spend" in capsys.readouterr().err


def test_generate_refuses_to_spend_when_not_interactive_without_yes(tmp_path, monkeypatch, capsys):
    # A provider must be configured, or the generate CLI fails on that first and never
    # reaches the gate. The address is unroutable on purpose: if the gate lets the run
    # through, it fails on the network rather than returning EXIT_RUN_ABORTED.
    monkeypatch.setenv("GLOSSARY_GEN_OPENAI_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.delenv("GLOSSARY_GEN_GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(
        cli,
        "build_http_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200, text=PAGE_HTML))
        ),
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    _explode_on_input(monkeypatch)

    exit_code = cli.run(_generate_args(tmp_path))

    assert exit_code == EXIT_INPUT_ERROR
    assert "refusing to spend" in capsys.readouterr().err


def test_scan_refuses_before_fetching_anything(tmp_path, monkeypatch):
    """Refusal must cost nothing — not even a crawl.

    Consent does not depend on the estimate, and the estimate is what needs the page
    count. A scan that refuses only after `collect_pages` would walk an entire book,
    minutes of traffic against libretexts.org, produce nothing, exit non-zero, and do it
    again on the next cron tick.
    """
    requests: list[str] = []

    def _counting_handler(request):
        requests.append(str(request.url))
        return _scan_handler(request)

    monkeypatch.setattr(
        scan_cli,
        "build_http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(_counting_handler)),
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    _explode_on_input(monkeypatch)

    assert scan_cli.run(_scan_args(tmp_path)) == EXIT_INPUT_ERROR
    assert requests == []


def test_yes_flag_is_consent_for_an_unattended_scan(tmp_path, monkeypatch):
    """--yes is the way to authorise an unattended run, so it must still get through."""
    monkeypatch.setattr(
        scan_cli,
        "build_http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(_scan_handler)),
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.delenv("GLOSSARY_GEN_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GLOSSARY_GEN_OPENAI_BASE_URL", raising=False)
    _explode_on_input(monkeypatch)

    # Walks past the gate and fails on the next real thing: no provider configured.
    assert scan_cli.run(_scan_args(tmp_path, "--yes")) == scan_cli.EXIT_INPUT_ERROR


def test_dry_run_is_unaffected_by_the_gate(tmp_path, monkeypatch, capsys):
    """A dry run spends nothing, so it must not be refused for lack of --yes."""
    monkeypatch.setattr(
        cli,
        "build_http_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200, text=PAGE_HTML))
        ),
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    _explode_on_input(monkeypatch)

    exit_code = cli.run(_generate_args(tmp_path, "--dry-run"))

    assert exit_code == EXIT_OK
    assert "refusing to spend" not in capsys.readouterr().err
