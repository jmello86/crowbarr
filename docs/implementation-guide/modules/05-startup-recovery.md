# 05 — Startup and resumable sync recovery

## Goal and boundary

Restart without forcing all known work to await a complete library refresh. Validate
candidate items against current manager truth before claiming them; resume durable sync
work from Module 04. No blind reuse of a healthy flag or fabricated webhook is allowed.

**Read:** `Service.start/close/worker/scanner`; `Database.recover/invalidate_sync/eligible/claim`;
`SyncCoordinator` and `ArrClient.catalog_item()`; `processor.current/publish_candidate`.
**Allowed:** service, sync, Arr, Database, and a focused validation helper if needed.
**Tests:** NEW `tests/test_startup_validation.py`; extend sync/restart/race suites.

## Tasks

- [ ] **05.1 — Separate catalog existence and validation readiness.** Preserve committed
  catalogs and run progress on startup. Replace the unconditional all-provider
  invalidation/whole-sync gate with explicit persisted catalog identity plus candidate
  freshness. An old discovery fingerprint is never reusable. First install with no
  catalog consumes the first successfully applied items from Module 04, not the final
  full inventory. Keep existing public integration fields compatible until Module 06
  adds detailed status. Test same configuration, changed paths, removed provider, and
  old credentials/fingerprint.

- [ ] **05.2 — Implement validation tokens.** Add the short-lived candidate validation
  schema/facade from contracts.md. Select at most 50 pending candidates using existing
  queue order; targeted item fetches happen outside the writer lock. Coalesce candidates
  belonging to one manager item. On success apply current monitoring/media identity and
  issue a 60-second token tied to expected job generation and current item revision.
  A current skip or definitive removal cannot receive a token. Test token expiry,
  provider timeout, file replacement, monitoring change, and duplicate validation.

- [ ] **05.3 — Consume tokens with fencing.** Claim atomically checks the token, settings
  fingerprint, item revision, expected job generation, ready time, and current policy.
  If any changed, leave/requeue for revalidation rather than claiming stale work.
  Folder discovery uses fresh local checks, never an invented manager token. Ensure
  higher-priority ready jobs are considered first and one unavailable provider does not
  prevent eligible jobs from another provider being considered. Test events/settings
  changes arriving after fetch but before token issue and before claim.

- [ ] **05.4 — Resume durable discovery.** Recover expired leases; resume applied batches
  without replaying their side effects. Full-run item inventory and completion markers
  remain intact. Obsolete a run on fingerprint change and create a new run without
  deleting the previous committed catalog. Checkpoint at least after every item and
  bounded apply batch. A crash after DB commit but before acknowledgment must be safe
  to repeat. Exercise each persisted phase and an incomplete deletion reconciliation.

- [ ] **05.5 — Make shutdown cooperative.** Stop new requests/items on stop_event; let
  bounded in-flight requests return within their timeout, retaining leases/checkpoints.
  Preserve the one shared shutdown deadline and service lock behavior in existing tests.
  Stop processing only the actual owned inference process group. Do not add broad
  `pkill`, process-name matching, or cleanup of unrelated workers. Old subprocesses
  remain fenced by job generation after resume.

- [ ] **05.6 — Prove early recovery.** Hold a fake full Sonarr inventory at a barrier,
  validate one existing ready job, and observe it claimed before releasing the barrier.
  Repeat with Sonarr unavailable and a ready Radarr job. Test fresh-install streaming,
  settings changed during restart, an imported item removed from monitoring, and a
  provider returning malformed data. Include a publication-race regression.

## Acceptance and exit gate

- With a current persisted catalog and responsive mocked targeted validation, a ready
  job becomes claimable without waiting for full inventory completion.
- Validate this within a 30-second reference startup target in Module 07; unit tests
  prove ordering via barriers and fake clocks, not a 30-second sleep.
- No authoritative manager check means no manager-backed claim; a successful system
  status call alone is insufficient. Provider failures are isolated and visible.
- Crash/restart does not duplicate jobs, reset first-seen/wait times, erase history,
  consume failure attempts administratively, or infer deletions from partial runs.
- Existing media/current-input/ownership guards still execute at publication.

Run startup, sync/race, restart, queue, Arr, API, and publication suites; standard exit
gate. Document precisely which checkpoints resume and which unfinished requests/chunks
may repeat. Do not promise zero repeated work or instantaneous startup on every host.
