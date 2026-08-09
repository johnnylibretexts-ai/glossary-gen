from glossary_gen.models import Block, Page
from glossary_gen.scan_cli import build_parser, structural_preview

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
    assert args.min_score == 0.0
    assert args.dry_run is False
