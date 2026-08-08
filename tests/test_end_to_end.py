import csv
import json

import httpx

from glossary_gen.cli import run

PAGE_HIT = """
<html><body>
<h2>Recursion</h2>
<p>Recursion is a technique where a function calls itself.</p>
</body></html>
"""
PAGE_MISS = "<html><body><p>Nothing relevant here at all.</p></body></html>"

REPLY = json.dumps(
    {
        "definition": "A technique where a function calls itself.",
        "category": "Functions and flow",
        "context": "Used for tree traversal in this book.",
        "example": "fact(n)",
        "related": ["Base case"],
        "aliases": ["recursive"],
    }
)


def test_full_run_writes_reviewable_csv(tmp_path, monkeypatch, capsys):
    payload = {
        "book": {
            "library": "eng",
            "coverID": "12345",
            "bookId": "python-openstax",
            "title": "Python Programming (OpenStax)",
            "index_url": "https://eng.libretexts.org/i",
        },
        "terms": [
            {"term": "Recursion", "pages": ["https://eng.libretexts.org/hit"]},
            {"term": "Ghost", "pages": ["https://eng.libretexts.org/miss"]},
            {"term": "Vanished", "pages": ["https://eng.libretexts.org/gone"]},
        ],
    }
    input_path = tmp_path / "in.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    def page_handler(request):
        url = str(request.url)
        if url.endswith("/hit"):
            return httpx.Response(200, text=PAGE_HIT)
        if url.endswith("/miss"):
            return httpx.Response(200, text=PAGE_MISS)
        return httpx.Response(404)

    def llm_handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": REPLY}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 30},
            },
        )

    # glossary_gen.llm.httpx is the *same* module object as the httpx imported here (Python
    # modules are singletons), so patching "glossary_gen.llm.httpx.Client" patches the
    # process-global httpx.Client. A replacement that itself calls `httpx.Client(...)` would
    # therefore call itself and recurse forever; capture the real class first and call that.
    real_client = httpx.Client
    monkeypatch.setenv("GLOSSARY_GEN_OPENAI_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.delenv("GLOSSARY_GEN_GEMINI_API_KEY", raising=False)
    # An operator's own exported GLOSSARY_GEN_OPENAI_MODEL/_API_KEY must not leak into a
    # test run and change client.model or send unexpected headers.
    monkeypatch.delenv("GLOSSARY_GEN_OPENAI_MODEL", raising=False)
    monkeypatch.delenv("GLOSSARY_GEN_OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        "glossary_gen.cli.build_http_client",
        lambda: real_client(transport=httpx.MockTransport(page_handler)),
    )
    monkeypatch.setattr(
        "glossary_gen.llm.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(llm_handler)),
    )

    out = tmp_path / "out.csv"
    exit_code = run(
        [
            "--input",
            str(input_path),
            "--out",
            str(out),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--ledger",
            str(tmp_path / "run.jsonl"),
            "--yes",
        ]
    )

    assert exit_code == 0
    with out.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 1
    row = rows[0]
    assert row["term"] == "Recursion"
    assert row["x_status"] == "needs-review"
    assert row["library"] == "eng"
    assert row["x_source_pages"] == "https://eng.libretexts.org/hit"
    assert "recursive" in row["aliases"]

    printed = capsys.readouterr().out
    assert "ok=1" in printed
    assert "no_excerpt=1" in printed
    assert "fetch_error=1" in printed


def test_second_run_is_free_and_reproduces_the_csv(tmp_path, monkeypatch, capsys):
    payload = {
        "book": {
            "library": "eng",
            "coverID": "1",
            "bookId": "b",
            "title": "T",
            "index_url": "https://i",
        },
        "terms": [{"term": "Recursion", "pages": ["https://eng.libretexts.org/hit"]}],
    }
    input_path = tmp_path / "in.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    llm_calls = []

    def llm_handler(request):
        llm_calls.append(1)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": REPLY}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 30},
            },
        )

    # See the comment in test_full_run_writes_reviewable_csv: glossary_gen.llm.httpx is the
    # same module object as httpx here, so the replacement must call the real class, not the
    # (about to be patched) name "httpx.Client" — else it recurses into itself forever.
    real_client = httpx.Client
    monkeypatch.setenv("GLOSSARY_GEN_OPENAI_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.delenv("GLOSSARY_GEN_GEMINI_API_KEY", raising=False)
    # An operator's own exported GLOSSARY_GEN_OPENAI_MODEL/_API_KEY must not leak into a
    # test run and change client.model or send unexpected headers.
    monkeypatch.delenv("GLOSSARY_GEN_OPENAI_MODEL", raising=False)
    monkeypatch.delenv("GLOSSARY_GEN_OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        "glossary_gen.cli.build_http_client",
        lambda: real_client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, text=PAGE_HIT))
        ),
    )
    monkeypatch.setattr(
        "glossary_gen.llm.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(llm_handler)),
    )

    argv = [
        "--input",
        str(input_path),
        "--out",
        str(tmp_path / "out.csv"),
        "--cache-dir",
        str(tmp_path / "cache"),
        "--ledger",
        str(tmp_path / "run.jsonl"),
        "--yes",
    ]

    assert run(argv) == 0
    assert len(llm_calls) == 1

    capsys.readouterr()
    assert run(argv) == 0
    assert len(llm_calls) == 1  # nothing regenerated
    assert "skipped=1" in capsys.readouterr().out
