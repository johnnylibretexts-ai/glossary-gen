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
a hint: a candidate whose evidence cannot be found on the page is refused outright, never merely
penalised. Refused is not the same as forgotten — the refusal is recorded — but being recorded
softens nothing about the gate.
_Avoid_: quote, proof, snippet, excerpt

**Rejected candidate**:
A candidate whose evidence failed the gate, kept as a record of what the model did. Not a term:
the book is not known to define it, and the span offered as proof may have been invented. This is
what separates it from an unwritten term, which the book does define and which a person is asked
to judge — a rejected candidate is never offered to anyone to rescue.
_Avoid_: unwritten (a different thing), failed term, dropped term, discarded term

**Confidence**:
A model's own stated certainty about a candidate, recorded exactly as given. Nothing adjusts it,
and it is never combined with anything else into a single figure.
_Avoid_: score, rating, certainty

**Corroboration**:
An independent signal from a page agreeing that a term is defined there — the term in a heading, a
definitional cue in its evidence, or the term appearing on more than one page. Each is recorded by
name and they are never fused into one number. A corroboration says the page defines the term; it
says nothing about whether the term belongs in a glossary, which depends on the book's audience and
is a human's judgement.
_Avoid_: score, weight, bonus, relevance, ranking

**Merge**:
Collapsing the same term proposed on several pages into one entry — unioning its pages and
aliases, and promoting its highest-scoring surface form.
_Avoid_: dedupe, collapse, consolidate

### Definition writing

**Excerpt**:
A passage chosen from a page because a definition can be grounded in it. Distinct from evidence:
evidence proves a term belongs in the index, an excerpt is the raw material for explaining it. A
passage too short to ground anything is not an excerpt — where a page yields too little, the term
has no excerpt and no definition is written, because what came back would be the model's knowledge
wearing the page's provenance.
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

### Review

**Reviewer**:
A person deciding, term by term, what leaves the CSV for the book's glossary. Not the book's
author, and not assumed to know its subject.
_Avoid_: editor, user, curator

**Unwritten**:
A term in the index that a run produced no definition for — its pages yielded too little to ground
one, would not fetch, or the model failed. Unwritten is not a verdict about the term: it records
that the tool wrote nothing, never that the term does not belong.
_Avoid_: skipped (already means resumed past), failed, dropped, missing

**Term fit**:
Whether a term belongs in this book's glossary at all, which depends on the book's audience.
Independent of how well its definition came out — a term can fit perfectly and be badly defined.
_Avoid_: relevance, importance, glossary-worthiness

**Definition soundness**:
Whether a generated definition is correct and stands on its own. Independent of whether the term
belongs — a definition can be flawless for a term that should not be in the glossary.
_Avoid_: quality, accuracy, correctness

**Verdict**:
What a reviewer decides about one term — keep, cut, or fix. Derived from term fit and definition
soundness rather than judged on its own: cut when the term does not fit, fix when it fits but its
definition is unsound.
_Avoid_: decision, disposition, outcome

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
