# 02 — Sonarr fetch efficiency

## Goal and boundary

Overlap bounded manager request waits and eliminate repeated episode-list scans.
Do not change database sync publication or deletion semantics yet. Module 01 must pass.

**Read:** `crowbarr/arr.py`: all `ArrClient` methods, `_remote_path()`, `map_path()`;
`Settings` and `discovery_fingerprint()` in `config.py`; `scan_arr()` in `library.py`.
**Allowed:** `arr.py`, `config.py`, and only compatibility changes in `library.py`.
**Tests:** `tests/test_arr.py`; NEW `tests/test_arr_concurrency.py`.

## Tasks

- [x] **02.1 — Make episode association linear.** Group episode resources by
  `episodeFileId` once per series. Pass the group into `_file()` rather than filtering
  every episode for each video. Preserve episode sorting, merged titles, season,
  monitored-only checks, language normalization, and multi-episode deduplication.
  Test 1,000 files with several episodes each using iteration/lookup counts; require
  linear grouping work and exact equivalence with existing fixture output.

- [x] **02.2 — Extract complete per-item fetching.** Add `catalog_item(item_id)` and
  `iter_catalog_items()` from the shared contract. An item fetch validates the current
  series/movie record and retrieves all file/episode information needed for monitoring.
  Keep `catalog()` returning its existing list; initially it collects the iterator.
  Reuse the same item normalization from `event_files()` while retaining its file-ID
  filter. Test monitored-to-unmonitored transitions, valid empty items, definitive
  missing items, missing metadata, and transport failures as distinct outcomes.
  The full iterator may use its fresh series inventory payload; avoid adding an extra
  series-detail request per item solely for refactoring. Targeted candidate validation
  must fetch current item truth. Test request counts for both paths separately.

- [x] **02.3 — Add a bounded request pool.** Introduce validated
  `sync_request_workers` (default 4, range 1–8), excluded from processing fingerprints.
  Bound active requests and queued futures: submit at most twice the worker count of
  items, consume completed items, then replenish. Do not submit thousands of futures
  at once. Own/close HTTP clients deterministically; never share a mutable Settings
  instance across workers. Preserve `trust_env=False`, authentication, timeouts, and
  redirect refusal. Test peak active requests and client closure after failure/cancel.

- [x] **02.4 — Bound retries and cancellation.** Retry only GET transport errors and
  429/502/503/504, at most three total attempts. Respect a valid Retry-After within a
  1–60 second bound; otherwise exponential backoff with injectable jitter/clock.
  Do not retry 401/403, definitive 404, malformed JSON, or invalid resource shapes as
  success. Cancellation stops submission and prevents application of canceled results;
  an in-flight request may take its existing bounded timeout to return. Unit tests use
  fake wait functions and never sleep through real retry delays.

- [x] **02.5 — Preserve determinism and report counters.** The iterator may complete
  items out of order; `catalog()` sorts by stable provider/item/file identity to retain
  deterministic tests and downstream processing. Add request/attempt/completed-item
  counters through an optional callback, without exposing API keys or full URLs.
  No newer/bulk endpoint is allowed unless the deployed v3 schema supports it and a
  fallback is tested. Add settings round-trip/default/migration tests.

## Tests and acceptance

Run Arr, library, settings/API, and restart suites plus new concurrency tests; then
the standard exit gate. Exercise workers=1, 4, and 8 with deterministic MockTransport
barriers rather than timing guesses.

- Peak active requests never exceeds the configured bound; queued work is bounded.
- Serial and concurrent modes return the same complete catalog and decisions.
- Injected 401/429/503, timeout, cancellation, and parse errors do not create a partial
  successful full catalog or infer removals. The compatibility collector fails closed
  on any failed item until Module 04 provides staged run semantics.
- A timed fake transport demonstrates overlap; CI's pass/fail is based on counters,
  barriers, and completeness, not an assumed production speedup.
- `_file()` association work is linear; no per-file search of the full episode list.
- Unchanged scan concurrency settings do not reopen settled processing results.

**Exit artifact:** sanitized request counts and a comparison for a generated 100-series
fixture. Document retry bounds and how an operator reduces concurrency if a manager
is overloaded. Do not tune a live server or change its settings as part of unit tests.
