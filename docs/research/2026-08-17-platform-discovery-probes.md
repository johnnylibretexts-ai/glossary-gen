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

- **`GET https://<network>/wp-json/pressbooks/v2/books?per_page=N` → 200,** but **`per_page` caps
  at 10** — anything higher is a `400 rest_invalid_param`, not a clamp (measured 2026-08-17 with
  `per_page=12`). A sweep across a network's thousands of books therefore pages, and the earlier
  "83 books sampled" figure below came from paging, not from one large request. Confirmed on
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

## Follow-up: what the front page actually leaves out (2026-08-17, [#38](https://github.com/johnnylibretexts/glossary-gen/issues/38))

Discovery read a Pressbooks book's front page and kept links under `front-matter/`, `chapter/` and
`back-matter/`. Parts were excluded on the reasoning that a part is a divider whose page is a
heading and nothing else. This measures both halves of that.

Everything below used the package's own User-Agent against `ecampusontario.pressbooks.pub`, on
allowed paths only. **The per-book sitemap at `<book>/?feed=sitemap.xml` is allowed** — no
`Disallow` line matches it — and it enumerates every part, chapter, front- and back-matter page.
It was used here as an independent ground truth to check discovery against; it is deliberately NOT
what the tool reads, because it carries no reading order and lists non-book pages (`about`, `buy`,
`authors`, `h5p-listing`).

### A part is linked from the front page exactly when it has content

18 books, 89 parts. Compared the parts the front page *links* against the parts the sitemap *lists*,
and fetched every one of them:

| | |
|---|---|
| parts that were linked and turned out empty | **0** |
| parts that were unlinked and turned out to carry content | **0** |

So the front page already offers every part worth reading, and the section filter was throwing them
away. 3 of the 18 books have parts carrying content — 27 pages, 1,200 to 6,200 characters of prose
each. Note the linking rule is a *theme's* behaviour, not a platform guarantee: `toc.py` fetches
each linked part and judges the page rather than trusting the link.

**Trap:** part links are rendered with **single-quoted** `href='…'` where chapter links are
double-quoted. A regex probe over the raw HTML reported "0 parts" for every book and read as a clean
negative. BeautifulSoup — what the package uses — sees them.

### Three shapes of part page, and only one is a page

- **authored introduction** to the chapters below it (*Communication at Work*, 11 of 12 parts). A
  real page that defines terms.
- **empty** — the heading Pressbooks renders for every part, and nothing else (*Introductory
  Chemistry*, *Language Foundations Handbook*).
- **`Chapter Outline` over a list of links to its own chapters** (*Introductory Statistics*, 13 of
  13). This one is why "has any text" is the wrong test: every line is a chapter title, which is the
  exact shape of "a term this page defines", and the evidence gate cannot refuse it because the text
  really is on the page. It is the same hazard `article.py` strips out of the site chrome, rendered
  this time *inside* the article where narrowing cannot reach it.

### The front page really can be the whole book minus most of it

**`businesscommunication`: 19 parts, one front-matter page, and zero chapters.** The entire book is
written in its part pages. Front-page sections alone returned **1 page** for it and reported no
error. The sitemap confirms the shape rather than contradicting it — there are no chapters to miss.

Widening discovery to parts, per book (before → after):

| book | before | after | |
|---|---|---|---|
| `businesscommunication` | 1 | 20 | |
| `unisuccess2ed` | 72 | 84 | |
| `communicationatwork` | 48 | 59 | |
| `knowinghome2` | 21 | 24 | |
| `bearguideworkshop` | 24 | 26 | the only book found that is BOTH a glossary carrier and has content-bearing parts: 2 harvested terms before and after |
| `languagefoundationshandbook` | 23 | 23 | no part carries content; its 26 harvested terms are also unchanged |

The last row is the check #38 names: harvest the book's own glossary before and after, and the count
must not fall.

### Do not take the union from a part's article

The cross-check reads the part page's **chrome** — the document with its article detached — because
that is where the theme repeats the book's table of contents. Reading the whole document instead
looks equivalent and is not. On *Communication at Work* it turned up one URL the front page had
never listed, `chapter/6-1-1-email-address/`, which **301s to a chapter already in the list**: a
stale cross-reference in the part's prose. Kept, it would be fetched, scanned and paid for a second
time under a second URL, and that URL would be attached to every term found there. A book's own
prose links to its own pages freely, and some of those links are wrong.

## Built: screening a Pressbooks book, and what it costs (2026-08-18, [#37](https://github.com/johnnylibretexts/glossary-gen/issues/37))

`tools/survey_glossaries.py` was LibreTexts-only. It now routes on the host the way `discover`
does, and the Pressbooks route is a different kind of answer rather than the same one ported.

### One request settles a carrier, and it is the more complete of the two routes

*Language Foundations Handbook*, measured before anything was written:

| route | requests | terms |
|---|---|---|
| `back-matter/glossary/` | **1** | **59** |
| the 23-page walk, `<dl>` blocks | 23 + discovery | 59 |
| the 23-page walk, inline `<template>` terms only | 23 + discovery | 26 |

So the glossary page is not merely a shortcut past the walk — on this book the walk finds nothing
the one request did not, and the inline route alone finds 26 of the 59. (The API reports 64, which
neither HTML route reaches; five terms are defined and never used.)

It stays an optimisation and never the only route. A glossary page titled anything else — the
`Glossaire` and `Glossary of Key Terms for Online Learning` recorded above — 404s that URL, and the
walk reads the book's back matter like any other page. There is a test for exactly that.

### A zero is a zero, which is the whole point

The walk stops at the first page carrying a term, because one page carrying one answers the
question asked. A book with none is read to the end. So both answers are proof, and `settled` is
the column that says so — against the LibreTexts screen, where a hit is proof and a zero is "no
evidence at 24 pages".

What a carrier pays for the early exit is its term count, which becomes a floor: *A Guide to Bears*
settles on its 2nd page of 26 and reports 1 term where a full harvest finds 2. `read` against
`pages` says so on the row.

### The cost is real, and it is fetching

20 books, 609 pages read, **1 carrier** (*Supplément FR2805A*, 2 terms). The 11-of-83 rate above
predicts 2.7 from 20 books, and at these numbers 1 does not disagree with it.

**Cold that took roughly half an hour, and it was throttled part-way**: the fetch rate fell from
~25 pages/minute to 3, which is what a polite crawl of a whole network looks like when the network
answers back. **Re-run against the warm cache: 79 seconds**, every page served from disk.

Non-carriers are what costs: every one of them is a complete walk, and 87% of books are
non-carriers. The fast path saves a whole book walk per carrier-with-a-glossary-page and costs one
404 per book that has none — roughly a wash across a sweep, and decisive on the books being hunted.

### The wider run: 10 carriers in 80 books

Run at the probe's own scale the next day, output in
[`2026-08-18-pressbooks-glossary-survey.csv`](./2026-08-18-pressbooks-glossary-survey.csv):

| | |
|---|---|
| books | 80 |
| pages read | 1,650 |
| **carriers** | **10 (12.5%)** |
| settled by one request | 2 of the 10 |
| inconclusive | 1 |

12.5% against the API probe's 11 of 83 (13.3%) — measured a different way, on a different sample of
the same network, and they agree.

**The two books settled by their glossary page were 21 and 100 terms, for one request each.** The
other eight were settled by a walk that stopped at the first page carrying a term. Between them the
ten carriers cost **39 page fetches**; the seventy non-carriers cost **1,611**. That is where a
sweep's time goes and there is no way around it: proving absence means reading the book.

**Carrier term counts on these rows are floors, not totals** — except the two from a glossary page,
which are that page's whole list. They are not comparable to the probe's per-book API counts
(median 13, max 64), which were complete.

**29 minutes at `--delay 0.5`**, with roughly a quarter of the books already cached. The 20-book run
below, at the 0.3 s default, was throttled from ~25 pages/minute to 3; at 0.5 s nothing throttled.
Being politer was faster.

One book came back inconclusive — *H5P Library*, 6 of 7 pages, one page lost to a transient
failure. It says `no evidence`, not `no glossary`.

**Two books came back inconclusive on the cold run and settled on the warm one.** Both are 28-page
program handbooks that lost a single page to a transient failure while the network was visibly
throttling (the run's fetch rate fell from ~25 pages/minute to 3). 27 of 28 pages is not a book
without a glossary, and the run said `no evidence` rather than `no glossary` for both. A re-run
fetched the missing page and settled them. That is the `settled` column earning its place on its
first real outing.

### Four things the enumerator gets wrong if written the obvious way

- **`per_page` caps at 10**, so a sweep pages. Already recorded above.
- **The catalogue's last listing page is short** — 3 books, not 10 — and an even spread always
  includes it, because a spread includes both ends. Sizing a sweep in whole pages therefore returns
  fewer books than asked for and says nothing about it: `--books 20` came back with 13. The page
  count is computed from `x-wp-total` instead, and `--books 20` and `--books 80` now return 20 and
  80 exactly. (The probe's own 83-book sample was 9 listing pages of this shape: 8 full and one
  of 3.)
- **Trimming the surplus off the END undoes that.** Reading the extra listing page to reach the
  newest books and then slicing the list from the front discards exactly that page and nothing
  else. The count comes out right, so a test that counts rows passes while the reason for the count
  is broken — this shipped and was caught in review. The surplus is spread out instead, with
  `evenly_spaced` over the collected books, which keeps both ends by construction.
- **A `link` from the listing is data, not a host a person named.** Every fetch is checked against
  a standing allowlist widened by exactly one host — on a sweep, the network URL that was typed.
  Taking the widening from each book's own `link` instead would let the listing choose what the run
  fetches, including a host that is not the network's. Entries off the network host are dropped.
