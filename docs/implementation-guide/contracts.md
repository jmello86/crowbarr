# Shared contracts and invariants

Read this before every module. This document fixes cross-module choices to prevent
piecemeal implementations from requiring an architecture rewrite. Proposed interfaces
are **NEW** unless explicitly identified as existing. Do not implement future interfaces
before their owner module.

## Existing architecture to preserve

| Responsibility | Existing location |
| --- | --- |
| Arr discovery and event lookup | `crowbarr/arr.py`: `ArrClient`, `ManagedFile`, `map_path()` |
| Filesystem eligibility and signatures | `crowbarr/library.py`: `allowed()`, `signature()`, `prepare_media()` |
| Queue, current jobs, result/history persistence | `crowbarr/db.py`: `Database` |
| Library identity and inclusion rules | `crowbarr/catalog.py`: `identity()`, `decision()`, `refresh_policy()` |
| Scanner/worker process lifecycle | `crowbarr/service.py`: `Service`, `run_job()` |
| Input guards and atomic subtitle publication | `crowbarr/processor.py`: `current()`, `process()`, `publish_candidate()` |
| Chunk checkpoints | `crowbarr/inference.py`: `transcribe_bounded()`; `processor._recognized_words()` |
| Authenticated API and webhooks | Nested handlers in `crowbarr/app.py:create_app()` |
| Session-based browser UI | `crowbarr/static/app.js`, `app.css`, `index.html` |

Keep `Database` as the public persistence facade through Module 12. Extract helpers
behind it when useful; avoid replacing every caller or adding an ORM during sync work.
All new migrations are registered from its initialization path and tested transactionally.
Do not run heavyweight repair/backfill on every `Database()` construction: worker
subprocesses also construct it.

## Non-negotiable invariants

1. One physical media file has one current job. History/results remain separate.
2. `jobs.generation` is the worker fencing token. Replaced requests cannot write results.
   A suspended/resumed worker receives a new generation; old workers stay fenced out.
3. `Settings.discovery_fingerprint()` identifies provider/path/monitoring configuration.
   A sync fetched under old configuration cannot authorize current work.
4. A catalog run ID, a job generation, a policy revision, and a settings fingerprint
   are distinct values. Never reuse one as another.
5. Preserve title/season/file rules, multi-episode shared-file skip semantics, and explicit
   inclusion precedence. Unknown language remains conservative under existing policy.
6. No network I/O, model work, directory traversal, or subtitle hashing inside a queue
   write transaction. The existing publication boundary is a narrow exception: its atomic
   file replacement remains serialized with the latest generation/preference guard.
7. Failed, incomplete, canceled, or configuration-stale catalog runs never infer deletions.
   A verified item deletion may retire that item's records independently.
8. Authored/provider files remain untouched by optimization, undo, and retention.
   External edits and symlinks fail closed at every output replacement/deletion boundary.
9. Input signatures must be verified with fresh file bytes before publication and manual
   approval. Scan caches are hints, not publication authorization.
10. A retryable transport failure is different from an authoritative empty catalog/404.
    Never interpret timeout, 401, 429, 5xx, parse error, or inaccessible mount as removal.
11. Keep one inference child. Parallelize bounded discovery I/O only.
12. Settings snapshots are immutable per request/job/run. Never mutate the shared Settings
    object to apply per-job behavior.
13. Session and machine API authentication remain on new endpoints. No secrets in public
    status, diagnostics, exceptions rendered by the UI, or committed fixtures.
14. Resume/preemption does not consume failure attempts; real failures retain limits.
15. Never claim end-to-end performance or real XPU success from unit tests or CPU smoke tests.

## Policy projection: owner Module 01

Retain existing `jobs.library_order` and `jobs.library_blocked` as cached projections.
Add a monotonic `policy_revision` in `meta` and per-job projected revision. Keep
`catalog.decision()` as the policy oracle rather than copying its precedence rules.

NEW facade operations:

```text
Database.mark_policy_dirty(paths=None) -> revision
Database.refresh_policy_batch(limit=200) -> remaining_count
Database.check_current_policy(connection, media) -> decision
```

`paths=None` invalidates the projection globally without a Python loop over the catalog
under the writer lock. Otherwise coalesce dirty paths by primary key. Projection
calculation uses read snapshots; applying a batch compares the revision and retries
changed inputs. Batch commits are bounded at 200 paths. A global refresh advances by
an indexed stable cursor; it must also cover jobs absent from managed media.

Claims and publication check current policy for the candidate media inside their short
transaction, even if its projection is dirty. An outdated allow must never publish;
an outdated skip may delay a newly included job only until its bounded projection
batch runs. Global rule changes cannot leave skipped work permanently stranded.
Rule writes + revision advance are atomic. Background projection never overwrites a
newer rule/metadata decision. Every catalog/audio/rule mutation calls the same invalidation
facade. No full `catalog.rows()` call on an idle claim or single-file API operation.

## Discovery/cache interfaces: owners Modules 02–04

- Module 02: NEW `ArrClient.iter_catalog_items()` yields complete per-item results;
  `catalog()` remains a compatibility collector. NEW `catalog_item(item_id)` validates
  the item and its monitored episode/file state. `event_files()` uses this shared path.
- A per-item result includes provider, item ID, discovery fingerprint, authoritative
  file list, and a complete/removed outcome. Exceptions never masquerade as empty results.
  Implemented as `arr.CatalogItem` in Module 02. An unbound standalone adapter reports
  fingerprint None; coordinators must supply the full Settings discovery fingerprint
  and reject unbound snapshots for freshness/authorization. Request metrics describe
  fetching, not successful database application.
- Module 03: NEW `ScanContext` is scoped to one scan/batch. It caches resolved allowed
  roots, directory entries, and stat hints, and tracks operation counts. Existing callers
  without a context keep the exact current behavior.
- Module 03: durable subtitle-hash cache keys include canonical path, device/inode,
  size, mtime_ns, ctime_ns, and cache format version. Failing any validation recomputes.
  Every full reconciliation rereads hashes; targeted/scoped scans may reuse hints.
- Module 04: NEW `SyncCoordinator` in `crowbarr/sync.py` owns provider scheduling,
  durable work leasing, batch publication, and metrics. `Service.scanner()` delegates;
  API hooks enqueue work rather than executing a full sync synchronously.

Persistent sync state (Module 04 introduces migrations; exact SQL lives behind Database):

| Table | Minimum fields / uniqueness |
| --- | --- |
| `sync_runs` | UUID run_id PK; provider; discovery fingerprint; mode; state; phase; timestamps/heartbeat; total/completed items; generation; sanitized error code |
| `sync_items` | (run_id,item_id) PK; pending/fetching/applied/failed; attempts; lease deadline; item revision captured at fetch start |
| `sync_staging` | (run_id,file_id) PK; provider/item ID; normalized ManagedFile payload; seen marker |
| `item_refreshes` | (provider,item_id) PK; monotonically increasing requested revision; applied revision; lease/backoff |

Run states: `pending`, `running`, `complete`, `failed`, `cancelled`, `obsolete`.
Phases: `discover`, `fetch`, `inspect`, `apply`, `reconcile`, `idle`.
A provider's file IDs are unique only within that provider. Canonical media path remains
the cross-provider physical-file identity. Full inventory and per-item results must be
staged/marked complete before their missing records can be retired.

Import/webhook work advances an item revision. A full scan fetched before that advance
cannot overwrite the newer item result. Re-fetch that item, or exclude the newer item
from stale application/deletion reconciliation. No global run completion may erase a
newer webhook import. Do not hold an HTTP response open while fetching the whole library.

## Startup freshness: owner Module 05

Persisted catalogs survive restart. They are not automatically fresh authorization.
NEW `validate_candidate(job_id)` performs a targeted manager lookup outside the write
lock and records a short-lived (60 seconds) validation tied to provider, item ID,
discovery fingerprint, item revision, media identity, and expected job generation.
The claim consumes/checks that token with a compare-and-swap. Expired/mismatched tokens
trigger revalidation; inaccessible providers defer only their own jobs. Folder-only
mode uses current filesystem/policy validation, not a manager token.

This is a point-in-time manager check; later changes arrive through webhooks and
reconciliation. Cancellation/generation and pre-publication file checks remain required.
No setting of provider `healthy=1` solely because a system-status request succeeded.

## Status contract: owner Module 06

Add fields to existing `/api/status`, `/api/events`, and job detail responses. Preserve
existing fields and job states; do not create database states just to fix a label.

```text
sync: [{provider, run_id, state, phase, completed_items, total_items|null,
        checked_files, changed_files, queued_files, failed_items,
        started_at, updated_at, last_success, error_code|null}]
scheduler: {reason_code, message, until|null}
job.eligibility: {ready_at, time_ready, policy_allowed, provider_validated,
                  reason_code, message}
```

Reason codes: `none`, `paused`, `subtitle_grace`, `file_settling`, `provider_refresh`,
`provider_unavailable`, `policy_refresh`, `policy_skip`, `quiet_hours`, `plex_busy`,
`cpu_busy`, `ram_low`, `vram_low`, `budget`, `cooldown`, `preempted`.
Compute reason precedence server-side. Global resource gates still apply to urgent work;
background-only gates retain existing manual/import exemptions. Never fabricate a
percentage when the denominator is unknown. Server-Sent Events remain the status
transport; the browser does not introduce full-library polling.

## Effective settings: owner Module 08

NEW `effective_settings(global_settings, media_identity, binding) -> SettingsSnapshot`
returns a validated immutable Settings copy, profile ID/revision, processing fingerprint,
and recognition fingerprint. The no-profile case produces the existing fingerprints
and behavior byte-for-byte. Discovery settings, credentials, mounts, pause, and global
resource limits cannot be overridden by a profile.

Profile IDs, names, and revision numbers are provenance, not processing inputs by
themselves. Renaming a profile or changing an override to the same effective value must
not requeue work. Retain the legacy fingerprint when effective behavior matches it;
use a versioned extra-settings envelope only for additional behavior-affecting values
not represented in the legacy fingerprint. Specify/test the exact serialization in
Module 08 before wiring callers. Recognition keys include recognition inputs only.

Precedence is explicit title binding, then longest matching canonical library root,
then global defaults. Existing skip/include rules remain separate and win over processing.
Use the same snapshot for signature, claim, child execution, manual approval, current
input checks, reporting, and transcript cache keys. A change invalidates affected work
only. Later modules must consume this resolver instead of inventing overrides.

## Artifacts and destructive operations: owners Modules 10–12

Module 10 introduces versioned `publication_events` and `managed_artifacts` tables.
Each artifact has ID, kind, relative private path (or validated media output location),
digest, size, created/accessed times, owning job/generation, protection/reference state,
and schema version. Only registered, verified Crowbarr artifacts are eligible for undo
or automatic cleanup. Legacy backups may be registered only when ownership and digest
can be established; otherwise expose them as unverified and protect them.

Undo uses a durable intent journal, generation/policy guard, verified current output
digest, verified prior bytes, atomic replacement, and recoverable completion record.
It never edits an authored file and never overwrites an external edit. The full undo
flow, not just its button, must pass before Module 11 adds deletion.

Retention computes candidates, rechecks protection under an exclusive maintenance
lease, revalidates path/no-symlink/digest, and then deletes individual artifacts. Running
work, resumable chunks, review candidates, and undo-pinned artifacts are protected.
Backup/restore and retention share the same maintenance lease so files cannot vanish
mid-export. Diagnostics are a distinct sanitized product and never include backups.

## Performance contracts

- CI gates use counts, SQLite instruction budgets, bounded active requests, and bounded
  batch size. Avoid hard wall-clock assertions on shared runners.
- Module 07 owns measured wall-clock/RSS acceptance, environment recording, fixtures,
  and reference thresholds. Earlier modules report operation counts using small fixtures.
- No claimed speedup may be based on skipping monitoring checks, signatures, source
  discovery, language checks, or deletion reconciliation.
- SQLite optimization and PostgreSQL parity use the same queue/publication semantics.
  PostgreSQL row locking does not authorize concurrent inference children.
