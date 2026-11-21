#!/usr/bin/env bash
# Create an SSH key belonging ONLY to PT35 and configure only this repo to use it.
set -Eeuo pipefail
[[ "$(id -u)" != 0 ]] || { echo "Run as jenna; do not use sudo"; exit 1; }
KEY="$HOME/.ssh/id_ed25519_pt35"
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
if [[ -e "$KEY" || -e "$KEY.pub" ]]; then
  echo "PT35 SSH key already exists. Never overwrite it automatically."
else
  ssh-keygen -t ed25519 -a 64 -C "pt35@$(hostname)" -f "$KEY"
fi
chmod 600 "$KEY"
chmod 644 "$KEY.pub"
echo
echo "Add this PUBLIC key to https://github.com/settings/ssh/new as an Authentication key:"
cat "$KEY.pub"
echo
echo "The private key at $KEY stays on this device; never upload or paste it."
echo "Once you have added the public key, run:"
echo "  cd ~/pt35-migration"
echo "  git config --local core.sshCommand 'ssh -i ~/.ssh/id_ed25519_pt35 -o IdentitiesOnly=yes'"
echo "  git ls-remote git@github.com:DakotaWolfi/pt35.git HEAD"
echo "  bash scripts/publish_recovered_pi4_apps.sh"
echo "The repo-specific Git setting leaves other SSH identities and repositories unchanged."

