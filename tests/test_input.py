import json

import pytest

from glossary_gen.input import InputError, load_input


def write(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_load_json_with_book_and_terms(tmp_path):
    payload = {
        "book": {
            "library": "eng",
            "coverID": "12345",
            "bookId": "python-openstax",
            "title": "Python Programming (OpenStax)",
            "index_url": "https://eng.libretexts.org/index",
        },
        "terms": [
            {
                "term": "Recursion",
                "aliases": ["recursive"],
                "pages": ["https://eng.libretexts.org/a"],
            },
            {"term": "Base case", "pages": ["https://eng.libretexts.org/b"]},
        ],
    }
    path = write(tmp_path, "in.json", json.dumps(payload))

    result = load_input(path)

    assert result.book is not None
    assert result.book.library == "eng"
    assert result.book.cover_id == "12345"
    assert [t.slug for t in result.terms] == ["recursion", "base-case"]
    assert result.terms[0].aliases == ("recursive",)
    assert result.terms[1].aliases == ()


def test_load_csv_has_no_book(tmp_path):
    path = write(
        tmp_path,
        "in.csv",
        (
            "term,aliases,pages\n"
            "Recursion,recursive|recursing,"
            "https://eng.libretexts.org/a|https://eng.libretexts.org/b\n"
        ),
    )

    result = load_input(path)

    assert result.book is None
    assert result.terms[0].aliases == ("recursive", "recursing")
    assert result.terms[0].pages == ("https://eng.libretexts.org/a", "https://eng.libretexts.org/b")


def test_term_without_pages_is_rejected_with_position(tmp_path):
    payload = {"terms": [{"term": "Recursion", "pages": []}]}
    path = write(tmp_path, "in.json", json.dumps(payload))

    with pytest.raises(InputError, match="term 1"):
        load_input(path)


def test_blank_term_is_rejected(tmp_path):
    path = write(tmp_path, "in.csv", "term,aliases,pages\n  ,,https://eng.libretexts.org/a\n")

    with pytest.raises(InputError, match="term 1"):
        load_input(path)


def test_duplicate_slugs_are_rejected(tmp_path):
    payload = {
        "terms": [
            {"term": "Base case", "pages": ["https://eng.libretexts.org/a"]},
            {"term": "base-case", "pages": ["https://eng.libretexts.org/b"]},
        ]
    }
    path = write(tmp_path, "in.json", json.dumps(payload))

    with pytest.raises(InputError, match="duplicate"):
        load_input(path)


def test_unknown_extension_is_rejected(tmp_path):
    path = write(tmp_path, "in.txt", "nope")

    with pytest.raises(InputError, match="unsupported"):
        load_input(path)
