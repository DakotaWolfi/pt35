#!/bin/bash
set -euo pipefail
cd /home/jenna/pt35
test "$(id -un)" = jenna || { echo 'Updater must run as jenna'; exit 1; }
test "$(git branch --show-current)" = feature/fmi-print-station || { echo 'Unexpected branch'; exit 1; }
test -z "$(git status --porcelain --untracked-files=no)" || { echo 'Tracked files changed, skipping'; exit 1; }
git fetch --quiet --no-tags origin feature/fmi-print-station
old=$(git rev-parse HEAD)
new=$(git rev-parse origin/feature/fmi-print-station)
test "$old" != "$new" || { echo 'Already current'; exit 0; }
git merge-base --is-ancestor "$old" "$new" || { echo 'Non-fast-forward, skipping'; exit 1; }
for f in app.py epaper_test.py display_epaper.py; do
  if git cat-file -e "$new:print_station/$f" 2>/dev/null; then
    git show "$new:print_station/$f" | python3 -c 'import ast,sys; ast.parse(sys.stdin.read())'
  fi
done
git merge --ff-only "$new"
mkdir -p /home/jenna/.local/state/fmi-print-station
printf '%s\n' "$new" > /home/jenna/.local/state/fmi-print-station/revision
echo "Updated $old -> $new"
