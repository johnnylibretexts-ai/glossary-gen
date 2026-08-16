# glossary-gen

Turns a LibreTexts book into reviewable glossary definitions. Two commands share one domain:
`glossary-scan` discovers which terms a book defines, and `glossary-gen` writes a definition for
each. Every model call costs money, so both are built around never paying twice for the same work.

## Language

### The book

**Book**:
A LibreTexts title, identified by its library, cover and book identifiers.
_Avoid_: text, textbook, publication

**Page**:
One addressable document within a book, identified by its URL.
_Avoid_: section, chapter, node

**Article**:
The authored body of a page, with the site's navigation, display controls and footer removed. A
page whose article is empty — front and back matter such as Index or Licensing — defines no terms.
_Avoid_: content, body, main

### Terms

**Term**:
A concept the book defines. Its identity is its slug, not its spelling.
_Avoid_: keyword, entry, concept

**Surface form**:
The exact spelling of a term as it appears on a page. One term may be seen in several.
_Avoid_: name, label, variant

**Alias**:
A surface form of a term other than the one chosen to represent it. Every observed spelling is
kept as an alias so nothing seen is lost.
_Avoid_: synonym, alternate name

**Slug**:
The normalised identifier derived from a surface form. Two surface forms that slug alike are the
same term; singular and plural deliberately do not.
_Avoid_: key, id, normalised term

**Index**:
Every term a book defines, each with the pages it appears on. The handoff between the two
commands, and the only shape either will accept.
_Avoid_: term list, keyword list, manifest

### Discovery

**Candidate**:
A term a model claims a page defines, before anything has checked the claim.
_Avoid_: proposal, suggestion, hit

**Evidence**:
The span a model copied verbatim from a page to prove its candidate is defined there. A gate, not
a hint: a candidate whose evidence cannot be found on the page is discarded outright, never merely
penalised.
_Avoid_: quote, proof, snippet, excerpt

**Confidence**:
A model's own stated certainty about a candidate. Only ever an input to a score.
_Avoid_: score

**Score**:
A candidate's confidence after corroboration by independent signals from the page. It ranks terms
for the human reviewing them; it never decides whether a term survives.
_Avoid_: rating, weight, relevance, confidence

**Merge**:
Collapsing the same term proposed on several pages into one entry — unioning its pages and
aliases, and promoting its highest-scoring surface form.
_Avoid_: dedupe, collapse, consolidate

### Definition writing

**Excerpt**:
A passage chosen from a page because a definition can be grounded in it. Distinct from evidence:
evidence proves a term belongs in the index, an excerpt is the raw material for explaining it.
_Avoid_: context, evidence, passage, chunk

**Definition**:
The generated explanatory text for one term — the artifact the whole tool exists to produce.
Always unreviewed.
_Avoid_: description, explanation, gloss

**Occurrence pages**:
Every page a term appears on, as claimed by the index.
_Avoid_: pages (unqualified, when source pages are also in play)

**Source pages**:
The pages an excerpt was actually drawn from when writing a definition — always a subset of the
occurrence pages. Conflating the two attributes a definition to pages nothing read.
_Avoid_: origin pages, cited pages

### Spend and resumption

**Run**:
One pass over a list of subjects, paying for each that is not already done. A run stops early if
its spend ceiling is crossed or the model fails repeatedly; a later run resumes it from the ledger.
_Avoid_: job, batch, session, invocation

**Subject**:
The thing one paid model call is made about — a term when writing definitions, a page when
discovering them. What the ledger is keyed on.
_Avoid_: item, target, unit, slug

**Attempt**:
One recorded try at producing a result for a subject, successful or not. A subject may accumulate
several; the failures are deliberate history, not noise.
_Avoid_: record, row, entry

**Request**:
One round trip to a provider. Several may go into a single attempt — a refused request is retried
without anything being recorded, and only a request that came back with a reply was billed. The
ledger never sees requests individually.
_Avoid_: call, attempt, try

**Ledger**:
The append-only record of every attempt. What makes a run resumable, and what stops a second run
paying for work the first already finished.
_Avoid_: log, cache, journal, history

**Done**:
A subject has a successful attempt for the current prompt and model. A failed attempt is history,
not completion — it is retried on the next run, never skipped.
_Avoid_: complete, finished, cached
