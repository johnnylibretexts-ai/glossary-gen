# Backoff belongs to the transport

Three layers retry a model that did not answer, and only the lowest one sleeps.

A **request** — one round trip to a provider — is retried with a delay when the provider refused it
with a retryable status. That is the transport's own concern, and it lives in `RetryingClient`,
which wraps a single client and knows nothing about terms, pages, or the ledger. Above it,
`ProviderChain` moves to the next provider when a client has given up, and above that
`generate_entry` and `propose_candidates` retry a reply that arrived but did not parse. Neither of
those two sleeps, and neither should be made to.

The distinction is what the failure means. A retryable status is a server telling us *when* to come
back — often literally, in a `Retry-After` header or a `RetryInfo` block — so waiting is the
correct and only response. A reply that fails schema validation is not a server asking for time; it
is a model that produced the wrong shape, and the same request a second later is as likely to work
as the same request a minute later. Sleeping there buys nothing and spends the run's wall clock.

## Considered options

**Backoff in the retry loops above.** Rejected, though not because of the request count: the loops
nest either way. `generate_entry` tries three times and each try enters a fresh transport retry, so
one term can cost nine requests to one provider under *any* of these options. What this option adds
is *sleeping* in the outer loop — a delay paid for a failure that has nothing to do with timing,
on top of the delays paid for failures that do. The accepted arrangement already carries a worst
case of six waits, roughly six minutes per provider at the 60s cap and double that with a fallback
configured; making the outer loop sleep too would be paying twice for the same congestion.

**Backoff in `ProviderChain`.** Rejected because the chain's question is *which provider*, not *how
patiently*. Retrying there would put the policy in the same class as the `name`/`model` properties
the ledger keys on, and would apply one schedule to providers whose refusals mean different things
— a quota on a metered API, and a self-hosted endpoint that does not rate-limit at all.

**Backoff inside each client.** Rejected as duplication with no boundary to hold it: the loop would
be written once per provider, and the README's provider contract would silently grow a fourth
obligation that only the existing clients demonstrate.

## Consequences

`RetryingClient` composes rather than inherits, so a new provider gets the policy by being wrapped
in `build_client` and needs no knowledge of it. The retry decision is expressed once, as the type
`LLMRetryableError`; `ProviderChain` still catches `LLMTransportError` and its fall-through is
unchanged, because a retryable error is one.

The sleep and the reporting function are injected, which is what keeps the schedule assertable in
tests that take no time and print nothing. A test names the waits it expects; it does not perform
them.

A provider that refuses without a hint gets brief patience — roughly twelve seconds across the two
waits of one request sequence — and not a full quota window. Buying a 60-second window blind would cost every genuinely
broken run five times that in dead waiting before the failure counter stops it. When the hint is
absent and the window is a minute, the subject fails, the ledger records it, and the resume is
free. That is a deliberate hole, and the README states it rather than implying the case is covered.

A hint longer than the cap is not waited out. It is treated as evidence the quota is not coming
back within this run, and the subject fails immediately so the failure counter can end the run
instead of the tool appearing to hang for hours.
