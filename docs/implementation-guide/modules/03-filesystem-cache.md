# 03 — Filesystem scan caching

## Goal and boundary

Reuse filesystem discovery work within a batch and across incremental scans without
changing publication evidence. Module 02 must pass. The default signature path stays
fresh and uncached; optimized scanning must opt into a ScanContext explicitly.

**Read:** `library.allowed/subtitle_sources/signature/retire_stale_output/prepare_media`;
`processor.current/publish_candidate`; `Database.observe/video_revision/set_video_revision`;
`app.py` manual processing, approval, and subtitle-download guards.
**Allowed:** `library.py`, `db.py`; NEW `crowbarr/scan_cache.py`; small caller changes in
`arr.py` only if required to avoid redundant canonicalization. Do not weaken path safety.
**Tests:** library, queue, processor suites; NEW `tests/test_scan_cache.py`.

## Tasks

- [ ] **03.1 — Add ScanContext with counters.** Resolve authorized roots once per context;
  use `os.scandir()` once per parent directory, retaining entry names/stat hints. Cache
  only for that context's lifetime. Keep existing no-context behavior. Test two seasons,
  many episodes per directory, unreadable/disappearing directories, and contexts with
  different settings. Directory invalidation after a new subtitle event must be explicit.

- [ ] **03.2 — Consolidate stat work.** Pass validated media stat/revision through
  preparation and stale-output checks instead of repeating it. Recheck when any side
  effect occurs or a path changes. Do not trust inode/mtime hints for symlink containment
  or publication. Add tests that replace a file or directory/symlink between discovery
  and preparation; it must be rejected or revalidated with the current code's safety.

- [ ] **03.3 — Add durable subtitle hash hints.** Add an additive cache table with the
  exact key fields in contracts.md, hash, cache format version, and last verification.
  Before/after-hash stat must agree; retry a changing file once, then defer it with a
  bounded warning. A missing/bad cache entry is a miss. Enforce the existing 8 MiB
  source limit. A new subtitle, removal, rename, language-tag change, or same-size edit
  with a changed ctime must invalidate the relevant discovery/signature hints.

- [ ] **03.4 — Separate incremental and full verification.** Context exposes
  `revalidate_hashes=True` for every full reconciliation. Incremental scans may reuse
  hints when all keys match. `signature()` without a context always reads current bytes;
  `processor.current()`, approval, publication, and integrity-checked downloads use that
  path. Preserve exact signature serialization so unchanged files do not all requeue.
  Include a test that tampers with subtitle content while restoring size/mtime: a
  publication must still fail, regardless of the scan hint.

- [ ] **03.5 — Batch metadata persistence.** Add bounded preparation persistence helpers
  behind Database for observation/revision/cache updates, at most 200 files per write
  commit. Preserve `observe()` first-seen behavior and wait deadlines for unchanged
  signatures. Do not delay recording a newly observed file until an entire library
  scan completes. Reads/hashing happen outside write transactions. Preserve existing
  standalone helper signatures with compatibility wrappers.

- [ ] **03.6 — Prove reuse and integrity.** Build a generated two-season fixture with
  100 episodes, 100 sidecars, and unrelated files. Count scandir/stat/hash calls for
  first, unchanged incremental, one-sidecar-change, and full-revalidation passes.
  Test hash-cache corruption, partial writes, stale metadata, and cache schema upgrade.

## Tests and acceptance

- Directory enumeration count is one per visited directory per context, not per episode.
- An unchanged incremental pass hashes zero eligible cached sidecar bytes; a changed
  sidecar hashes only affected uncached inputs. A full pass rereads all eligible sidecars.
- Cached and uncached signatures, source ordering, first-seen times, and wait deadlines
  match for the same stable inputs. No processing/audit cache policy bump is needed.
- Output ownership, external-edit refusal, symlink rejection, and fresh pre-publication
  verification pass existing processor/library tests plus the new race tests.
- Each persistence batch covers at most 200 files; no filesystem I/O occurs inside its
  writer transaction. Existing legacy tables/jobs/history survive migration.

Run the new suite plus queue/library/processor/Arr/restart suites and the standard
exit gate. Record operation-count evidence, not only a subjective timing improvement.
Do not remove an old backup or cache just to make the benchmark fit in memory.
