import json

import httpx

from glossary_gen.cli import dry_run, run
from glossary_gen.fetch import PageCache
from glossary_gen.models import Term

_REAL_PARAGRAPH = (
    "Recursion is a technique where a function calls itself to solve a smaller "
    "instance of the same problem, continuing until it reaches a base case."
)
HTML_HIT = f"<html><body><p>{_REAL_PARAGRAPH}</p></body></html>"
HTML_MISS = "<html><body><p>Nothing relevant here.</p></body></html>"


def make_cache(tmp_path, routes):
    def handler(request):
        url = str(request.url)
        if url not in routes:
            return httpx.Response(404)
        return httpx.Response(200, text=routes[url])

    return PageCache(tmp_path, httpx.Client(transport=httpx.MockTransport(handler)))


def test_dry_run_counts_coverage(tmp_path):
    routes = {
        "https://eng.libretexts.org/hit": HTML_HIT,
        "https://eng.libretexts.org/miss": HTML_MISS,
    }
    cache = make_cache(tmp_path, routes)
    terms = [
        Term(
            term="Recursion",
            slug="recursion",
            aliases=(),
            pages=("https://eng.libretexts.org/hit",),
        ),
        Term(term="Recursion", slug="r2", aliases=(), pages=("https://eng.libretexts.org/miss",)),
        Term(term="Ghost", slug="ghost", aliases=(), pages=("https://eng.libretexts.org/gone",)),
    ]

    report = dry_run(terms, cache)

    assert report.total == 3
    assert report.with_excerpts == 1
    assert report.without_excerpts == 2
    assert report.failed_pages == ["https://eng.libretexts.org/gone"]
    assert "ghost" in report.missing_terms and "r2" in report.missing_terms


def test_run_dry_run_exits_zero_and_reports(tmp_path, capsys, monkeypatch):
    payload = {
        "terms": [
            {"term": "Recursion", "pages": ["https://eng.libretexts.org/hit"]},
        ]
    }
    input_path = tmp_path / "in.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    def fake_client():
        return httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, text=HTML_HIT))
        )

    monkeypatch.setattr("glossary_gen.cli.build_http_client", fake_client)

    exit_code = run(["--input", str(input_path), "--cache-dir", str(tmp_path / "c"), "--dry-run"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "terms with excerpts: 1" in out
    assert "no model was called" in out


def test_run_reports_input_error_as_exit_two(tmp_path, capsys):
    missing = tmp_path / "nope.json"
    exit_code = run(["--input", str(missing), "--dry-run"])
    assert exit_code == 2
    assert "does not exist" in capsys.readouterr().err


def test_module_entry_points_are_runnable():
    """`python -m glossary_gen` and `python -m glossary_gen.cli` must actually run.

    Both previously imported and exited 0 silently, which reads as a broken install.
    """
    import subprocess
    import sys

    for target in ("glossary_gen", "glossary_gen.cli"):
        result = subprocess.run(
            [sys.executable, "-m", target, "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"{target}: exit {result.returncode}"
        assert "--dry-run" in result.stdout, f"{target}: no usage output"
