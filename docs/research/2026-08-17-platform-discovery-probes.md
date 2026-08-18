# Probes: a full LibreTexts catalogue walk, and Pressbooks as a second platform

Two questions were probed on 2026-08-17 and neither is built yet. This records what the probes
returned so the next attempt starts from evidence rather than repeating them.

Context: [the glossary survey](./2026-08-17-glossary-survey.md) screened 77 books from six shelves
and found 9 carriers. Both probes below exist to widen that — one across all of LibreTexts, one
onto a different platform entirely.

## 1. Telling a book from a shelf, for a full-catalogue walk

`tools/survey_glossaries.py` takes shelf URLs by hand. A catalogue-wide sweep needs to walk
`https://<library>.libretexts.org/Bookshelves` recursively and decide, at each node, whether it is
a shelf (recurse), a book (survey), or a chapter (stop). Some shelves nest — `eng` has
`Computer_Science/Programming_Languages` — so depth is not a reliable signal.

**The `properties` block distinguishes them.** Probed on `bio`:

| node | carries the property |
|---|---|
| shelf (`Introductory_and_General_Biology`) | `mindtouch.idf#subpageListing` |
| book (`Concepts_in_Biology_(OpenStax)`) | `mindtouch.page#overview` |
| chapter (a book's child) | `mindtouch.page#welcomeHidden` |

`getTOC` already returns `properties` on every node, so this costs no extra request. **Validate it
across libraries before relying on it** — it was checked on one library and three nodes, and a
book without an overview property would be silently skipped by a walk keyed to it. A cheaper
fallback exists if it does not hold: a book's `path` sits directly under a shelf and its children
are numbered chapters.

Scale: ~13 libraries, dozens of shelves, and the survey fetches ~1 page/second. A full sweep at 24
pages per book is hours of fetching and **no** model spend. Run it in the background, cached, and
resumable.

## 2. Pressbooks — the API is disallowed, the same content is not

Pressbooks is a different platform with a **native glossary feature**: terms are a first-class post
type rather than markup to be scraped, which would remove the `<dl>`-under-a-heading heuristic and
the "a zero is only weak evidence" caveat that sampling forces on the LibreTexts survey.

The first probe found the enumerator:

- **`GET https://<network>/wp-json/pressbooks/v2/books?per_page=N` → 200.** Confirmed on
  `ecampusontario.pressbooks.pub`: a JSON list, each entry carrying `id`, `link`, and a
  schema.org `metadata` block (`name`, `alternativeHeadline`, `inLanguage`, `copyrightYear`,
  `image`). This is the enumerator — it replaces both shelf-walking and guesswork.
- **Per-book paths must come from that listing's `link`.** A guessed slug
  (`/hospitalityfinancialaccounting/wp-json/pressbooks/v2/toc`) returned **404**; the listing
  returns real ones (e.g. `/northern/`).

The second probe (2026-08-17, same day) went after the glossary endpoint itself. Everything below
is measured, not inferred.

### The glossary endpoint exists, and it is exact

`GET <book>/wp-json/pressbooks/v2` returns a route index — 42 routes, and **`glossary`,
`glossary-type`, `glossary/<id>` and `glossary/<id>/metadata` are all among them**. Glossary is a
WordPress post type with its own taxonomy, exactly as hoped. (`glossary-types`, plural, is a 404;
the route is singular.)

**`?per_page=1` returns an `x-wp-total` header carrying the exact term count.** That is the whole
carrier test, in one request:

| | LibreTexts survey | Pressbooks |
|---|---|---|
| requests per book | ~24 sampled pages | **1** |
| result | "no evidence at 24 pages" | **exact count** |
| detection | `<dl>` under a heading | first-class post type |
| the "a zero is weak evidence" caveat | load-bearing | **gone** |

That caveat is what forced the survey to report a carrier rate "at or above 12%" rather than a
number. Here the number is a number.

### Measured carrier rate: 11 of 83, and the payload is directly usable

83 books sampled evenly across the network's 3,033 (listing pages 1, 40, 80 … 304, so the estimate
is not biased toward the oldest books, which predate the glossary feature). **Zero errors.**

| | |
|---|---|
| carriers | **11 / 83 (13%)** |
| terms per carrier | min 1, median 13, max 64 |
| total terms harvested from the sample | 195 |

Densest: *Language Foundations Handbook* (64), *Universal Design for Learning* (31), *International
Students: Stories and Strategies* (26). 13% against the LibreTexts survey's "≥12%" is a near-match —
but this one is a measurement and that one is a floor.

A term is a reference set already: `title.raw` is the surface form, `content.raw` is the authors'
definition, and `status` says `publish`.

```json
{ "id": 94, "slug": "affix", "status": "publish", "type": "glossary",
  "title":   { "raw": "affix" },
  "content": { "raw": "A morpheme attached to the beginning or end of a base to modify its
                       meaning. Affixes are bound morphemes; they cannot stand alone…",
               "protected": false } }
```

`glossary/<id>/metadata` adds schema.org: `isPartOf` (the book), named `author` contributors, and
`isBasedOn` — a pointer at the book this one was cloned from, which is free provenance the
LibreTexts side has no equivalent of.

**The generation side works too, not just harvesting.** `toc` returns parts → chapters with `id`,
`title`, `slug` and `word_count`; `chapters?per_page=1` returns `x-wp-total` (chapter count) and
full `content.rendered` (9,573 chars on the first chapter tried, `protected: false`, no auth). So a
book without a glossary could be indexed and scanned, which is the tool's actual job.

### The blocker is a permission question, not an allowlist entry

This is the finding that outranks the rest, and it moved in the wrong direction between the two
probes.

**1. Pressbooks' default `robots.txt` disallows the entire per-book API.**

```
User-agent: *
Disallow: /*/wp-json/
```

Byte-identical on `ecampusontario.pressbooks.pub` and `openpress.usask.ca` — two independent
installs, so this is the platform default, not one operator's config. The pattern requires a path
segment before `wp-json`, which splits the API cleanly in two:

| path | matched by `/*/wp-json/`? | |
|---|---|---|
| `/wp-json/pressbooks/v2/books` | no | the enumerator is **allowed** |
| `/<book>/wp-json/pressbooks/v2/glossary` | yes | **disallowed** |
| `/<book>/wp-json/pressbooks/v2/{toc,metadata,chapters}` | yes | **disallowed** |

Everything measured above sits on the disallowed side of that line.

**2. `pressbooks.pub` and `opentextbc.ca` refuse AI crawlers by name.** Both are Cloudflare-fronted,
both 403 every request including with a browser User-Agent, and their `robots.txt` carries an
explicit reservation of rights:

```
User-agent: *
Content-Signal: search=yes,ai-train=no,use=reference
…
User-agent: ClaudeBot     Disallow: /
User-agent: GPTBot        Disallow: /
User-agent: CCBot         Disallow: /
User-agent: Google-Extended   Disallow: /
```

with a header citing Article 4 of EU Directive 2019/790. `ai-train=no` is unambiguous. `use=reference`
is the operator permitting reference but not wholesale ingestion — arguably the exact shape of a
glossary comparison, and equally arguably not. That reading is the owner's call to make, not a
detail to settle in code.

**3. The 403s in probe 1 were partly User-Agent filtering, and getting past it is a choice.**
CloudFront in front of `ecampusontario` returns 403 to httpx's default UA *and* to a descriptive
`glossary-gen probe (…)` string, and 200 to a browser-shaped one. The second probe used a browser UA
to proceed. That is worth an explicit decision rather than becoming a habit — the package's fetcher
currently sends no custom UA at all, so it would be 403'd on this network as written. `opentextbc.ca`
403s a browser UA too; that one is Cloudflare and a different refusal.

**So the original framing was too small.** `fetch.is_allowed_url` refuses any host that is not
`*.libretexts.org`, and that guard is why this tool cannot wander the open web. Adding a second
allowlist entry is still the right *mechanism* — never remove the guard — but it is not the whole
question. The rest of it is whether to fetch endpoints an operator has disallowed for all agents, on
a platform of thousands of independent installs where each operator's answer may differ.

Both probes deliberately used bare `httpx` calls in scratch scripts rather than the package's fetch
path, and nothing was cached into the repo. **Probe 2 did fetch roughly 100 disallowed `/*/wp-json/`
URLs** to produce the measurements above — low volume, nothing retained, and recorded here rather
than left for someone to discover.

### Correction: the content is reachable on allowed paths, so this is not a blocker

Probed the same day, after the above was written. **It revises the conclusion, not the evidence** —
every robots.txt finding above still stands. What changed is that the disallowed API turns out not
to be the only way in.

Pressbooks renders each inline term *and its definition* into the served HTML of the chapter that
uses it:

```html
<a class="glossary-term" href="#term_27_447">welcome booth</a>
<template id="term_27_447">
  <div class="glossary__definition"><p>A kiosk setup at the airport to welcome arriving
  international students…</p></div>
</template>
```

`/<book>/chapter/<slug>/` is not matched by any `Disallow` line. Measured across the 11 carriers:

| route | robots | books reached |
|---|---|---|
| a `<dl>` on a glossary back-matter page | allowed | 4 / 11 |
| `<template>` blocks in chapter HTML | allowed | 5 of the remaining 7 |
| **combined** | **allowed** | **9 / 11** |

The two stragglers are one-term books, and one was truncated at 30 of its 80 pages, so the real
figure is probably better.

`/back-matter/glossary/` on its own is **not** the answer — it 404s on 7 of 11, and walking the
book's table of contents to find a differently-titled page (`Glossaire`, `Glossary of Key Terms for
Online Learning`) does not help: those pages exist but render no terms into their HTML.

**Dedupe by the term id, and the match is exact.** The anchor href encodes it as
`term_<page-id>_<term-id>`. On *Croissance et objectifs*: 44 distinct hrefs (one per occurrence), 30
distinct surface forms — plurals and inflections pointing at one term — and **19 distinct term ids,
against the API's 19.** *Canadian Press Writing Style* matched 13/13. A harvester keyed to surface
forms would have over-reported that book by 58% and looked like it was working.

**One trap, and it fails silently.** BeautifulSoup wraps `<template>` contents in `TemplateString`,
which `get_text()` skips by default: it returns `''` with no error while `str(node)` plainly shows
the text. The first run of this probe reported **0 terms across all 7 books** and read as a clean
negative result. Extract with `BeautifulSoup(block.decode_contents(), "html.parser")` instead, and
give anything built here a test that would catch it — otherwise it reports "no glossary" forever.

What the HTML route costs against the API: **N requests per book instead of 1**, since the
`x-wp-total` carrier test is gone and every page must be fetched. The declared sitemap does not
rescue it — the per-book sitemap lists a single glossary URL and does not enumerate terms.

What it gains, and the API cannot give: **which page each term appears on** — the index format this
tool consumes as input, free as a side effect of the harvest.

**So the revised position:** asking eCampusOntario for API access is still worth doing, but it is an
optimisation now, not the unblock. Nothing here requires fetching a disallowed path.
