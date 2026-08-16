import httpx
import pytest

from glossary_gen import scan_cli
from glossary_gen.models import Block, Page
from glossary_gen.scan.toc import API
from glossary_gen.scan_cli import build_parser, structural_preview

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
                {"title": "2: More", "url": f"{BOOK}/02"},
            ],
        }
    }
}

TOC_NO_PAGES = {
    "toc": {
        "structured": {
            "title": "Empty Book",
            "@id": "2",
            "subdomain": "eng",
            "subpages": [],
        }
    }
}


def _mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


PAGES = [
    Page(
        url="https://eng.libretexts.org/a",
        blocks=(
            Block(kind="heading", text="Learning Objectives"),
            Block(kind="heading", text="Recursion"),
            Block(kind="paragraph", text="Recursion is a technique."),
        ),
    ),
    Page(url="https://eng.libretexts.org/b", blocks=(Block(kind="paragraph", text="Intro."),)),
]


def test_preview_counts_pages_and_heading_candidates():
    report = structural_preview(PAGES)

    assert report.pages == 2
    assert report.candidates == ["Recursion"]


def test_preview_drops_template_boilerplate():
    report = structural_preview(PAGES)
    assert "Learning Objectives" not in report.candidates


def test_parser_requires_a_book_url():
    parser = build_parser()
    args = parser.parse_args(["--book", "https://eng.libretexts.org/x"])

    assert args.book == "https://eng.libretexts.org/x"
    assert args.dry_run is False


def test_parser_has_no_min_score_flag():
    """Removed with the fused score it thresholded on — see ADR-0004.

    It cut terms out of the index permanently, before generation, on a number that tied
    64% of a real book's terms at the ceiling; and because a cut term was never written
    anywhere, the damage was invisible.
    """
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--book", BOOK, "--min-score", "0.5"])


def test_limit_rejects_zero():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--book", BOOK, "--limit", "0"])


def test_limit_rejects_negative():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--book", BOOK, "--limit", "-1"])


def test_dry_run_aborts_when_every_page_fails(tmp_path, monkeypatch, capsys):
    def handler(request):
        if str(request.url).startswith(API):
            return httpx.Response(200, json=TOC_WITH_PAGES)
        return httpx.Response(404)

    monkeypatch.setattr(scan_cli, "build_http_client", lambda: _mock_client(handler))

    exit_code = scan_cli.run(
        ["--book", BOOK, "--dry-run", "--delay", "0", "--cache-dir", str(tmp_path / "cache")]
    )

    assert exit_code == scan_cli.EXIT_RUN_ABORTED
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "every page failed to fetch" in captured.err
    assert "2 failed" in captured.err


def test_dry_run_aborts_when_toc_has_no_content_pages(tmp_path, monkeypatch, capsys):
    def handler(request):
        return httpx.Response(200, json=TOC_NO_PAGES)

    monkeypatch.setattr(scan_cli, "build_http_client", lambda: _mock_client(handler))

    exit_code = scan_cli.run(
        ["--book", BOOK, "--dry-run", "--delay", "0", "--cache-dir", str(tmp_path / "cache")]
    )

    assert exit_code == scan_cli.EXIT_RUN_ABORTED
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no content pages" in captured.err


def test_default_model_is_the_same_for_both_commands():
    """The two entry points share a ledger format and a price table; differing defaults
    would silently key their ledgers apart and price the same book two ways."""
    from glossary_gen.cli import build_parser as gen_parser

    scan_default = build_parser().parse_args(["--book", BOOK]).model
    gen_default = gen_parser().parse_args(["--input", "x.json"]).model
    assert scan_default == gen_default == "gemini-3.7-flash"
