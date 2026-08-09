"""The cost-confirmation prompt in `scan_cli.run`, mirrored from `cli.run` (FIX 2).

A run without `--yes` must never call `input()` in a non-interactive context (cron, CI,
nohup, a pipe) -- that hits EOFError and dies with an undefined exit code. And declining
an interactive prompt is not a failure: it must print an explicit message and return the
same EXIT_OK that `cli.run` returns, not the silent EXIT_RUN_ABORTED this used to return.
"""

import httpx

from glossary_gen import scan_cli
from glossary_gen.scan.toc import API
from glossary_gen.scan_cli import EXIT_INPUT_ERROR, EXIT_OK, build_parser, run

BOOK = "https://eng.libretexts.org/Bookshelves/CS/Sample"

TOC_WITH_PAGES = {
    "toc": {
        "structured": {
            "title": "Sample Book",
            "url": BOOK,
            "@id": "1",
            "subdomain": "eng",
            "subpages": [
                {"title": "1: Intro", "url": f"{BOOK}/01"},
            ],
        }
    }
}

PAGE_HTML = """
<html><body>
<h2>Recursion</h2>
<p>Recursion is a technique where a function calls itself.</p>
</body></html>
"""


def _mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _handler(request):
    if str(request.url).startswith(API):
        return httpx.Response(200, json=TOC_WITH_PAGES)
    return httpx.Response(200, text=PAGE_HTML)


def _base_args(tmp_path, *extra):
    return [
        "--book",
        BOOK,
        "--delay",
        "0",
        "--cache-dir",
        str(tmp_path / "cache"),
        "--out",
        str(tmp_path / "out.json"),
        "--report",
        str(tmp_path / "report.json"),
        "--ledger",
        str(tmp_path / "scan.jsonl"),
        *extra,
    ]


def _no_provider_configured(monkeypatch):
    # build_client (shared with cli.py) raises InputError -> EXIT_INPUT_ERROR when no
    # provider is configured. Reaching that (rather than EXIT_OK/EXIT_RUN_ABORTED from
    # the prompt) is the proof that the run walked PAST the confirmation gate.
    monkeypatch.delenv("GLOSSARY_GEN_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GLOSSARY_GEN_OPENAI_BASE_URL", raising=False)


def test_non_interactive_run_without_yes_never_calls_input(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(scan_cli, "build_http_client", lambda: _mock_client(_handler))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    def _boom(*_a, **_k):
        raise AssertionError("input() must not be called in a non-interactive context")

    monkeypatch.setattr("builtins.input", _boom)
    _no_provider_configured(monkeypatch)

    exit_code = run(_base_args(tmp_path))

    # A defined exit code (not an uncaught EOFError -> implicit exit 1), and it got far
    # enough past the prompt to hit the next real failure (no provider configured).
    assert exit_code == EXIT_INPUT_ERROR
    assert "aborted by user" not in capsys.readouterr().out


def test_declining_the_prompt_prints_a_message_and_returns_exit_ok(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(scan_cli, "build_http_client", lambda: _mock_client(_handler))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")

    exit_code = run(_base_args(tmp_path))

    assert exit_code == EXIT_OK
    assert "aborted by user" in capsys.readouterr().out


def test_yes_reply_is_accepted_same_as_y(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(scan_cli, "build_http_client", lambda: _mock_client(_handler))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
    _no_provider_configured(monkeypatch)

    exit_code = run(_base_args(tmp_path))

    assert exit_code == EXIT_INPUT_ERROR  # proceeded past the prompt, same as "y" would
    assert "aborted by user" not in capsys.readouterr().out


def test_yes_flag_skips_the_prompt_entirely(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(scan_cli, "build_http_client", lambda: _mock_client(_handler))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def _boom(*_a, **_k):
        raise AssertionError("input() must not be called when --yes is given")

    monkeypatch.setattr("builtins.input", _boom)
    _no_provider_configured(monkeypatch)

    exit_code = run(_base_args(tmp_path, "--yes"))

    assert exit_code == EXIT_INPUT_ERROR


def test_parser_still_defines_yes_flag():
    args = build_parser().parse_args(["--book", BOOK, "--yes"])
    assert args.yes is True
