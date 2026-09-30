#!/bin/bash
# Kept at this path because the maintainers' cleanup rule runs it from here; the script is tools/ops/backup_all.sh.
exec "$(dirname "$0")/../tools/ops/backup_all.sh" "$@"
