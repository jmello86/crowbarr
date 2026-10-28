# Implementation progress ledger

Planning baseline: application 0.4.14 / audit policy 0.3.7.
No implementation module is complete merely because this guide exists.

| Module | State | Last completed task | Evidence / next action |
| --- | --- | --- | --- |
| 01 | Complete | 01.6 | 377 passed, 6 skipped; Ruff/wheel pass. Local module commit; unreleased. |
| 02 | Complete | 02.5 | 449 passed, 6 skipped; Ruff/wheel pass. Local module commit; unreleased. |
| 03 | Not started | — | Ready for 03.1; Module 02 exit gate passed. |
| 04 | Not started | — | Requires 03 exit gate. |
| 05 | Not started | — | Requires 04 exit gate. |
| 06 | Not started | — | Requires 05 exit gate. |
| 07 | Not started | — | Requires 06 exit gate. |
| 08 | Not started | — | Requires 07 exit gate. |
| 09 | Not started | — | Requires 08 exit gate. |
| 10 | Not started | — | Requires 09 exit gate. |
| 11 | Not started | — | Requires 10 exit gate. |
| 12 | Not started | — | Requires 11 exit gate. |
| 13 | Deferred decision | — | Requires 12 exit gate; do not assume PostgreSQL is required. |

## Module 01 working notes

- Starting commit: `9cf86d6` (guide), application remains 0.4.14.
- 01.1: characterization compares single-file decisions with the existing full loader
  across rule precedence, shared episodes, audio overrides, and unmanaged folder jobs.
  The new idle-claim assertion fails on the old full-catalog implementation as expected.
- Task decomposition: 01.2 migration/triggers; 01.3a bounded record/oracle reads;
  01.3b revision-fenced batch application; 01.4 claim/publication integration;
  01.5a API mutation integration; 01.5b service maintenance; 01.6 evidence and exit gate.
  These are sequential subtasks within Module 01, not parallel module implementations.

### 01.1 — Characterization

- Added `tests/test_policy_scaling.py`. Original source: 5 expected failures, 1 pass.
  The idle-claim failure specifically demonstrated a call to `catalog.rows()`.
- Policy parity covers title/season/file precedence, shared episode identities,
  audio metadata precedence, unknown/multiple languages, folder and unmanaged jobs.
- Existing queue-order, active-skip, source-integrity, and four-claimer tests remain gates.

### 01.2 — Migration and invalidation

- Added `crowbarr/policy.py:migrate`, called inside `Database.__init__`'s existing
  migration transaction. Adds jobs.policy_revision/policy_input_revision,
  policy_inputs/policy_dirty/policy_scan, and the managed_item lookup index.
- Triggers atomically fence catalog, library metadata, audio metadata, job-path,
  rule, and audio-policy mutations, including existing direct-SQL mutation callers.
  Dirty paths coalesce; global rule invalidation advances a durable job-ID cursor.
- Legacy reopen is lazy/idempotent. Injected failure during trigger creation rolls
  back every new column/table/trigger/index, preserving the prior queue records.

### 01.3 — Bounded projection

- `policy.refresh_batch` reads identities/rules/tokens in one read snapshot, computes
  decisions through the unchanged `catalog.decision`, then applies at most 200 paths
  in a separate write transaction. Rule and metadata revision comparisons reject stale
  snapshots. Global cursor updates use compare-and-swap and do not regress on restart.
- Tested rule, metadata, audio, and manager-identity changes between read and apply;
  coalescing; batch bounds; folder coverage; skip-to-include revival; and lazy reopen.

### 01.4 — Claim and publication

- `Database.claim` no longer calls the full policy/UI loader. It fetches at most 200
  lightweight candidate identities and validates current policy before claiming one.
  Enqueue projects that file's ordering/policy immediately. The existing indexed
  provider eligibility, priority aging, readiness, attempts, and generation fencing remain.
- `processor.publish_candidate` checks current policy before journaling and again at
  the serialized file replacement boundary. Approval's final DB update is generation-
  fenced too. Tests refuse unprojected skips, changes after journaling, and replaced
  manual approval requests; no forbidden output is written.

### 01.5 — Integration

- Single-file retry, manual processing, and file preferences use scoped decisions;
  they do not load the UI catalog. Hooks project imported paths in bounded commits.
- Preference writes and active-worker cancellation/projected blocking are atomic.
  Title/season targets use scoped manager/folder lookup; invalid targets return 404.
- `Service.worker` processes one maintenance batch before pause/resource gates.
  `refresh_library_policy()` schedules one global batch, leaving remaining work durable;
  explicit paths use bounded commits. Paused-service maintenance is tested.
- Existing API fields/auth remain; job rows gain additive projection revision columns.
  No application release, audit-policy, or recognition-policy bump was made.

### 01.6 — Measurements and exit evidence

- Dedicated command: `python -m pytest tests/test_policy_scaling.py -q -s`:
  **31 passed**. Ruff across crowbarr/tests/integrations/packaging: **passed**.
- For both 3,000 and 15,000 generated catalog records with 500 pending jobs:

  | Operation | SQL statements | Policy objects inspected | Full catalog loads |
  | --- | --- | --- | --- |
  | Claim one eligible job | 17 | 1 | 0 |
  | Idle check with an active worker | 3 | 0 | 0 |
  | Explicit single-file refresh | 13 | 1 | 0 |

- Tests also cap a stale-policy candidate sweep at 200, then verify the next call
  reaches the remaining eligible job. Four concurrent claimers produce one worker.
- Earlier full-suite run before final added edge cases: 370 passed, 6 skipped.
  Final current-source `python -m pytest -q`: **377 passed, 6 skipped**, 116.22 seconds
  on Python 3.12. Existing Docker/platform-dependent skips remain; Starlette emits one
  existing TestClient/httpx deprecation warning. No test failure is left unresolved.
- Wheel built successfully with `python -m pip wheel --no-deps . -w /tmp/crowbarr-module01-wheels`.
  It includes the new policy module; the wheel is a local unreleased verification artifact.
- Browser gate: not applicable (no browser files changed). Hardware/inference performance,
  actual NAS sync duration, and the 150,000-file acceptance workload were not tested here.
- Upgrade/rollback guidance: `docs/migration.md`, upcoming policy projection section.
  Use a complete stopped-service backup and restore its matching image/data on downgrade.
- Remaining scope: manager requests and the UI library loader are unchanged; those are
  later modules. This evidence establishes bounded policy work, not overall sync speed.

### Module 01 exit gate

| Criterion | Result / evidence |
| --- | --- |
| Tasks 01.1–01.6 | PASS; task list checked in modules/01-queue-policy.md. |
| No full policy load during claim/file API | PASS; prohibited loader monkeypatch plus SQL/object counters. |
| Bounded work at both catalog sizes | PASS; identical operation counts at 3,000/15,000 records. |
| Batch/candidate limits | PASS; projection batches <=200; candidate sweep stops at 200. |
| Legacy migration and restart | PASS; lazy/idempotent reopen, cursor recovery, transactional failure rollback. |
| Rule/metadata races | PASS; independent rule, metadata, audio, and identity revision fences. |
| Publication/approval safety | PASS; stale cached allows, post-journal edits, and replaced approvals refused. |
| Single worker / queue semantics | PASS; concurrent claimers and original priority/history/attempt tests. |
| Paused maintenance | PASS; paused service updates policy without starting inference. |
| Full suite / Ruff / wheel | PASS; 377 passed, 6 skipped; lint clean; helper/migration present in wheel. |
| Browser / live hardware / deployment | Not applicable/not performed; no UI edits or live deployment. |
| Unresolved decisions | None for this module. |

- Save as a local commit on `work/module01-policy-efficiency`; this ledger is included
  in that commit. No source push, image publication, production schema migration, or
  deployed-container patch is part of this module's exit.
- Upgrade requires a complete pre-upgrade data backup. Rollback restores matching old
  image/data; an image-only downgrade is not asserted compatible with the new triggers.
- Next module: **02 — Sonarr fetch efficiency**, task **02.1** (linear episode grouping).

## Module 02 working notes

- Starting commit: `1300bf0`; application remains 0.4.14, unreleased work.
- Task sequence: 02.1 grouping; 02.2a item result contract/validation; 02.2b shared fetch
  normalization and compatibility collector; 02.3 bounded pool/settings; 02.4 retry and
  cancellation; 02.5 counters, integration, parity/scale evidence, and final exit gate.
- Scope stays within Arr/config plus scan caller compatibility; no database publication,
  deletion, inference, UI, or live-server changes are authorized by this module.

### 02.1 — Linear association

- New regression initially failed with **3,003,000 episode visits** for 1,000 files
  and 3,000 episodes. `_episode_groups` now visits the list **3,000 times**, once per
  episode. `_file` sorts only the matched group, preserving merged episode titles and
  shared-file identities. Existing Arr characterization tests pass.

### 02.2 — Item results and compatibility

- Added `arr.CatalogItem`, `catalog_item`, `iter_catalog_items`, and shared
  `_catalog_record` normalization. Empty/unmonitored is complete; targeted item 404 is
  removed; transport/authentication/JSON/shape failures have no successful outcome.
- `catalog()` still returns a complete list, sorted by provider/item/file IDs, and fails
  closed on any item failure. A full inventory does not add per-item detail requests;
  targeted/event lookups fetch current item truth and filter event file IDs afterward.
- Client connection/mapping/monitoring configuration is copied. The full Settings
  discovery fingerprint is passed by `scan_arr`; unbound helper calls explicitly have None.

### 02.3 — Bounded pool and settings

- `sync_request_workers` defaults to 4, accepts strict integers 1–8, persists in settings,
  and is excluded from processing/discovery fingerprints. API round-trip and settled-job
  preservation are tested. `scan_arr` forwards workers and the full discovery fingerprint.
- One shared thread-safe HTTPX client has bounded connection limits and an explicit
  request semaphore. Item futures are replenished only up to twice the worker count.
  Tests force overlapping requests with barriers at 1/4/8 workers and verify caps,
  queue bounds, deterministic complete output, and client closure.

### 02.4 — Retry and cancellation

- Only GET transport failures or 429/502/503/504 retry, maximum three attempts. Retry-After
  dates/deltas clamp to 1–60 seconds; fallback is exponential plus bounded jitter.
  Injected clock/jitter/wait avoid real backoff sleeps in tests.
- Cancellation checks submission, slot acquisition/request start, backoff, item completion,
  and yielding/collection. Owned workers finish/cancel before client close. Tests cover
  early cancel, blocked requests, backoff, observer-triggered cancel, early iterator close,
  an abandoned iterator at context exit, and reuse after explicit iterator close.
- Existing whole-catalog persistence remains unchanged. Injected 401/404/429/503,
  timeout, malformed JSON, and invalid shapes preserve the prior catalog and queue.
  Server-wide stop-event/coordinator wiring remains in later modules.

### 02.5 — Metrics, evidence, and exit verification

- Aggregate callback/metrics snapshots expose no URLs, keys, paths, or payloads.
  Observer mutation cannot corrupt counters; a failing observer is disabled/logged
  once without exception text. Completed-item counts mean fetched, not DB-applied.
- `python -m pytest tests/test_arr.py tests/test_arr_concurrency.py -q`:
  **89 passed** before final exit verification. Ruff passed after fixing one test-only
  loop-variable closure lint issue. No production behavior changed for that correction.
- Generated 100-series fixture, 5ms simulated GET latency, Python 3.12; one diagnostic run:

  | Workers | GET requests/attempts | Elapsed | Peak requests | Peak pending futures |
  | --- | --- | --- | --- | --- |
  | 1 | 201 / 201 | 1.520 s | 1 | 2 |
  | 4 | 201 / 201 | 0.403 s | 4 | 8 |
  | 8 | 201 / 201 | 0.209 s | 8 | 16 |

- Timing is reported only. Barrier/counter/parity assertions are the CI gates, and no
  real-manager/NAS speedup is claimed. See `docs/library-sync.md` for operator controls,
  retry/cancellation semantics, result contracts, and metric interpretation.
- Final current-source `python -m pytest -q`: **449 passed, 6 skipped**, 119.44 seconds
  on Python 3.12. The six existing environment-dependent skips remain; no new skip was
  added. The existing Starlette/httpx TestClient deprecation warning remains. Ruff passes.
- `python -m pip wheel --no-deps . -w /tmp/crowbarr-module02-wheels` builds successfully.
  The wheel contains the item-result/pool/retry implementation and the worker setting.
  One trailing blank line was removed after testing; this has no behavior change.
- No UI changes, schema migration, version/policy bump, deployment, or image publication
  is part of this module.

### Module 02 exit gate

| Criterion | Result / evidence |
| --- | --- |
| Tasks 02.1–02.5 | PASS; task list checked in modules/02-sonarr-fetch.md. |
| Linear association | PASS; 3,000 episode visits for 1,000 files, versus baseline 3,003,000. |
| Item truth and outcomes | PASS; targeted metadata/monitoring/404/error tests and full/event parity. |
| Request and future limits | PASS; deterministic barrier tests at workers 1/4/8; peaks bounded by workers and 2x workers. |
| Serial/concurrent parity | PASS; full normalized record equality, stable sorting, no per-item detail inflation in inventories. |
| Retry budget | PASS; transient statuses/transport errors cap at three attempts; injected waits/date clock tested. |
| Cancellation and cleanup | PASS; before start, blocked calls, backoff, callback cancel, early/abandoned iterator, client reuse. |
| Failure safety | PASS; preexisting catalog/queue preserved for auth/404/rate-limit/timeout/JSON/shape failures. |
| Settings/counters | PASS; default/range/persistence/API/fingerprint tests; sanitized aggregate copies and failed-observer isolation. |
| Full suite / Ruff / wheel | PASS; 449 passed, 6 skipped; lint clean; package built and inspected. |
| Real server / browser / hardware | Not changed or benchmarked here. Synthetic timings do not establish NAS/XPU performance. |
| Unresolved decisions | None for this module. |

- Save as a local commit on `work/module02-sonarr-fetch`, following Module 01. No push,
  deployment, or live configuration tuning is included. Server-wide cancellation and
  incremental catalog application remain assigned to their later modules.
- Operator guide: `docs/library-sync.md`. Reduce request workers if a manager is overloaded.
  There is no Module 02 schema migration to reverse; back up current data and preserve
  paths/settings when changing images. Full system rollback still follows `docs/migration.md`.
- Next module: **03 — Filesystem scan caching**, task **03.1** (ScanContext and operation counters).

## Copy this entry for each task

```text
Task ID:
Starting commit:
Goal and bounded scope:
Changed files and routines:
Migration/API/contract changes:
Targeted test commands and exact results:
Acceptance measurements (fixture, environment, operation counts):
Remaining failures/skips and explanation:
Safety invariants checked:
Commit:
Next task:
```

## Copy this entry at each module exit

```text
Module:
All task IDs complete:
Full suite / Ruff / wheel / browser results:
Legacy migration + restart + concurrency evidence:
Acceptance criteria, each PASS/FAIL with evidence:
Actual limitations (including hardware not tested):
Operator upgrade and rollback steps:
Unresolved decisions (must be empty before next module):
Next module and first task:
```

Do not paste secrets, production paths/titles, raw API responses, or real subtitle text
into this committed ledger. Store private acceptance evidence outside the repository;
record a sanitized measurement summary here.
