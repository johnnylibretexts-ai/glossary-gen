"""Entry point for `python -m glossary_gen`.

Lets the tool run without the `glossary-gen` console script being on PATH,
which is the usual situation inside a fresh checkout or a CI container.
"""

from glossary_gen.cli import run

if __name__ == "__main__":
    raise SystemExit(run())
