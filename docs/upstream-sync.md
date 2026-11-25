# Upstream comparison — 2026-11-25

Compared this Intel fork at `40e53c7` with official
[`amanofvaly/crowbarr`](https://github.com/amanofvaly/crowbarr), using common
ancestor `36359468` (official 0.4.11). The latest official release is
[`v0.4.15`](https://github.com/amanofvaly/crowbarr/releases/tag/v0.4.15), commit
`0011f4d`. Official `main` at `5b3aa0e` adds a release-workflow correction.
Official and fork version numbers are independent.

## Fixes applied in fork 0.4.17

| Area | Backported behavior | Upstream source |
| --- | --- | --- |
| Settings saves | Probe pending video durations only when the minimum duration changes, after returning the response. | `5264122` |
| Waiting queue | Recompute waiting-job deadlines when the Bazarr wait changes; Run next releases the wait; keep manually released jobs released. | `5264122` |
| Activity | List ready jobs ahead of jobs whose wait has not elapsed. | `5264122` |
| Library display | Refresh text nodes in mixed-content headings and fix malformed show-expansion markup. | `5264122` |
| Scanner recovery | Continue retrying even when both the scan and its failure notice encounter database locks. | `5afac62` |
| Plex status | Explain when background work is deferred because Plex cannot be reached. | `cb764eb` |
| Language verification | Try extra distributed probes only when the initial samples contain too little confident speech. | `cb764eb` |

The language change adopts official audit policy `0.3.8`. On upgrade, existing
review and failed jobs are reopened; completed, unchanged and deliberately skipped
results are not reopened. Recognition cache version `2` is preserved.

## Equivalent or more extensive fixes already present

- Official `5afac62` throttles full-library policy refreshes during queue claims.
  This fork already uses bounded, incremental policy projections and per-file claim
  checks, with concurrency and scaling tests. Retain that implementation instead of
  restoring a periodic full-library rewrite.
- Official `7bfcbb7` preserves real stat attributes in the private-file permissions
  test for pytest 9.2. This fork already preserves the complete stat result.
- Official `147bc71` labels saved Bazarr/Plex connections as Configured. The fork
  already has this behavior.

## Changes kept out of this fixes-only backport

- The upstream UI redesign and in-app updater are separate features. Its updater
  targets official CPU/CUDA releases, whereas this fork uses the verified Intel
  image workflow. Updating the fork continues through its container image.
- Upstream's optional refinement installer and reduced CPU/CUDA dependency locks
  are packaging changes. The Intel image must retain its XPU PyTorch runtime and
  bundled alignment dependencies.
- High Accuracy, missing-section detection, and audit policy `0.3.9` change audit
  behavior and processing cost. Official 0.3.9 uses roughly 8–18 two-minute samples
  per film and full audits for recordings under about 27 minutes. This backport
  retains the fork's current sampling behavior; a full feature import needs a
  separate review of Intel speech-filter handling and workload implications.
- Official release-automation changes and the CUDA overlay Dockerfile target
  upstream's distribution. The fork retains its Intel publication workflow.

No server configuration or running container is changed by applying this backport.
