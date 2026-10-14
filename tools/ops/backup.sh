#!/bin/bash
# Back up robouse run data to Google Cloud Storage: $ROBOUSE_BACKUP_URI (gs://<bucket>/<prefix>) in the Google Cloud
# project $ROBOUSE_BACKUP_PROJECT. Both come from the environment or, when ROBOUSE_BACKUP_URI is unset, from
# ~/.config/robouse/ops.env (or the file $ROBOUSE_OPS_ENV names), a folder the agent sandbox denies.
#   runs/            every trial (videos, agent output, trajectories, episode traces, verifier results), audit, gallery
#   benchflow-dist/  exported BenchFlow bundles and their `bench eval run` job results
#   tasks/           the task folders as they were at backup time (also in git)
# rsync only uploads new or changed files, so it is cheap to rerun. Nothing is deleted from the bucket.
set -euo pipefail
cd "$(dirname "$0")/../.."
OPS_ENV="${ROBOUSE_OPS_ENV:-$HOME/.config/robouse/ops.env}"
if [ -z "${ROBOUSE_BACKUP_URI:-}" ] && [ -f "$OPS_ENV" ]; then . "$OPS_ENV"; fi
DEST="${ROBOUSE_BACKUP_URI:?set ROBOUSE_BACKUP_URI (gs://bucket/prefix), or put it in ~/.config/robouse/ops.env}"
PROJECT="${ROBOUSE_BACKUP_PROJECT:?set ROBOUSE_BACKUP_PROJECT, or put it in ~/.config/robouse/ops.env}"
for pair in "runs:runs" "benchflow/dist:benchflow-dist" "tasks:tasks"; do
  src="${pair%%:*}"; dst="${pair#*:}"
  [ -d "$src" ] || continue
  gcloud storage rsync -r "$src" "$DEST/$dst" --project "$PROJECT" --quiet
done
date -u +"%Y-%m-%dT%H:%M:%SZ" | gcloud storage cp - "$DEST/LAST_BACKUP.txt" --project "$PROJECT" --quiet
echo "backed up to $DEST"
