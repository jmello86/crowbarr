# Crowbarr implementation guide

This is an implementation handoff, not a description of features already shipped.
Complete the modules in order. Finish each module's implementation, integration,
tests, documentation, and exit gate before starting the next module. Do not create
partially working implementations of several modules at once.

## Starting point

- Application release: **0.4.14**, audit policy **0.3.7**.
- Release commit: `2b6f57b6d0ccd525bab19abb82a92803d00bf5ec` on `intel`.
- That release fixes the correlated queue lookup in `Database.claim()` by using
  the existing `managed_path` index. `tests/test_arr.py` contains the bounded-SQL-work
  regression. It also corrects an incomplete `fstat` test double.
- Local release validation: 346 passed, 6 skipped; Ruff passed; wheel built.
- Release build: [Intel workflow run](https://github.com/jmello86/crowbarr/actions/runs/40650480926)
  completed successfully. The Python 3.11–3.13 matrix, installed dependencies, real CPU
  speech/spawn smoke test, and server health checks passed before Intel channel promotion.
- Published images: `ghcr.io/jmello86/crowbarr:intel`, `latest-intel`, and
  `sha-2b6f57b6d0ccd525bab19abb82a92803d00bf5ec-intel` (same repository prefix).
  The immutable commit image's published digest is
  `sha256:c46f557bfe4577670d6a127b27fae2bfa84700b8e7b2e5f221858e7de80ead8e`.
  GitHub-hosted CPU checks do not establish actual Intel XPU inference performance.
- No module below is implemented by this guide. The index fix is not the complete
  scalability solution. A measured queue SELECT is not an end-to-end sync benchmark.

Use the checked-out source as the authority for existing symbols. Links below are
relative to the repository; symbols are more durable than line numbers. Items marked
**NEW** are proposed files, routines, tables, fields, or endpoints, not existing ones.

## Mandatory reading

1. [Shared contracts](contracts.md).
2. The current module, and only the contracts of its immediate dependencies.
3. [CONTRIBUTING.md](../../CONTRIBUTING.md), [DESIGN.md](../../DESIGN.md), and
   [migration/backup guidance](../migration.md).
4. [Progress ledger](progress.md). Start at the first incomplete module.

## Implementation order

| Order | Module | Outcome |
| --- | --- | --- |
| 01 | [Queue and policy efficiency](modules/01-queue-policy.md) | Claiming one job does bounded work; writes do not monopolize SQLite. |
| 02 | [Sonarr fetch efficiency](modules/02-sonarr-fetch.md) | Bounded concurrent requests and linear episode/file grouping. |
| 03 | [Filesystem scan caching](modules/03-filesystem-cache.md) | Repeated scans avoid repeated directory reads and subtitle hashing. |
| 04 | [Incremental provider sync](modules/04-incremental-sync.md) | Independent providers, durable batches, changes and webhooks converge. |
| 05 | [Startup and sync recovery](modules/05-startup-recovery.md) | Validated existing work can resume without a full catalog rebuild. |
| 06 | [Accurate status and library UI](modules/06-status-ui.md) | Users can see progress, eligibility, and the actual blocking reason. |
| 07 | [Large-library acceptance](modules/07-acceptance.md) | Reproducible scalability and crash-safety evidence gates further features. |
| 08 | [Processing profiles](modules/08-profiles.md) | Libraries can choose processing settings without changing unrelated jobs. |
| 09 | [Checkpoint preemption](modules/09-preemption.md) | Urgent work can interrupt resumable backlog recognition safely. |
| 10 | [Review evidence and undo](modules/10-review-undo.md) | Users can inspect provenance and restore verified Crowbarr outputs. |
| 11 | [Storage accounting and retention](modules/11-storage.md) | Bounded caches and protected recovery artifacts. |
| 12 | [Backup and diagnostics](modules/12-backup-diagnostics.md) | Tested recovery and a bounded, redacted support bundle. |
| 13 | [PostgreSQL decision/optional backend](modules/13-postgresql.md) | A measured decision; optional parity-tested backend only if justified. |

The first four modules form the sync/queue phase; 05–06 cover recovery and status;
07 is the acceptance gate; 08–12 add operational features. PostgreSQL is a separate
decision after these contracts stabilize. Do not add it while optimizing sync.
Module 13 may complete with a documented decision to retain SQLite.

## Rules for the implementing model

- Work on one numbered task at a time. A task should normally change at most three
  production files and approximately 250 production lines, excluding tests/migrations.
  Split a larger task into recorded subtasks before editing; do not silently expand scope.
- First add or identify a test that would fail without the change. Use deterministic
  fixtures; no model downloads, production credentials, or real media in unit tests.
- Read the named routines and their callers before editing. Preserve public response
  fields and old database data unless a module explicitly defines a migration.
- New configuration defaults preserve existing behavior unless the module specifies
  an optimization default. Unknown/invalid settings must fail validation clearly.
- Never weaken `processor.current()`, ownership/digest checks, generation guards,
  language verification, or publication validation to make a test pass.
- Do not replace the UI framework, speech backend, audit algorithm, or packaging system.
  Keep one inference subprocess; request/sync concurrency does not authorize GPU concurrency.
- Do not build later-module stubs. Define the documented interface only when its owner
  module is implemented. A later module extends the interface additively.
- Use additive, transactional, idempotent schema upgrades with legacy database fixtures.
  Do not delete user state or regenerate the database to hide a migration problem.
- Do not push, publish, deploy, alter a live library, or migrate a live database merely
  because a task is complete. Those are separate operator actions. Local tests and
  reversible implementation work do not require repeated permission questions.
- On a contract conflict, failed invariant, or unsupported provider behavior: record
  the evidence and unresolved decision in the ledger, stop dependent work, and obtain
  a decision. Do not invent a new API or bypass a safety check.

## Standard verification

From a Python 3.11–3.13 environment with FFmpeg/FFprobe available:

```sh
python -m pip install -e '.[test]'
python -m pytest PATH_TO_CURRENT_MODULE_TESTS -q
python -m ruff check crowbarr tests integrations packaging
python -m pytest -q
python -m pip wheel --no-deps . -w /tmp/crowbarr-wheels
```

Run targeted checks during each task. Run the full suite and wheel check once at the
module exit, then again only after relevant changes. A network/socket restriction is
an environment failure, not a passing test. Record skips and platform-specific limits.
The existing workflows test Python 3.11, 3.12, and 3.13; retain that matrix.
Run `node --check crowbarr/static/app.js` and visually verify both themes and a narrow
viewport when changing browser code. Use the existing browser check script as a starting
point; do not treat a syntax check as visual verification.
The existing script is not an authentication oracle: verify that it actually enters
the signed-in workspace against the current session-cookie flow, and update its login
setup if necessary. Do not weaken login to make browser automation work.

## Completion and handoff

For each task, record changed files, exact commands, results, and unresolved issues
in [progress.md](progress.md). At module exit also record migration/restart behavior,
API compatibility, measured acceptance results, and rollback instructions. Commit one
coherent module locally after its gate passes. Future release version bumps follow
`CONTRIBUTING.md`; infrastructure-only changes must not bump audit policy. A processing
behavior change must explicitly assess audit and recognition cache invalidation.

Use this continuation prompt:

> Read docs/implementation-guide/README.md, contracts.md, progress.md, and the first
> incomplete module. Implement only its next unchecked task. Preserve all shared
> invariants. Run its targeted tests and update the ledger. Do not start another module,
> publish, deploy, or migrate production. If the task is too large, split it in the ledger
> before editing. At module completion run its full exit gate and report the evidence.

## Primary references

- [SQLite WAL and concurrency](https://www.sqlite.org/wal.html)
- [SQLite backup API](https://www.sqlite.org/backup.html)
- [SQLite query planning](https://www.sqlite.org/eqp.html)
- [Sonarr API documentation](https://sonarr.tv/docs/api/): the deployed integration
  currently uses v3. Confirm the deployed schema; do not switch to a newer API because
  current online documentation defaults to another version.
- [HTTPX client connection pooling](https://www.python-httpx.org/advanced/clients/)
- [PostgreSQL explicit locking](https://www.postgresql.org/docs/current/explicit-locking.html)
- [PostgreSQL SELECT / SKIP LOCKED](https://www.postgresql.org/docs/current/sql-select.html)

These sources explain mechanisms. They do not establish performance on this project;
use Module 07's measurements for that.
