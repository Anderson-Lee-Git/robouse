#!/bin/bash
# One-off full backup: main runs, every worktree's runs, uncommitted hub templates/snippets, BenchFlow dogfood jobs.
set -u
DEST=gs://example-backup-bucket/robouse; P=example-backup-bucket; B=~/benchflow
sync(){ [ -e "$1" ] && gcloud storage rsync -r "$1" "$DEST/$2" --project $P --quiet && echo "ok $2" || echo "skip $1"; }
cd $B/robouse && ./scripts/backup.sh >/dev/null 2>&1 && echo "ok main (backup.sh)"
for w in robouse-embodiments robouse-more-suites robouse-behavior robouse-embodied robouse-benchflow robouse-gpu-track; do sync $B/$w/runs worktrees/$w/runs; done
sync $B/robohub/templates hub-working/robohub-templates
sync $B/scratch/hub-snippets hub-working/hub-snippets
sync $B/robohub-dogfood hub-working/robohub-dogfood
date -u > /tmp/LAST_FULL_BACKUP.txt; gcloud storage cp /tmp/LAST_FULL_BACKUP.txt $DEST/LAST_FULL_BACKUP.txt --project $P --quiet && echo done
