# Library discovery controls (unreleased modules)

These controls describe the local Module 02 implementation, following the Module 01
queue-policy work. They are not part of the previously published 0.4.14 image yet.
No live-server configuration changes or deployment are implied by these instructions.

## Request concurrency

`sync_request_workers` controls manager discovery request concurrency. Its default is
4; valid values are integers from 1 through 8. This is independent of speech inference:
Crowbarr still runs one inference child. Changing request concurrency does not change
processing or discovery fingerprints and does not reopen settled subtitle verdicts.

The existing authenticated settings API accepts, for example:

```http
PUT /api/settings
Content-Type: application/json

{"sync_request_workers": 4}
```

Use the authentication described in the main README. There is no dedicated browser
control for this setting in Module 02. Alternatively, edit the setting in settings.json
while the service is stopped; do not edit a running service's config file and assume it
will reload automatically. Old settings files without this property default to four.

Start with the default. Reduce to 1 or 2 if the manager is overloaded or produces rate
limits/timeouts. Raising it above four is optional and should follow measurement of the
actual manager/storage workload. It cannot exceed eight. Changes apply to subsequent
adapter instances/scans; an active adapter keeps its copied configuration.

Each client queues at most twice its worker count of unconsumed item futures. Requests
also have an explicit per-client concurrency limit, HTTP connection-pool limits, the
existing 20-second HTTPX timeout per I/O phase, redirects disabled, and environment
proxies disabled. This is not a guarantee of a 20-second total library scan.

## Retry and cancellation behavior

Only GET requests are retried. Transport failures and HTTP 429/502/503/504 receive at
most three total attempts. A valid Retry-After delta/date is clamped to 1–60 seconds;
otherwise delays are exponential (1 then 2 seconds) plus up to one second of jitter.
401/403, definitive item 404, other statuses, malformed JSON, and invalid resource shapes
are not converted into successful empty data or repeatedly retried.

The adapter accepts a cancellation event. It stops submission, retries, and result
yielding when cancellation is observed; cleanup joins its owned workers before closing
the HTTP client. In-flight network calls may finish or hit their normal I/O timeout.
Cancelling does not return a successful partial catalog. Server-wide scanner stop/run
recovery wiring is a later module; Module 02 adds the adapter mechanism only.

## Developer interfaces

`ArrClient.catalog()` remains a complete, sorted list of ManagedFile values. It returns
only after all items succeed; any failure aborts the replacement. Existing scan/database
publication and deletion semantics are unchanged in this module.

`catalog_item(item_id)` and `iter_catalog_items()` return CatalogItem values containing:

- `provider` and `item_id`.
- `discovery_fingerprint`: the caller-supplied full configuration fingerprint; None
  for an unbound standalone client. A coordinator must supply/compare it before using
  a snapshot for freshness or authorization. Never substitute a connection-only hash.
- `files`: a tuple of normalized ManagedFile values for this item.
- `outcome`: complete, including an authoritatively empty/unmonitored item, or removed
  for a targeted item lookup's 404. An exception has no successful outcome.

Full inventories use their fetched series/movie records without an extra detail request
for every item. Targeted lookups fetch current item truth. Sonarr associates episodes
by file ID once per series and preserves sorted/shared episode metadata. Webhook paths
and monitoring claims do not override the manager's response.

The item iterator can finish out of order and can yield good items before a later item
fails. A consumer implementing incremental persistence must stage/fence these results
under Module 04's contracts. It must not infer whole-catalog removals from a partial
iterator. Explicitly close an iterator when abandoning it; use ArrClient as a context
manager to close the owned pool/client even on exceptions.

## Metrics and measurement

An optional `progress` callback receives copied aggregate metrics: provider, logical
GET requests, HTTP attempts, completed/submitted items, pending futures, active requests,
and active items, plus their peaks. `adapter.metrics` returns the same kind of snapshot.
Counters cover that client's lifetime; completed means fetched/normalized, not applied
to the database. Pending includes completed futures not yet consumed by the iterator.
Callbacks must be quick observers; do not close the client or perform blocking work
inside them. A failing callback is disabled and logged once without its exception data.
Metrics contain no URLs, API keys, media paths, subtitle text, or raw responses.

The generated 100-series test makes 201 requests and reports latency for workers 1, 4,
and 8 with a simulated 5ms delay per GET. Deterministic barrier tests enforce actual
overlap, request/window limits, and parity. The reported timings are diagnostic, not a
wall-clock CI threshold or a claim about a real NAS. Module 07 owns end-to-end acceptance.
