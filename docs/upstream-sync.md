# Upstream comparison — 2026-11-25

Compared this Intel fork at `40e53c7` with official
[`amanofvaly/crowbarr`](https://github.com/amanofvaly/crowbarr), using common
ancestor `36359468` (official 0.4.11). The latest official release is
[`v0.4.15`](https://github.com/amanofvaly/crowbarr/releases/tag/v0.4.15), commit
`0011f4d`. Official `main` at `5b3aa0e` adds a release-workflow correction.
Official and fork version numbers are independent.

## Reliability fixes retained in fork 0.4.17

| Area | Backported behavior | Upstream source |
| --- | --- | --- |
| Settings saves | Probe pending video durations only when the minimum duration changes, after returning the response. | `5264122` |
| Waiting queue | Recompute waiting-job deadlines when the Bazarr wait changes; Run next releases the wait; keep manually released jobs released. | `5264122` |
| Activity | List ready jobs ahead of jobs whose wait has not elapsed. | `5264122` |
| Library display | Refresh text nodes in mixed-content headings and fix malformed show-expansion markup. | `5264122` |
| Scanner recovery | Continue retrying even when both the scan and its failure notice encounter database locks. | `5afac62` |
| Plex status | Explain when background work is deferred because Plex cannot be reached. | `cb764eb` |
| Language verification | Try extra distributed probes only when the initial samples contain too little confident speech. | `cb764eb` |

The initial language backport adopted policy `0.3.8`; the complete integration below
adopts policy `0.3.9` and includes both sets of changes.

## Equivalent or more extensive fixes already present

- Official `5afac62` throttles full-library policy refreshes during queue claims.
  This fork already uses bounded, incremental policy projections and per-file claim
  checks, with concurrency and scaling tests. Retain that implementation instead of
  restoring a periodic full-library rewrite.
- Official `7bfcbb7` preserves real stat attributes in the private-file permissions
  test for pytest 9.2. This fork already preserves the complete stat result.
- Official `147bc71` labels saved Bazarr/Plex connections as Configured. The fork
  already has this behavior.

## Full official release integration

The complete official `main` history through `5b3aa0e` is merged after the initial
reliability backports. Fork application version `0.4.17` now includes:

- The redesigned dashboard, library, review and settings UI, including policy previews.
- In-app update checks, transport retries, compatible app updates and rollback.
- Optional refinement installation for CPU/CUDA images; Intel retains its bundled
  XPU-compatible PyTorch and WhisperX packages.
- High Accuracy (off by default) and its speech-filter bypass for full audits,
  including Intel recognition and CPU fallback.
- Missing-section detection and evenly spaced sampling for all audits, adopting
  official audit policy `0.3.9`. Short recordings are audited in full.
- Official release automation, optional dependency splitting and CUDA overlay assets.

## Intel adaptations and preserved fork behavior

- Intel images check `jmello86/crowbarr` releases and recommend versioned
  `ghcr.io/jmello86/crowbarr:VERSION-intel` images. Official CPU/CUDA behavior is
  retained for those image variants.
- The Intel image workflow builds a wheel and update manifest, verifies the manifest
  against the actual image runtime, and publishes them as a fork GitHub release after
  the image checks pass. Version and commit image tags remain available alongside
  `intel` and `latest-intel`. No publication is performed merely by this local merge.
- Update manifests include exact XPU wheel versions, including `torch==2.8.0+xpu`,
  so an incompatible CPU-only runtime cannot be accepted as an Intel app update.
- Intel refinement is reported as bundled, and the optional CPU refinement installer
  is disabled for Intel images. Regenerating the Intel dependency lock keeps its full
  XPU stack instead of splitting Torch into an optional add-on.
- The FP16 normalization fix, CPU fallback reporting, valid-frame clip bounds, sparse
  alignment buffers and CPU DTW workaround remain in the Intel adapter.
- GPU device names, cached memory telemetry, Intel model inventory and discovery
  concurrency controls are retained in the new UI.
- Queue claims retain incremental policy projections and publication fences instead
  of upstream's periodic full-library refresh. Existing scaling and concurrency tests
  continue to cover this behavior.

## Upgrade behavior and workload

Audit policy `0.3.9` reopens review and failed jobs, not completed, unchanged or
explicitly skipped results. Recognition cache version `2` is unchanged. The new
sampling schedule uses roughly 8–18 two-minute samples per film; recordings under
about 27 minutes receive a full audit. This increases recognition work compared with
the old three-sample schedule even with High Accuracy off. High Accuracy additionally
bypasses the speech filter during full audits and holds retimed results for review.
It remains off by default and is not enabled in any running installation by this merge.

The previous server instruction remains in effect: publishing or applying this code
must not update the Unraid container automatically. No live server configuration,
queue, media, or container is changed by this local integration.
