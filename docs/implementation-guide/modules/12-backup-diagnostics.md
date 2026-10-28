# 12 — Consistent backup, restore, and sanitized diagnostics

## Goal and boundary

Provide tested recovery and a safe support bundle as two distinct products. Complete
Module 11 so backup can pin artifacts and coordinate with retention. A diagnostics
download must never be a disguised copy of a credential-bearing backup.

**Read:** `docs/migration.md`; `ConfigStore/atomic_write`; `Database.connect/recover`;
service lifecycle and maintenance lease; artifact manifest; API auth/download handlers;
`packaging/install-crowbarr.sh` and native data-directory conventions.
**Allowed:** NEW `crowbarr/backup.py`, `crowbarr/diagnostics.py`, an explicit backup/restore
CLI, auth/API/UI integration, maintenance hooks, and migration documentation.
**Tests:** NEW `tests/test_backup.py`, `tests/test_diagnostics.py`, `tests/test_restore.py`.

## Tasks

- [ ] **12.1 — Define archive format and restore boundary.** Version the manifest with
  application/schema/audit versions, creation time, file digests/sizes, optional models,
  and required artifact references. Include settings, dashboard credentials, API token,
  database, and required private recovery artifacts in a backup; warn clearly that it
  contains secrets. Preserve ownership/modes in a documented portable form. Never
  include media videos or provider sidecars by default. Protect the archive with mode
  0600 and authenticated, expiring download access; no secrets in its filename.

- [ ] **12.2 — Make a consistent export.** Acquire the maintenance lease and a bounded
  consistency barrier coordinating inference publication, config/profile edits, artifact
  mutations, and retention. Use SQLite's backup API for a consistent DB snapshot, not a
  copy of only `crowbarr.db` while WAL writes continue. Pin referenced immutable files
  until export completes. Settings/config versions must correspond to that snapshot;
  if a consistent barrier cannot be acquired within 30s, fail clearly and retain prior
  data. Long file copying may occur after the snapshot while pins prevent deletion.
  Model caches are optional to avoid huge exports. Resume normal work in every error path.

- [ ] **12.3 — Implement offline restore validation.** Restore runs with the service stopped
  and its data lock acquired, into a new staging directory. Reject traversal, absolute
  archive paths, symlink/hardlink escape, duplicate targets, oversized entries/archives,
  missing required files, bad hashes, and unsupported schema versions. Check database
  integrity and required artifacts before switching directories. Never merge over a
  running service or silently rewrite media mounts. Save current data before replacement;
  report that media-side published SRTs require separate media backup/undo handling.

- [ ] **12.4 — Round-trip recovery.** Build a fixture with profiles, rules, completed/review
  history, a resumable checkpoint, undo versions, and a pending sync/event. Export,
  restore elsewhere with preserved logical media paths, start, authenticate, and verify
  queue/result/profile/artifact continuity. Inject failure before snapshot, during copy,
  before archive finalization, during restore validation, and before directory switch.
  Assert old data remains usable and no automatic duplicate publication occurs.

- [ ] **12.5 — Add diagnostics by allowlist.** Export only application/schema versions,
  dependency/backend availability, aggregate sync/queue/storage metrics, sanitized error
  codes, bounded timing counters, and redacted configuration shape. Do not include raw
  settings, URLs/query strings, API headers/tokens, cookies/password hashes, DB files,
  raw logs/tracebacks, media titles/paths, subtitle/transcript text, reports, or backups.
  If identifying paths within one bundle is necessary, use bundle-local opaque IDs.
  Regex redaction alone is insufficient; whitelist fields first. Cap bundle at 10 MiB
  and source counts/strings; malformed diagnostic inputs must not bypass exclusions.

- [ ] **12.6 — Add operator UI and documentation.** Backup/diagnostic jobs are authenticated,
  bounded, observable asynchronous operations with cleanup/expiry. Restore remains an
  offline CLI for this module; do not add a web endpoint that overwrites its own running
  state. UI distinguishes backup from diagnostics and explains secrets/media scope.
  Update migration docs with exact export/verify/stop/restore/start/verify/rollback steps.
  Seed canary credentials/URLs/subtitle text and assert none appear in diagnostics,
  while a protected backup preserves the actual values required for recovery.

## Acceptance and exit gate

- Backup round-trip preserves authentication, settings, rules/profiles, queue/history,
  checkpoints, undo artifacts, and pending events. Archive integrity is independently checked.
- Live export is snapshot-consistent and cannot race retention/publication/config changes.
- Every failed backup/restore preserves recoverable prior data and releases maintenance.
- Restore refuses unsafe/unsupported archives and a running-service data lock.
- Canary secrets, identifying media data, raw reports, and subtitle text are absent from
  diagnostics; auth and size limits are tested on every new endpoint.

Run backup/restore/diagnostic plus artifact/storage/profile/restart/API suites, standard
exit gate, and a documented offline restore drill on disposable data. Do not test restore
against the operator's actual app-data directory.
