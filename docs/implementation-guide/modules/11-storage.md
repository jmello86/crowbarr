# 11 — Storage accounting and safe retention

## Goal and boundary

Expose storage use and safely bound replaceable private artifacts. Complete Module 10's
undo/artifact journal first. Do not add deletion based only on file age or extension.

**Read:** `processor._recognized_words()` (existing 2 GiB transcript pruning), candidate
and publication artifact code; `Database.prune/update`; `Service.start/worker` work cleanup;
`capabilities.model_inventory/start_download`; artifacts/profiles/preemption contracts.
**Allowed:** NEW `crowbarr/storage.py`, artifacts/Database/config/service, storage API/UI.
**Tests:** NEW `tests/test_storage.py`; cache/restart/undo/API suites.

## Tasks

- [ ] **11.1 — Centralize accounting.** Enumerate only configured private artifact roots:
  transcripts/checkpoint parts, candidates, reports, saved subtitles, backups, temporary
  work, models, and other/untracked bytes. Mark bytes approximate while scanning; bound
  scan work and cache aggregate results. Show model size separately and keep model
  removal explicit through existing model management. Never traverse media libraries
  for storage accounting or follow symlinks outside the private root.

- [ ] **11.2 — Establish protection references.** Pin active jobs, resumable preempted/
  interrupted chunks, current review candidates, latest retained undo version, in-progress
  publication/undo journals, and active backup exports. Module 10's manifest is the
  authority. Reconcile legacy transcript keys with pending jobs conservatively; an
  unidentifiable legacy artifact is protected/untracked, not automatically deleted.
  Test restart rebuilding protections before cleanup can run.

- [ ] **11.3 — Add validated retention settings and dry run.** Default transcript budget
  stays 2 GiB to match existing behavior, applied only to unprotected artifacts. Default
  cleanup removes no reports/backups/review candidates automatically. Optional age/budget
  limits for those categories must be explicit. Keep at least current publication plus
  one verified undo version per media unless the operator explicitly removes an undo
  version through its dedicated action. Dry-run output includes candidate artifact IDs,
  categories, sizes, reasons, and protected totals, never arbitrary deletion paths.

- [ ] **11.4 — Implement one cleanup owner.** Replace the inline transcript-pruning loop
  and indiscriminate work-tree cleanup with the central manifest-aware service. Use the
  shared exclusive maintenance lease; recheck references, path containment, lstat identity,
  and digest immediately before cleanup. For private artifacts, move to a private same-
  filesystem quarantine under the lease, verify again, then unlink. If verification
  fails, preserve/report it. Never delete current media-side output or provider sidecars.
  Keep DB and filesystem intent/recovery records consistent across a crash.

- [ ] **11.5 — Add APIs/UI.** NEW authenticated `GET /api/storage`,
  `POST /api/storage/cleanup-preview`, and `POST /api/storage/cleanup` with preview revision
  and exact selected artifact IDs. Stale previews trigger re-evaluation/409, not unchecked
  deletion. Add a Storage settings panel with category usage, limits, protected space,
  and reclaimable space. Do not display a promise to reach a budget when protected
  content exceeds it; report the limitation and keep protected work.

- [ ] **11.6 — Exercise races and pressure.** Add disk-full/quota errors, partial writes,
  missing files, changed digests, symlink swaps, active downloads, concurrent preemption,
  undo, backup lease, and restart-after-quarantine tests. Interrupted chunks must still
  resume. Verify no cleanup scans provider directories or removes untracked content.

## Acceptance and exit gate

- Accounting totals are consistent for a known fixture and clearly label approximate
  or untracked data. Enumeration is bounded and does not block status/SSE.
- Unprotected disposable caches obey configured limits; protected references always win.
- Current review, undo, active inference, resumed checkpoints, and backup exports remain
  usable after cleanup, restart, and injected failure.
- Every deletion is of a registered verified private artifact; path/digest changes refuse
  cleanup. Models require explicit operator removal, not automatic transcript retention.
- The old unconditional 2 GiB pruning path no longer races the central retention service.

Run storage/cache/restart/preemption/undo/API tests, standard exit gate, and the Module 07
concurrent status/queue subset. Document defaults, approximate accounting, quarantine
recovery, and how to recover safely when protected content exceeds the configured budget.
