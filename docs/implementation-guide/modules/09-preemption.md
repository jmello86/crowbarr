# 09 — Checkpoint preemption for urgent work

## Goal and boundary

An eligible manual/import job can yield a running backlog transcription at a durable
chunk boundary. Keep one inference child and never lose completed recognition work.
Module 08 must pass so resume uses the same effective settings contract.

**Read:** `inference.transcribe_bounded/transcribe_windows`; `processor._recognized_words/process`;
`Service.worker/run_job`; `Database.claim/recover/update/record_usage`; existing corrupt
checkpoint and interruption tests in `tests/test_restart.py`.
**Allowed:** these routines; NEW focused control message/exception helper. No backend rewrite.
**Tests:** NEW `tests/test_preemption.py`; progress/restart/queue/processor suites.

## Tasks

- [ ] **09.1 — Define cooperative control.** NEW `PreemptRequested` is an administrative
  outcome, distinct from failure, user cancel, settings replacement, or shutdown. Add a
  per-generation control request and a new `preemptible` stage flag. Use a multiprocessing
  event/control channel or bounded DB check at checkpoints; never send process-name
  kill commands. Default enable only for background origins, when a ready validated
  manual/import job outranks them. Do not preempt urgent work for other urgent work.

- [ ] **09.2 — Yield only after durable chunks.** Extend `transcribe_bounded()` with an
  optional checkpoint callback invoked after the existing atomic chunk write and before
  the next chunk. On a preemption request, raise the administrative exception. Completed
  chunks remain intact; the unfinished chunk may repeat after crash. Existing callbacks
  and transcribe runtime metadata must restore in finally blocks. Windows/sample audit,
  model initialization, audio extraction, alignment, and publication are initially
  non-preemptible; show that accurately rather than force-killing them.

- [ ] **09.3 — Requeue with fencing.** Parent receives/recognizes a cooperative yield,
  waits for child exit, advances generation, and requeues the same job without incrementing
  failure attempts or erasing its directive/signature/profile identity. Preserve completed
  chunks and progress evidence. Permit exactly one urgent claim after the child exits.
  Unexpected process death still follows normal failure/retry rules. Add cancellation
  precedence and settings-change precedence tests.

- [ ] **09.4 — Preserve fairness/accounting.** Add a minimum 60s active-work interval and
  300s preemption cooldown per background job (fake-clock tests). Charge actual time
  spent against the background budget; do not double-charge resumed chunks or charge
  waiting time. Keep existing priority aging so backlog eventually returns. A skip or
  external media change invalidates resumable publication, regardless of saved chunks.

- [ ] **09.5 — Integrate status.** Expose preemptible/non-preemptible stage, a pending
  preemption request, and the `preempted` reason through Module 06. No unmeasured ETA.
  Document that the yield latency is one remaining chunk plus current operation; it
  is not an instant interruption. Keep the chunk duration at its current 300s unless
  a separately measured change is approved and tested.

- [ ] **09.6 — Exercise restart and cache compatibility.** Fake a three-chunk recording:
  finish chunk 1, yield, run an urgent job, restart, resume chunks 2–3, and compare final
  words/output with uninterrupted processing. Corrupt one checkpoint and recompute only
  that chunk. Repeat with an edited source, changed effective profile, full transcript
  cache hit, CPU fallback, cancel during yield, and an old worker attempting late writes.

## Acceptance and exit gate

- One active inference process at all times, including exit/claim races.
- Preemption occurs only at declared durable boundaries; no partial subtitle publication.
- Completed compatible chunks are reused and final output matches uninterrupted fixtures.
- Yield/resume does not exhaust failure attempts or duplicate history/completion entries.
- Manual/import urgency improves without starvation or inaccurate resource accounting.
- Unsupported stages/backends remain safe and report non-preemptibility; do not claim
  support for an untested hardware path.

Run preemption, restart, progress, queue, profiles, processor, and publication suites;
the standard exit gate; repeat Module 07's concurrency/publication subset. Record
operator-visible latency limitations and actual hardware verification separately.
