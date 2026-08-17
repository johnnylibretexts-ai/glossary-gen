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

## 2. Pressbooks — the API works, but only from the network endpoint

Pressbooks is a different platform with a **native glossary feature**: terms are a first-class post
type rather than markup to be scraped, which would remove the `<dl>`-under-a-heading heuristic and
the "a zero is only weak evidence" caveat that sampling forces on the LibreTexts survey.

What the probe found:

- **`GET https://<network>/wp-json/pressbooks/v2/books?per_page=N` → 200.** Confirmed on
  `ecampusontario.pressbooks.pub`: a JSON list, each entry carrying `id`, `link`, and a
  schema.org `metadata` block (`name`, `alternativeHeadline`, `inLanguage`, `copyrightYear`,
  `image`). This is the enumerator — it replaces both shelf-walking and guesswork.
- **Per-book paths must come from that listing's `link`.** A guessed slug
  (`/hospitalityfinancialaccounting/wp-json/pressbooks/v2/toc`) returned **404**; the listing
  returns real ones (e.g. `/northern/`).
- **`opentextbc.ca` returned 403 to every request**, including with a browser User-Agent. Some
  installs sit behind a WAF, so a Pressbooks sweep must treat 403 as "this install declines", not
  as a bug to work around.

**Not yet probed:** the per-book `toc`, `metadata` and — the one that matters — the glossary
endpoint, on a link taken from the network listing. Do that before designing anything.

### The blocker that is a decision, not a task

`fetch.is_allowed_url` refuses any host that is not `*.libretexts.org`, and that guard is why this
tool cannot wander the open web. Pressbooks support means **adding a second explicit allowlist
entry, never removing the guard** — and Pressbooks is thousands of independent installs rather than
one host, so "which hosts" is a real question with a real answer needed from the owner. The
`pressbooks.pub` network is one host; a self-hosted institutional install is another.

Until that is decided, the probe above deliberately used a bare `httpx` call in a scratch script
rather than the package's fetch path.
