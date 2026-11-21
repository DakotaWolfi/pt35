#!/usr/bin/env bash
# Pull existing PT35 Collar Pet GUI sources, without touching private configuration.
set -Eeuo pipefail
if [[ "$(id -u)" == 0 ]]; then echo "Run as regular user"; exit 1; fi
DEST="$HOME/pt35-legacy-collarpet"
if [[ -d "$DEST/.git" ]]; then
  git -C "$DEST" pull --ff-only
else
  git clone --filter=blob:none --sparse https://github.com/DakotaWolfi/collar-pet.git "$DEST"
  git -C "$DEST" sparse-checkout set pt35/link pt35/training
fi
mkdir -p "$HOME/.local/bin"
if [[ -e "$HOME/.config/collarpet/link.conf" ]]; then
  if [[ ! -e "$HOME/.local/bin/cp-dashboard" ]]; then
    cat > "$HOME/.local/bin/cp-dashboard" <<EOF
#!/bin/sh
exec /usr/bin/python3 "$DEST/pt35/link/dashboard.py" "\$@"
EOF
    chmod +x "$HOME/.local/bin/cp-dashboard"
  fi
  if [[ ! -e "$HOME/.local/bin/cp-petmind-training" ]]; then
    cat > "$HOME/.local/bin/cp-petmind-training" <<EOF
#!/bin/sh
exec /usr/bin/python3 "$DEST/pt35/training/cp-petmind-training" "\$@"
EOF
    chmod +x "$HOME/.local/bin/cp-petmind-training"
  fi
  echo "Existing Collar Pet config found. Non-overwriting shortcuts are ready."
else
  echo "Sources downloaded, but no ~/.config/collarpet/link.conf present."
  echo "Dashboard/training shortcuts NOT installed; migrate config and dependencies separately."
fi
echo "Original old apps: $DEST/pt35/link and $DEST/pt35/training"
echo "No private keys, archive data, or configuration files were copied."
