# 10 — Review evidence, publication history, and undo

## Goal and boundary

Explain existing decisions and provide verified recovery of Crowbarr's own output.
Do not change audit verdicts or overwrite authored/manual edits. Module 09 must pass;
the artifact contracts introduced here are mandatory inputs to retention and backup.

**Read:** `processor.process/publish_candidate/review_candidate_path/new_review_candidate_path`; `Database.register_artifact/
owns_output/update/restore_results/skip`; app job-detail/download/approve handlers;
`static/app.js:detail/measureTable/perform`; `integrations.deliver_plex`.
**Allowed:** those files; NEW `crowbarr/artifacts.py`; publication-history migration.
**Tests:** NEW `tests/test_publication_history.py`, `tests/test_undo.py`; existing publication tests.

## Tasks

- [ ] **10.1 — Define versioned provenance and artifact records.** Add the shared
  `publication_events`/`managed_artifacts` schema. Store event ID, job/generation, media
  revision, input signature, source kind/digest, effective profile/settings identity,
  application/audit/recognition versions, output digest, artifact reference, operation,
  and timestamps. Treat actual backend/fallback as distinct from requested settings.
  Avoid duplicating transcript/subtitle text in database summaries. Test migration from
  old reports, absent optional fields, and idempotent ownership registration.

- [ ] **10.2 — Make previous outputs immutable.** Replace the single overwritten
  `<job_id>.srt` backup slot with uniquely identified, digest-verified version artifacts.
  Register old backups only if their provenance/ownership can be proved; otherwise
  preserve them as unverified and mark undo unavailable. Never fabricate missing prior
  versions. Extend the existing publication journal so crash recovery can distinguish
  intent, private backup committed, media replacement, and completed event.

- [ ] **10.3 — Add bounded review summaries.** Derive a versioned summary from existing
  audit reports: action (kept/repaired/generated/review), selected source, evidence
  counts/timing measurements, effective profile, actual backend/fallback, and up to
  five representative matched-cue comparisons. Values absent in old reports remain
  unknown. Do not call the model or re-audit just to open Details. Large evidence stays
  behind a paginated authenticated endpoint; limit cue text and escape it in the UI.

- [ ] **10.4 — Implement transactional undo intent.** NEW
  `POST /api/jobs/{id}/undo` takes an exact prior event ID and expected current output
  digest. Acquire the shared maintenance/job guard, reject an active/replaced job,
  verify compatible media revision, current inclusion policy, current owned output,
  target digest, safe paths, and no symlinks. Persist intent and a backup of current
  output before atomic replacement; journal completion afterward. Recheck generation
  and replacement digest. Recover crashes on either side of the rename without losing
  either version. Never infer a target from an arbitrary path supplied by the client.

- [ ] **10.5 — Define post-undo state.** Record undo as an administrative restoration,
  never as a newly passed audit. Preserve old completion/history evidence. Use the
  existing deliberate set-aside semantics for the exact current input signature so an
  automatic scan cannot immediately overwrite the user's restoration; explicit retry
  or changed inputs may requeue. Keep current output digest/download provenance accurate.
  Refresh Plex through the existing delivery path only after a successful restore.
  Test repeated undo, stale requests (409), missing versions, and change-after-preview.

- [ ] **10.6 — Add UI and verify failures.** Details shows summary, bounded comparisons,
  publication versions, exact target, and a concrete undo preview. Enable Restore only
  when server eligibility says it is valid; the server still rechecks. Test auth,
  path traversal, external edits, symlinks, mismatched hashes, disk-full/write refusal,
  profile change, rule skip, active inference, and old-worker completion races.

## Acceptance and exit gate

- Opening Details adds no inference/provider calls and handles legacy reports safely.
- An unchanged owned output can be restored to a verified previous compatible version.
- An authored file, external edit, symlink, wrong recording, stale generation, or
  unverified backup is never overwritten. Failed undo preserves recoverable versions.
- Every publication/undo crash window recovers to a known file and journal state;
  a DB transaction alone is not treated as atomic with filesystem replacement.
- Restoration survives restart/scan without a misleading audit-pass claim or immediate
  automatic replacement. Current and historical reports remain truthful.
- Required artifacts are registered/pinned for Module 11; unavailable legacy recovery
  is reported honestly. No audit-policy bump for evidence display alone.

Run new history/undo suites plus processor, restart, profiles, library, API, and integrity
tests; browser verification and standard exit gate. Document undo scope and explain
that app-data rollback alone does not restore media-side subtitle publications.
