# 06 — Accurate status and scalable library UI

## Goal and boundary

Expose the actual sync/queue blocker and avoid loading every library record to render
one page. Complete Modules 01–05 first. Keep the established frontend and session model.

**Read:** `app.py:build_status/events/jobs/job_detail/browse_library/library_preference`;
`Database.snapshot`; `catalog.rows/library`; `Service.worker`; `resources.gate/quiet`;
`static/app.js:activeJob/rows/systemStrip/libraryGroup/loadList/detail/apply/listen`;
`DESIGN.md`. **Allowed:** these files, sync metrics, CSS, NEW focused status/index helpers.
**Tests:** NEW `tests/test_status_reasons.py`, `tests/test_library_pagination.py`; API/library suites.

## Tasks

- [ ] **06.1 — Implement reason calculation.** Add one server-side classifier returning
  the contract's scheduler and per-job eligibility fields. Preserve job database states.
  Once ready time expires, a stored `waiting` job must display its current blocker or
  queued eligibility, not an expired subtitle wait. Distinguish settle time from grace
  time using stored preparation metadata; do not guess from the current label. Persist
  that metadata during preparation as an additive change. Define and test precedence:
  policy exclusion; pause/global resource gate; file/grace timer; provider validation;
  background-only gates; runnable. Show urgent-job exemptions correctly.

- [ ] **06.2 — Publish bounded sync snapshots.** Implement the exact additive status
  fields in contracts.md. Unknown totals are null. Coalesce progress/heartbeats at most
  once per second while making terminal transitions immediate. Durations use monotonic
  time in-process; persisted display timestamps use UTC epoch seconds. Never serialize
  full catalogs/reports in status events. Add fields to the manually maintained API
  schema where applicable and preserve existing API keys/cookies/auth dependencies.

- [ ] **06.3 — Index the library for SQL pagination.** Add a normalized derived library
  index keyed by physical path with provider/item/title key, kind, display/search title,
  season/episode ordering, and current policy summary. Update it through the existing
  catalog/audio/policy mutation facades; test legacy incremental backfill and restart.
  Preserve `catalog.identity()`/`file_targets()` identities and word-search semantics.
  NEW authenticated `GET /api/library/titles` returns paginated groups/counts without all
  episode rows; NEW `GET /api/library/files?key=...` returns paginated files. Limits 1–100;
  parameterize SQL and escape LIKE wildcards. Keep old `/api/library` compatible for
  existing clients, but stop using its full-loader path in the browser.

- [ ] **06.4 — Update the UI.** Add a compact sync strip and current phase/counters; show
  each provider independently. Expanded shows load bounded episode pages on demand.
  Preserve title/season/file controls, focus, drafts, search, both themes, mobile layout,
  and Server-Sent Events. Use `esc()`/DOM text for external values. Do not add a poster
  wall, a framework, full-library polling, or fake progress percentages. Announce phase
  changes accessibly without announcing every counter tick.

- [ ] **06.5 — Separate liveness from useful progress.** Keep `/health` compatible for
  container liveness; a legitimate long scan/provider outage must not trigger endless
  auto-restarts. Report stale heartbeat/progress warnings in authenticated status using
  phase-aware limits (default 180 seconds without heartbeat, configurable for tests).
  A blocked scheduler remains alive. Worker/scanner thread death remains unhealthy.
  Test a healthy blocked queue, a slow active request, a stale sync lease, and dead thread.

- [ ] **06.6 — Verify browser behavior.** Exercise expired grace, provider refresh/outage,
  CPU/RAM gate, policy skip, cooldown, budget, running inference, and completed sync.
  Add deterministic browser fixtures or extend `scripts/browser_check.py`; retain manual
  visual QA screenshots outside committed fixtures. Verify authentication failures and
  missing optional status fields on a mixed-version client/server session.

## Acceptance and exit gate

- Every fixture has an accurate, tested reason; no expired “Waiting for subtitle” label.
- One title/files page queries bounded result rows; its loader does not call `catalog.rows()`.
- Pagination/filter counts and shared-file identity remain correct at 150,000 records
  under Module 07; expanding one show does not transfer the whole library.
- Status payload is under 256 KiB for the acceptance fixture and contains no subtitle
  text, credentials, or full catalog. SSE remains responsive while sync applies batches.
- Both themes and a 390px-wide viewport remain usable; keyboard navigation and drafts survive updates.

Run targeted status/pagination/API/library tests; JS syntax/browser checks; standard exit
gate. Add user documentation defining counts, phases, readiness, and heartbeat warnings.
