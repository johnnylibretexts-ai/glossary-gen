"""Screening books for an author glossary before spending anything on them."""

from glossary_gen.scan.survey import evenly_spaced, shelf_books, survey_pages

GLOSSARY_OF = "<h2>Glossary</h2><dl><dt>%s</dt><dd>%s</dd></dl>"


def test_a_sample_spans_the_whole_book():
    """Glossary blocks sit in chapters, not front matter. A sample taken off the top
    would screen a book on its title page and licensing notice.

    The properties are asserted rather than one exact list of indices: which side of
    a half-step a middle item lands on is arbitrary, and pinning it would make a
    harmless rounding change look like a regression.
    """
    pages = list(range(100))

    sample = evenly_spaced(pages, 5)

    assert len(sample) == 5
    assert (sample[0], sample[-1]) == (0, 99)
    assert sample == sorted(set(sample))
    gaps = [b - a for a, b in zip(sample, sample[1:], strict=False)]
    assert max(gaps) - min(gaps) <= 1


def test_a_sample_larger_than_the_book_is_the_whole_book():
    assert evenly_spaced(["a", "b"], 10) == ["a", "b"]


def test_an_empty_book_samples_to_nothing():
    assert evenly_spaced([], 5) == []


def test_shelf_books_are_the_shelf_s_immediate_children():
    root = {
        "title": "Introductory Statistics",
        "url": "https://stats.libretexts.org/Bookshelves/Introductory_Statistics",
        "subpages": [
            {"title": "Introductory Statistics 1e (OpenStax)", "url": "https://x/1e"},
            {"title": "OpenIntro Statistics", "url": "https://x/openintro"},
        ],
    }

    assert shelf_books(root) == [
        ("Introductory Statistics 1e (OpenStax)", "https://x/1e"),
        ("OpenIntro Statistics", "https://x/openintro"),
    ]


def test_a_shelf_child_without_a_url_is_skipped():
    root = {"subpages": [{"title": "Broken"}, {"title": "Fine", "url": "https://x/fine"}]}

    assert shelf_books(root) == [("Fine", "https://x/fine")]


def test_survey_counts_pages_carrying_a_glossary_not_pages_fetched():
    pages = [
        ("https://x/1", GLOSSARY_OF % ("Average", "a central tendency")),
        ("https://x/2", "<h2>Chapter Summary</h2><p>nothing here</p>"),
        ("https://x/3", GLOSSARY_OF % ("Median", "the middle value")),
    ]

    result = survey_pages(pages)

    assert (result.sampled, result.with_glossary, result.terms) == (3, 2, 2)


def test_survey_counts_a_term_once_across_pages():
    pages = [
        ("https://x/1", GLOSSARY_OF % ("Average", "a central tendency")),
        ("https://x/9", GLOSSARY_OF % ("Average", "restated later")),
    ]

    assert survey_pages(pages).terms == 1
