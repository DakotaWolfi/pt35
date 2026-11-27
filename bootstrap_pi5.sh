#!/usr/bin/env bash
# Bootstrap PT35 Pi 5 on a freshly flashed Raspberry Pi OS Trixie 64-bit card.
# Usage: bash bootstrap_pi5.sh [--no-upgrade] [--enable-buttons]
set -Eeuo pipefail
[[ "$EUID" -ne 0 ]] || { echo "Run this as your regular user, not with sudo." >&2; exit 1; }
branch="feature/pi5-staged-install"
url="https://github.com/DakotaWolfi/pt35.git"
dest="$HOME/pt35"
sudo apt-get update
sudo apt-get install -y git ca-certificates
if [[ -d "$dest/.git" ]]; then
  [[ "$(git -C "$dest" remote get-url origin)" == "$url" ]] || {
    echo "Existing $dest is from another remote. Refusing to overwrite." >&2; exit 1;
  }
  [[ -z "$(git -C "$dest" status --porcelain)" ]] || {
    echo "Uncommitted changes in $dest; back them up first." >&2; exit 1;
  }
  git -C "$dest" fetch origin "$branch"
  git -C "$dest" checkout "$branch"
  git -C "$dest" pull --ff-only origin "$branch"
elif [[ -e "$dest" ]]; then
  echo "$dest already exists and is not a Git checkout. Refusing to overwrite." >&2
  exit 1
else
  git clone --branch "$branch" "$url" "$dest"
fi
exec bash "$dest/scripts/install_pi5.sh" "$@"
