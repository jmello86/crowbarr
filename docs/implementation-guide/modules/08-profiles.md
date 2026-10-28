# 08 — Per-library processing profiles

## Goal and boundary

Allow explicit processing choices per library/title while preserving global behavior
for existing installations. Module 07 must pass first. Profiles do not change audit
thresholds or introduce new languages/backends.

**Read:** `Settings`, `FINGERPRINT_FIELDS`, `ConfigStore`; `library.signature/prepare_media`;
`Service.worker/run_job`; `processor.current/process/_recognized_words`; app settings,
manual processing and approval handlers; `static/app.js:settingsPage/captureSettings/detail`.
**Allowed:** these files; NEW `crowbarr/profiles.py`; profile persistence migration/helper.
**Tests:** NEW `tests/test_profiles.py`; extend queue/restart/processor/API tests.

## Tasks

- [ ] **08.1 — Define explicit profiles and bindings.** Add profile IDs/revisions/names
  and validated partial overrides plus title/root bindings. Initially allow only model,
  device, compute_type, sampled_audit, refine_generated, generate_over_mismatch, and
  bazarr_download_alternatives. Add `allow_generation` default true; false forbids both
  missing-source generation and generation over a proven mismatch, including manual
  Generate (return a clear 409). Existing global default remains current behavior.
  Do not allow credentials, paths, language, skip/include, resource limits, or arbitrary
  Python/settings keys in an override. Test validation and legacy no-profile defaults.

- [ ] **08.2 — Implement the one resolver.** Follow contracts.md precedence and immutable
  SettingsSnapshot. Resolve canonical root bindings once with safe boundary checks;
  `/tv/Show` must not match `/tv/Showcase`. Validate model/device/compute combinations
  using existing capabilities logic. No-profile fingerprints must match 0.4.14 exactly.
  Separate recognition-affecting settings from publication/audit choices so a generation
  permission toggle does not unnecessarily discard a valid transcript.

- [ ] **08.3 — Use the snapshot everywhere.** Thread one resolved snapshot through
  preparation/signature, candidate validation/claim, child process arguments, current
  checks, cache keys, manual requests/approval, and reports. Store the applied profile
  ID/revision and effective fingerprints per job/run report. An edit that changes
  effective execution settings fences an active affected worker; metadata-only edits
  do not. Unrelated jobs/results keep their identity. Add deterministic
  tests changing a profile at claim and publication boundaries and retrying after restart.

- [ ] **08.4 — Invalidate affected work only.** Binding/profile changes enumerate affected
  identities using Module 06's index and enqueue bounded invalidation through Modules
  01/04. Profile deletion must atomically remove bindings and resolve to inherited defaults;
  do not leave dangling references. Requeue only input/effective-fingerprint changes;
  preserve historical results and recognition caches when compatible.

- [ ] **08.5 — Add authenticated CRUD/UI.** NEW `/api/profiles` GET/POST and
  `/api/profiles/{id}` PUT/DELETE plus `/api/profile-bindings` GET/PUT. Use revision/CAS
  checks for edits (409 on stale revision). Validate payload lengths/keys and return
  effective inherited values without secrets. Add a compact Processing settings panel
  and title/root binding controls; show which profile applies to a job. No presets that
  silently change existing installations. Test escaping, auth, stale edits, and drafts.

- [ ] **08.6 — Assess policy/version migration.** Document `allow_generation` refusal
  behavior and how stored unresolved jobs are reconsidered. Any change to audit verdict
  semantics requires an explicit audit-policy decision under CONTRIBUTING; never bump
  it just because the schema changed. Preserve old checkpoint recognition keys whenever
  effective recognition inputs are identical. Extend user docs with concrete inheritance
  examples and the difference between inclusion rules and processing profiles.

## Acceptance and exit gate

- No profiles/bindings means unchanged behavior, signatures, queue order, and caches.
- Profiles apply identically to automatic, manual, retry, approval, and resumed work.
- Skip/include rules and global resource gates remain authoritative.
- Editing one library profile does not reprocess every library or delete valid history.
- Generation disabled cannot be bypassed through another API endpoint or forced directive.
- Effective settings are reported accurately, including actual runtime fallback separately
  from requested backend. Restart preserves profiles and deterministic resolution.

Run new profile/API tests plus queue, restart, library, Arr, processor, capabilities,
and publication tests; browser verification and standard exit gate. Record any required
policy/cache migration and its tested affected scope before declaring complete.
