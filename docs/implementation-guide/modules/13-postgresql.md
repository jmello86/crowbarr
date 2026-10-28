# 13 — PostgreSQL decision and optional backend

## Goal and decision gate

Decide from measurements whether a second backend is justified. Modules 01–12 must be
complete. A written decision to retain SQLite is a valid completed outcome. Do not
migrate production or introduce simultaneous inference workers as part of this module.

SQLite already uses WAL, allowing readers and a writer to overlap, with one writer
at a time. PostgreSQL offers row-level locking and concurrent independent writers.
Neither fixes repeated API calls, unnecessary full scans, or expensive Python loops.

**Read:** Module 07 results; all Database methods and remaining direct SQL in `app.py`,
`catalog.py`, `processor.py`, `service.py`; backup/maintenance contracts; `pyproject.toml`,
Dockerfiles and packaging smoke checks. Primary references are linked in the guide index.

## Tasks

- [ ] **13.1 — Make and record the decision.** Re-run Module 07's workload with at least
  one sync writer, webhook writer, inference progress writer, and concurrent API reads.
  Attribute remaining latency to database locks/transactions versus remote/filesystem/
  CPU work. Trigger an implementation proposal if ordinary batches still fail the
  documented lock/API targets after query/transaction review, or a concrete requirement
  needs multiple independent service writers. Write `docs/database-decision.md` with
  evidence, operational cost, rejected alternatives, and a retain/add decision.
  If retain, finish this module here and do not install PostgreSQL dependencies.

The remaining tasks apply only to an explicitly accepted add-backend decision.

- [ ] **13.2 — Extract a persistence boundary without changing behavior.** Keep Database's
  public facade and move backend SQL behind focused queue/catalog/policy/artifact/sync
  repositories. Remove direct SQL from API/processor/service callers incrementally,
  one repository at a time. First run all tests on SQLite with this abstraction and
  identical results. Avoid a generic SQL-string converter or broad ORM rewrite.

- [ ] **13.3 — Implement migrations/configuration.** Add an optional PostgreSQL dependency
  extra and backend DSN loaded from an environment/secret source, never returned by
  ConfigStore.public/status/diagnostics. Use a separate database and least-privilege
  application role; never reuse another application's tables. Version migrations per
  backend and test rollback-on-failure plus idempotent reopen. Translate SQLite PRAGMAs,
  placeholders, JSON functions, INSERT OR REPLACE/IGNORE, index hints, datetime/boolean
  expressions, generated IDs, and transaction semantics explicitly.

- [ ] **13.4 — Implement queue fencing and maintenance parity.** PostgreSQL claims may
  use row locking / `FOR UPDATE SKIP LOCKED`, but retain a database-enforced single
  inference lease and generation CAS. Two concurrent service instances must not both
  become active inference owners. Replace SQLite service-file-lock assumptions with
  backend-appropriate leases/advisory locking, including expiry/recovery. Keep network
  I/O outside transactions and preserve all sync-revision/publication guards. Test
  connection loss, deadlocks/retry bounds, canceled transactions, and owner death.

- [ ] **13.5 — Add backend parity CI.** Parameterize repository/queue/sync/policy/history/
  profile/artifact/undo tests across SQLite and a disposable PostgreSQL service. Compare
  final logical records, ordering, ownership, and API behavior, not physical schemas.
  Keep SQLite as the default installation. Verify Docker/native optional-dependency
  packaging, TLS settings, connection pooling limits, diagnostics redaction, and unavailable
  database startup/error behavior. PostgreSQL errors may not leak credentials.

- [ ] **13.6 — Build an offline one-way migrator.** Source remains untouched. Acquire
  service/maintenance locks, export a verified Module 12 backup, migrate into a new
  empty destination transactionally, then compare table counts, job signatures/history,
  rule/profile identities, artifacts/digests, pending events, and completed results.
  Preserve absolute media paths. Validate before switching configuration; retain the
  SQLite source and backup for rollback. No dual-write mode, live cutover, or automatic
  destructive downgrade. Backup/restore must understand PostgreSQL consistently before
  this module can pass; reject unsupported format/backend combinations explicitly.

## Acceptance and exit gate

- A retain decision is supported by reproducible measurements and an explicit revisit
  trigger. An add decision includes every remaining task, not just a connecting driver.
- The entire logical behavior suite passes on both backends, including crash windows,
  stale workers, sync/webhook races, undo, retention, and backup/restore.
- Independent writers gain measured concurrency without duplicate inference or relaxed
  publication checks. The comparison uses identical inputs and excludes fixture overhead.
- Migration is offline, repeatable into an empty destination, preserves all required data,
  and has a tested rollback that keeps source data. No operator deployment is implicit.

**Production activation remains a separate operator decision** after all parity,
packaging, migration, backup, and rollback evidence is reviewable.
