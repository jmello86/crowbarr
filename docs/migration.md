# Migration and backup

## Policy projection migration (0.4.15)

The Module 01 implementation adds cached policy revisions, a dirty-path queue, and a
durable scan cursor. Its schema changes are transactional and additive. Existing
queue states, history, result signatures, and audit/recognition policy versions are
preserved. The first open schedules a bounded rebuild instead of recalculating every
library rule during startup or each job claim.

After upgrading, cached library states may settle over several background batches
(up to 200 files per batch). Claims, retry/manual requests, and publication still
validate the current policy for the individual file. Pausing inference does not pause
policy maintenance. A newly excluded active job is cancelled immediately when its
preference is saved through the dashboard/API. Existing published subtitle files are
not removed by this migration.

Use the complete stopped-service backup procedure below before upgrading. For rollback,
save the new app data, then restore the pre-upgrade app data and its matching old image;
do not assume that downgrading the image alone reverses the new schema/triggers. Test
the rollback with a disposable copy first.

## Existing installation data

Keep the existing data and install the published application. Crowbarr stores its
settings, login credentials, API key, job state, reports, model caches and transcript
checkpoints in its data directory (`/config` in Docker, `/var/lib/crowbarr` by default
on native Linux). Subtitle sidecars remain beside the media.

## Before moving

1. Record application and audit-policy versions, image tag/digest, UID/GID, host
   mounts, container paths, port and GPU selection. Keep the working image available.
2. Record queue totals and representative completed/review jobs in the dashboard.
3. Identify the actual data directory. For Docker, inspect container mounts with
   `docker inspect CONTAINER`; do not infer paths from an example.
4. Preserve the numeric UID/GID and container media paths. Jobs, reports and caches
   contain absolute paths. Changing `/tv` to `/media/tv` is not a transparent move.
   Use the supported mount settings to retain `/tv` and any other existing paths.
5. Disable the old updater, pause the queue in the dashboard and let the active job
   finish if convenient. Pause prevents new claims; stopping can interrupt a chunk.

## Back up

Stop Crowbarr through its manager and confirm it has exited. Back up the entire data
directory while stopped, preserving ownership, permissions and links. On TrueNAS,
take a snapshot of the dataset containing the data after stopping the service.
A snapshot on the same device does not protect against device failure; maintain a
recoverable backup too.

If the data shares a dataset with unrelated files, use a directory backup or restore
only Crowbarr's directory from a snapshot. Do not roll back the entire shared dataset
to recover one application.

For a regular Linux directory, an example is:

```sh
sudo tar --acls --xattrs --numeric-owner -C /srv/crowbarr \
  -cpf /backup/crowbarr-before-upgrade.tar config
```

Replace both paths. Protect backups because they contain credentials. Never copy
only `crowbarr.db` while running: committed changes may be in `crowbarr.db-wal`.
Keep settings, dashboard credentials, the API token, transcripts, reports,
candidates, models and the remaining app data together.

## Switch managers

Follow the public [Docker](docker.md) or [Portainer](nas.md#portainer) instructions.
Point configuration storage at the existing data directory, or a complete
stopped-service copy. Preserve media paths, UID/GID, port and GPU settings.

Keep the old container stopped. Never run two services against the same database,
or independent database copies writing to the same library. Retain the stopped old
container until the replacement has been verified.

## Verify

Check the new published version and container health. Sign in with the existing
account. Verify settings, integrations, API key continuity, queue counts, completed
and review history, and reports. Check media access as the configured user. Resume
the queue if paused and observe a real job reach its normal completion/review state.

An application-only update leaves settled results intact. An audit-policy change
can reopen review/failed jobs as described in the [changelog](../CHANGELOG.md).
Interrupted jobs return to the queue subject to retry limits. Valid recognition
chunks can resume; the unfinished chunk may repeat. An in-memory progress percentage
is not guaranteed to survive exactly.

If an existing installation asks you to create an account, stop and check `/config`.
If jobs show missing media, check container mount paths before resetting or rescanning.
Fix installation defects in the shared release or instructions, rather than patching
a running container.

## Rollback

Stop the replacement and disable its updater. Save its current data before restoring
an older backup, since restoring discards changes made after that backup. Restore
the complete pre-upgrade data with ownership and permissions, then start the matching
old release. Verify health and the dashboard again.

An older image alone does not reverse schema migrations, policy adoption or new
subtitle publications. Verify old-version database compatibility or restore its
matching data backup. App-data rollback does not restore media-side subtitle files;
use media backups/snapshots when those also need reverting. Do not delete existing
subtitles to make a rollback appear healthy.
