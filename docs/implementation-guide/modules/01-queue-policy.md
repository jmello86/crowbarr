# 01 — Queue and policy efficiency

## Goal and boundary

Make idle polling and claiming one job independent of total catalog size, apart from
indexed queue selection. Preserve eligibility and publication safety under simultaneous
rule, metadata, and worker changes. Finish before changing Sonarr request concurrency.

**Read:** `Database.claim/connect/cache_audio/refresh_library_policy/update` in
`crowbarr/db.py`; `catalog.rows/preferences/decision/refresh_policy`; `Service.worker`;
`app.py` handlers `library_preference`, `retry`, and `hook`; `processor.publish_candidate`.

**Allowed production files:** those five Python files. NEW helper `crowbarr/policy.py`
is allowed if it reduces duplication. Do not modify inference, audit thresholds, or UI.
**Tests:** existing queue/library/restart/Arr suites; NEW `tests/test_policy_scaling.py`.

## Tasks, in order

- [x] **01.1 — Characterize policy parity.** Add fixtures for title/season/file overrides,
  shared episode files, untagged/multiple audio languages, folder-only jobs, and an
  unmanaged old job. Compare current `decision()` outputs, queue order, and publication
  refusal. Add a test proving idle `claim()` currently calls full `catalog.rows()`.
  That final test must fail after changing its expectation to zero full-catalog calls.

- [x] **01.2 — Add policy revision and dirty tracking.** Implement the contract's revision,
  per-job projected revision, coalesced dirty-path work, and global cursor. Existing
  databases start dirty and retain all states/history. Make schema creation and upgrade
  idempotent; rollback all new schema/data on an injected migration failure. Write an
  index for the dirty cursor/lookup. Do not eagerly backfill the entire library during
  every Database construction. Test reopening both old and new fixture databases twice.

- [x] **01.3 — Implement bounded projection.** Add `mark_policy_dirty()` and
  `refresh_policy_batch(limit=200)`. Read only the bounded media identities and required
  metadata, compute using `decision()`, then CAS-apply the same revision in a short write
  transaction. Metadata used by policy must have a revision too; do not publish a
  calculation whose metadata changed after its read. Cover include-after-skip revival,
  cancellation of active excluded work, cursor completion, coalescing, and a rule change
  halfway through a batch. Do not use the heavyweight UI-oriented `rows()` loader.

- [x] **01.4 — Make claim and publication authoritative for one file.** Remove full
  `refresh_policy()` from `claim()`. Examine at most 200 queued candidates per claim
  call, validate each candidate's current policy under the transaction, and either claim
  one or transition newly excluded work appropriately. Preserve the 0.4.14 indexed
  provider lookup, priority aging, library order, ready gate, and single active job.
  Add the same current-policy check at publication/manual approval so a dirty cached
  allow cannot authorize a write. Test a rule change at the publication boundary.

- [x] **01.5 — Wire every mutation.** Rule writes advance revision atomically; catalog
  changes and `cache_audio()` mark affected paths dirty. Integrate bounded projection
  work into the service, including while paused (pause blocks inference, not metadata
  maintenance). Adapt existing `refresh_library_policy()` callers without silently
  performing a full pass. A retry must validate that file immediately. Test newly included
  skipped work becoming queued after projection and skip/include on real shared-file
  identities. Preserve synchronous API guarantees where they affect safety; eventual
  background projection must never mean eventual protection against publication.

- [x] **01.6 — Measure and document.** Retain the existing 0.4.14 SQL regression. Add a
  small generated catalog fixture with 3,000 items/500 jobs and operation counters.
  Report SQL statements, policy records inspected, and full loader calls for an idle
  claim and a single-file mutation. Record migration/rollback behavior in the ledger.

## Required tests and acceptance

Run `tests/test_queue.py`, `test_library.py`, `test_arr.py`, `test_restart.py`, relevant
publication tests in `test_processor.py`, and the new suite. Then the standard exit gate.

- Idle claims perform **zero** full-catalog policy loads and issue bounded SQL; one
  projection commit touches at most 200 paths. Assert counts, not machine speed.
- Growing the catalog from 3,000 to 15,000 unchanged records does not grow the number
  of policy objects inspected by an idle claim or a single-file decision.
- Four concurrent claimers still produce exactly one active inference job.
- Changed rules/metadata cannot race an old projection or a publication into accepting
  forbidden work. Newly allowed work is not permanently stranded.
- Failure attempts, job generations, history, and established priority order remain correct.
- Public API fields remain compatible; no audit-policy or recognition-policy bump.

**Rollback:** stop the service, save new data, and restore the matching pre-module data
backup with the previous image. Do not promise that an older image understands the new
projection schema. The migration itself must be additive and preserve old columns.
