#!/bin/bash
# Back up robouse run data to GCS: gs://example-backup-bucket/robouse/
#   runs/            every trial (videos, agent output, trajectories, episode traces, verifier results), audit, gallery
#   benchflow-dist/  exported BenchFlow bundles and their `bench eval run` job results
#   tasks/           the task folders as they were at backup time (also in git)
# rsync only uploads new or changed files, so it is cheap to rerun. Nothing is deleted from the bucket.
set -euo pipefail
cd "$(dirname "$0")/../.."
DEST="${ROBOUSE_BACKUP_URI:-gs://example-backup-bucket/robouse}"
PROJECT="${ROBOUSE_BACKUP_PROJECT:-example-backup-bucket}"
for pair in "runs:runs" "benchflow/dist:benchflow-dist" "tasks:tasks"; do
  src="${pair%%:*}"; dst="${pair#*:}"
  [ -d "$src" ] || continue
  gcloud storage rsync -r "$src" "$DEST/$dst" --project "$PROJECT" --quiet
done
date -u +"%Y-%m-%dT%H:%M:%SZ" | gcloud storage cp - "$DEST/LAST_BACKUP.txt" --project "$PROJECT" --quiet
echo "backed up to $DEST"
