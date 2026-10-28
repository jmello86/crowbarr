# 07 — Large-library and failure acceptance gate

## Goal and boundary

Establish repeatable end-to-end evidence before adding processing features. Modules
01–06 must pass. Fix defects in their owning module, rerun affected gates, then return
here. Do not proceed to profiles while this gate is red.

**Read:** all prior exit gates; `tests/test_arr.py`, `test_queue.py`, `test_restart.py`,
`test_processor.py`; `.github/workflows/test.yml`; `packaging/intel_smoke.py`.
**Allowed:** NEW `tests/scale/`, `scripts/benchmark_sync.py`, `docs/performance.md`, test
configuration/workflow changes. Production fixes must be narrowly attributed and recorded.

## Tasks

- [ ] **07.1 — Build deterministic generators.** A small CI case has 5,000 catalog files;
  a dedicated scale case has 150,000 files, 3,250 shows, 6,000 films, shared episode files,
  Unicode titles, unmonitored items, unknown/non-English audio, and 35,000 pending jobs.
  Specify whether 150,000 includes films (it must in recorded totals). Fixed seed and
  unique IDs make datasets reproducible. Do not commit generated DBs, production paths,
  subtitles, secrets, or models. Use a small real temporary filesystem for correctness
  and explicitly labeled virtual/generated I/O for large synthetic load.

- [ ] **07.2 — Add independent instrumentation.** Record API calls/retries/peak concurrent
  requests, directories visited, stat calls, hash bytes, SQL statements/VM work, writer
  lock acquisition and hold duration, rows applied, wall time, process RSS, and time to
  first claim. Do not measure only a SELECT. Count transaction duration from actual
  acquire through commit/rollback. Distinguish parent service memory from inference
  children and fixture-generator memory. Save machine/dependency/SQLite/filesystem data.

- [ ] **07.3 — Exercise cold and warm sync.** Benchmark current release commit
  `2b6f57b6d0ccd525bab19abb82a92803d00bf5ec` and the new implementation on identical
  isolated datasets. Cases: initial full sync; unchanged incremental; one changed file;
  one imported episode; a subtitle arriving; explicit full revalidation; concurrent
  Sonarr/Radarr. Keep network latency/input contents/worker settings identical. A
  baseline stopped at a documented timeout is censored evidence, not a fabricated ratio.

- [ ] **07.4 — Exercise failure/concurrency.** Inject events during every sync phase,
  provider timeouts/401/429/503, partial inventories, configuration and monitoring
  changes, directory loss, rule changes, cancellation, restart, and service shutdown.
  Concurrently issue API reads and four claim attempts. Verify catalog/job/history
  counts, preserved input/output hashes, and no stale-generation publications.
  Use controlled process termination only for owned fixture processes in disposable data.

- [ ] **07.5 — Define CI tiers.** Normal CI runs bounded operation-count assertions and
  small race tests. Add a separate opt-in/nightly scale job for the 150,000-file workload,
  with generated artifacts as expiring CI outputs. Keep normal inference smoke checks
  and Python 3.11–3.13 matrix. No unit test downloads a speech model. Real CPU/XPU
  inference is a separately labeled installed-runtime check.

- [ ] **07.6 — Publish evidence and the database decision input.** Write sanitized results
  in `docs/performance.md` with exact commands, seed, commit, environment, three runs
  per timing case, median/range, and limits. Include a failure matrix and remaining
  bottlenecks. State whether database lock contention remains material after fixing
  API/filesystem/Python work. This informs Module 13; it does not authorize migration.

## Fixed acceptance targets

Operation-count/race guarantees below are hard gates. Timing/RSS targets are measured
on the documented dedicated reference environment, not assertions on shared CI runners.
If a target fails, investigate and record a decision; do not silently loosen it.

| Scenario | Required result |
| --- | --- |
| Idle claim | Zero full policy/catalog loads; bounded candidate/policy work. |
| Batching | At most 200 files per write commit; no remote/filesystem discovery inside locks. |
| Requests | Configured provider bound and global cap 8 respected; bounded submitted futures. |
| Fetch phase with simulated 50ms request latency | At least 3x serial throughput with workers=4, identical results. |
| Warm unchanged incremental | Zero cached subtitle bytes rehashed; no unchanged catalog rewrite or settled-job reset. |
| Startup | First ready, validated existing job claim within 30s with responsive managers, before full sync ends. |
| Writer locks | p95 hold under 100ms and maximum under 1s for ordinary apply/claim batches on reference storage. |
| API | Status/title/files first page p95 under 500ms while syncing on the reference host. |
| Memory | Service parent RSS below 512 MiB in the synthetic 150,000-file test, excluding inference and fixture server. |
| Safety | Zero lost imports, false deletions, duplicate current jobs, or forbidden publications in the failure matrix. |

First-pass filesystem timing depends on actual storage; report it separately. Synthetic
speed does not establish performance on a NAS, and passing HTTP health does not prove
subtitle correctness. Real-media acceptance uses operator-selected test copies and
records processing result, actual backend, original-file hashes, and output provenance.

**Exit:** all prior gates plus this matrix pass; evidence is reproducible; unresolved
correctness decisions are empty. Record remaining performance limitations explicitly.
