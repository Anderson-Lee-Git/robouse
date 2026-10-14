#!/bin/bash
# Full backup: this checkout's run data (backup.sh), the runs/ folder of every other worktree of this repository, and
# extra folders. Settings come from the environment or ~/.config/robouse/ops.env, as for backup.sh:
#   ROBOUSE_BACKUP_URI, ROBOUSE_BACKUP_PROJECT  the bucket prefix and project (required)
#   ROBOUSE_BACKUP_WORKTREES                    worktree folder names to back up, space-separated (default: all)
#   ROBOUSE_BACKUP_EXTRA                        more folders, space-separated "<local path>:<path in the bucket>" pairs
set -u
cd "$(dirname "$0")/../.."
OPS_ENV="${ROBOUSE_OPS_ENV:-$HOME/.config/robouse/ops.env}"
if [ -z "${ROBOUSE_BACKUP_URI:-}" ] && [ -f "$OPS_ENV" ]; then . "$OPS_ENV"; fi
DEST="${ROBOUSE_BACKUP_URI:?set ROBOUSE_BACKUP_URI (gs://bucket/prefix), or put it in ~/.config/robouse/ops.env}"
P="${ROBOUSE_BACKUP_PROJECT:?set ROBOUSE_BACKUP_PROJECT, or put it in ~/.config/robouse/ops.env}"
export ROBOUSE_BACKUP_URI ROBOUSE_BACKUP_PROJECT
sync(){ [ -e "$1" ] && gcloud storage rsync -r "$1" "$DEST/$2" --project "$P" --quiet && echo "ok $2" || echo "skip $1"; }
./tools/ops/backup.sh >/dev/null 2>&1 && echo "ok main (backup.sh)"
here="$(pwd -P)"
git worktree list --porcelain | sed -n 's/^worktree //p' | while read -r w; do
  [ "$(cd "$w" 2>/dev/null && pwd -P)" = "$here" ] && continue
  name="$(basename "$w")"
  if [ -n "${ROBOUSE_BACKUP_WORKTREES:-}" ]; then
    case " $ROBOUSE_BACKUP_WORKTREES " in *" $name "*) ;; *) continue ;; esac
  fi
  sync "$w/runs" "worktrees/$name/runs"
done
for pair in ${ROBOUSE_BACKUP_EXTRA:-}; do sync "${pair%%:*}" "${pair#*:}"; done
date -u > /tmp/LAST_FULL_BACKUP.txt; gcloud storage cp /tmp/LAST_FULL_BACKUP.txt "$DEST/LAST_FULL_BACKUP.txt" --project "$P" --quiet && echo done
