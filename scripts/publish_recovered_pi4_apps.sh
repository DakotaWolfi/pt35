#!/usr/bin/env bash
# Stage and publish recovered Pi4 application source in a reviewable branch.
# Requires the PT35 repo checkout and GitHub SSH authentication.
# No archives, config, private keys, .env, dumps, screenshots, database files.
set -Eeuo pipefail
[[ "$(id -u)" != 0 ]] || { echo "Run as normal user"; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$HOME/pt35-old-recovery/pt35-nfc-bench"
[[ -d "$SOURCE/nfc" && -d "$SOURCE/tools" ]] || { echo "Recover the Pi4 source first"; exit 1; }
cd "$ROOT"
[[ -d .git ]] || { echo "Not a Git checkout"; exit 1; }
if [[ -n "$(git status --porcelain)" ]]; then
 echo "Working tree has changes. Commit or stash them first; no action taken."; exit 1;
fi
echo "Checking GitHub SSH authentication..."
if ! git ls-remote git@github.com:DakotaWolfi/pt35.git HEAD >/dev/null; then
 echo "GitHub SSH auth failed. Run scripts/setup_pt35_github_key.sh first."; exit 1
fi
git fetch origin main
BRANCH="recover/pi4-apps"
if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  echo "Local branch $BRANCH already exists. Reuse manually or delete after review."; exit 1
fi
git switch -c "$BRANCH" origin/main
TARGET="$ROOT/legacy/pi4"
mkdir -p "$TARGET/nfc" "$TARGET/tools" "$TARGET/tests"
# Curated, top-level Python source only: do not recurse into user captures.
for item in nfc tools tests; do
  find "$SOURCE/$item" -maxdepth 1 -type f -name "*.py" -exec cp -n -t "$TARGET/$item" -- {} +
done
cat > "$TARGET/README.md" <<'EOF'
# Original PT35 Pi 4 applications — recovered baseline

This directory contains **source-only** snapshots copied from the original
Pi 4 `pt35-nfc-bench` tree. They are historical references, not the live Pi 5
entrypoints. The old system had an NFC reader GUI, scan/poll backend,
AS7341 graphical analyser, and its own tools launcher.

Do not directly enable the original I2C reader daemon on Pi 5 without
checking bus contention, RF shutdown paths and compatibility.

Private archives, NFC dumps, SSH keys, credentials and machine configuration
were deliberately excluded.
EOF
git add -- legacy/pi4
echo "=== Staged files ==="
git diff --cached --name-only
echo "=== Sensitive-source audit (review any matches before continuing) ==="
# Avoid exposing suspected secrets on screen or in CI logs: print only paths.
if git diff --cached --name-only -z | xargs -0 -r grep -IlE \
 "(BEGIN (OPENSSH|RSA|EC|DSA) PRIVATE KEY|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16})" \
 | tee /tmp/pt35-recovery-secret-matches.txt | grep -q .; then
 echo "Possible credentials detected: STOP. Inspect /tmp/pt35-recovery-secret-matches.txt locally."; exit 1
fi
# Re-assert there are only allowed files.
if git diff --cached --name-only | grep -Ev '^legacy/pi4/(nfc|tools|tests)/[^/]+\.py$|^legacy/pi4/README\.md$' ; then
 echo "Unexpected staged path; aborting."; exit 1
fi
read -r -p "Review files above. Type PUBLISH to commit and push source-only branch: " ACCEPT
[[ "$ACCEPT" == "PUBLISH" ]] || { echo "Staged only; no push."; exit 1; }
git -c user.name="$(git config user.name || echo PT35)" \
    -c user.email="$(git config user.email || echo pt35@users.noreply.github.com)" \
    commit -m "Recover original Pi4 NFC and spectral application sources"
git push -u origin "$BRANCH"
echo "Pushed $BRANCH to GitHub. Review diff, then open PR into main."
echo "Working tree now on branch $BRANCH; switch back with git switch main."

