"""Generation's fetch guard widens to the book it was given, exactly as the scan's does.

`glossary-scan` takes the host a person pasted into `--book` and widens `is_allowed_url`
by that one exact host. `glossary-gen` had no equivalent, so it could only ever fetch the
standing allowlist — `*.libretexts.org` plus the named exact hosts. An index the scanner
produced from any other book would therefore reach step 2 and fail every single page.
"""

import json

import httpx
import pytest

from glossary_gen.cli import run

BOOK = "https://www.saskoer.ca/handbook/"
PAGE = "https://www.saskoer.ca/handbook/chapter/recursion/"

_PARAGRAPH = (
    "Recursion is a technique where a function calls itself to solve a smaller "
    "instance of the same problem, continuing until it reaches a base case."
)
HTML = f"<html><body><p>{_PARAGRAPH}</p></body></html>"


def _index(tmp_path, *, book_block):
    payload = {"terms": [{"term": "Recursion", "pages": [PAGE]}]}
    if book_block:
        payload["book"] = {
            "library": "www.saskoer.ca",
            "coverID": "handbook",
            "bookId": "handbook",
            "title": "Handbook",
            "index_url": BOOK,
        }
    path = tmp_path / "index.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture
def served(monkeypatch):
    """Serve any request, so the only thing that can refuse a page is the guard."""
    requested: list[str] = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(200, text=HTML)

    monkeypatch.setattr(
        "glossary_gen.cli.build_http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return requested


def test_the_indexs_book_url_authorises_its_own_host(tmp_path, capsys, served):
    exit_code = run(
        [
            "--input",
            str(_index(tmp_path, book_block=True)),
            "--cache-dir",
            str(tmp_path / "c"),
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert served == [PAGE]
    assert "terms with excerpts: 1" in capsys.readouterr().out


def test_an_index_with_no_book_block_widens_nothing(tmp_path, capsys, served):
    """A CSV index, or a JSON one without a book block, carries no book URL — so there is
    nothing a person named, and the guard stays where it was. Here that leaves not one
    fetchable page, which is refused up front as a misconfigured invocation: `served`
    being empty asserts no request was made.
    """
    exit_code = run(
        [
            "--input",
            str(_index(tmp_path, book_block=False)),
            "--cache-dir",
            str(tmp_path / "c"),
            "--dry-run",
        ]
    )

    assert exit_code == 2
    assert served == []
    assert "no page in this index is on an allowed source" in capsys.readouterr().err


def test_a_plain_http_book_url_widens_nothing(tmp_path, capsys, served):
    """`index_url` arrives inside a data file, not from a command line, so its scheme is
    checked before its host is trusted. `http://` buys no widening.
    """
    payload = {
        "book": {
            "library": "www.saskoer.ca",
            "coverID": "handbook",
            "bookId": "handbook",
            "index_url": "http://www.saskoer.ca/handbook/",
        },
        "terms": [{"term": "Recursion", "pages": [PAGE]}],
    }
    path = tmp_path / "index.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    exit_code = run(["--input", str(path), "--cache-dir", str(tmp_path / "c"), "--dry-run"])

    assert exit_code == 2
    assert served == []


def test_the_widening_is_one_exact_host_not_a_suffix(tmp_path, capsys, served):
    """Naming `www.saskoer.ca` must not admit `evil.www.saskoer.ca`.

    The index holds one page on each, so the run proceeds and the property under test is
    which of the two was fetched — not the blanket refusal that fires when nothing is
    reachable at all.
    """
    payload = {
        "book": {
            "library": "www.saskoer.ca",
            "coverID": "handbook",
            "bookId": "handbook",
            "index_url": BOOK,
        },
        "terms": [
            {"term": "Recursion", "pages": [PAGE]},
            {"term": "Iteration", "pages": ["https://evil.www.saskoer.ca/handbook/x/"]},
        ],
    }
    path = tmp_path / "index.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    exit_code = run(["--input", str(path), "--cache-dir", str(tmp_path / "c"), "--dry-run"])

    assert exit_code == 0
    assert served == [PAGE]
    assert "pages failed: 1" in capsys.readouterr().out
