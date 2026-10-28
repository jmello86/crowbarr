# 04 — Incremental, independent provider synchronization

## Goal and boundary

Replace whole-library, all-or-nothing work with durable per-item synchronization.
Sonarr and Radarr progress independently; interrupted/partial scans cannot delete good
catalog data or overwrite newer imports. Modules 01–03 must pass completely.

**Read:** `Service.scanner`; `library.scan_arr/prepare_and_restore/queue_media`;
`Database.replace_catalog/discard_unmanaged/sync_failed/save_library_metadata`;
`ArrClient.iter_catalog_items/catalog_item/event_files`; `app.py:hook/trigger_scan`.
**Allowed:** those files, config, NEW `crowbarr/sync.py` and focused migration helper.
**Tests:** NEW `tests/test_sync.py` and `tests/test_sync_races.py`; retain Arr/restart suites.

## Tasks

- [ ] **04.1 — Add durable run/item schemas.** Introduce the four contract tables and
  facade methods for create/resume/lease/apply/finish. Use UUID run IDs and unique
  provider/item keys. Store discovery fingerprint and item revision on every work unit.
  Add indexes for pending leases, provider/item lookups, staging completion, and expiry.
  Test idempotent upgrade from 0.4.14, failure rollback, duplicate work, and lease expiry.

- [ ] **04.2 — Implement per-item atomic application.** Fetch/stage outside writer locks.
  Apply catalog metadata, observation updates, queue changes, and policy invalidation in
  bounded chunks (200 files maximum per commit). An item is complete only after every
  chunk is applied. Retire missing files for that item only after its authoritative
  complete result is committed. Never call global `discard_unmanaged()` against a partial
  item/run. Preserve physical-file deduplication and results/carry-forward behavior.
  Compare normalized record content/revision before rewriting catalog metadata or
  dirtying policy; unchanged content is a no-op. Run bookkeeping/seen markers may still
  advance. Test an unchanged item causing zero catalog-content or settled-job writes.

- [ ] **04.3 — Separate provider scheduling.** SyncCoordinator owns independent provider
  run state and bounded pools; use a shared cap of eight concurrent manager requests
  across providers. A slow/failing Sonarr cannot hold a successful Radarr validation
  behind it. Snapshot settings per run and obsolete old-fingerprint work. Implement
  interruptible waits and shutdown deadlines using the existing service stop event.
  Inject one provider outage and verify the other completes and queues its work.

- [ ] **04.4 — Make events durable and coalesced.** Authenticate/validate a webhook and
  persist `(provider,item_id,requested_revision)` before returning 202; fetch asynchronously
  through `catalog_item()`. Test/targetless events retain documented behavior and may
  request reconciliation. Rename, delete, upgrade, monitoring changes, duplicate and
  out-of-order events must converge by fetching current manager truth. A transport
  failure must retain the intent for bounded retry. Never trust webhook media paths.

- [ ] **04.5 — Fence full scans against newer events.** Capture each item's requested
  revision before fetch. Reject stale application when a newer event revision exists;
  enqueue a refetch. At full inventory completion, retire absent items only if every
  required fetch succeeded and no newer item revision would be erased. Apply identical
  fencing to item deletion and configuration changes. Write deterministic barrier tests
  for an import arriving before fetch, during staging, during apply, and before final
  deletion. This task is not done with an optimistic last-write-wins implementation.

- [ ] **04.6 — Add incremental/full cadence.** Keep `scan_seconds` as the incremental
  reconciliation cadence. Add `full_scan_seconds` default 86400, range 3600–604800,
  excluded from processing fingerprints. Webhooks trigger immediate targeted work.
  Do not rely on undocumented manager change timestamps: periodic bounded per-item
  reconciliation must eventually visit every item, and a full pass must force source
  hash verification. The explicit Scan API requests a full reconciliation. Missed
  events and monitoring-only changes must converge even without a history endpoint.

- [ ] **04.7 — Remove full-pass enqueue barriers.** Prepare/apply items as they complete;
  do not collect all prepared media before enqueueing the first batch. Keep per-item
  completion, global deletion completion, and provider freshness distinct. Publish
  phase/counter/heartbeat snapshots for Module 06 without implementing UI. Preserve
  folder-only discovery; route it through bounded preparation where possible without
  pretending it has Arr monitoring information.

## Tests and exit gate

- Radarr can complete while Sonarr is blocked by a test barrier.
- The first successful item's jobs become visible before the final item is fetched.
- Duplicate/replayed events are idempotent; newer imports survive stale full scans.
- Timeout, partial pages/items, unreadable mounts, cancel, and old settings never imply
  deletion. Definitive successful empty items and completed full inventories do.
- Restart at each stage resumes leased work without duplicated jobs or lost history.
- Stable existing results are preserved; changed media/signatures queue exactly once.
- Memory contains bounded in-flight items, not a full catalog plus all prepared results.
- Existing hooks return compatible status/auth behavior; no source subtitle writes.

Run sync/race suites plus Arr, queue, library, restart, API, and publication suites;
then the standard exit gate. Record new schema, cadence, explicit-scan semantics,
lease durations, and provider failure recovery in the ledger and user documentation.
