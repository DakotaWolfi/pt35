#!/usr/bin/env bash
# Fresh Raspberry Pi OS Trixie 64-bit -> PT35 Pi 5 software setup.
# Idempotent where possible. Never flash microcontrollers or touch NFC archives.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NO_UPGRADE=0
ENABLE_BUTTONS=0
for arg in "$@"; do
  case "$arg" in
    --no-upgrade) NO_UPGRADE=1;;
    --enable-buttons) ENABLE_BUTTONS=1;;
    *) echo "Unknown option: $arg" >&2; exit 2;;
  esac
done
[[ "$EUID" -ne 0 ]] || { echo "Run as your desktop user, not sudo." >&2; exit 1; }
[[ -r /proc/device-tree/model ]] || { echo "Cannot detect Raspberry Pi board." >&2; exit 1; }
MODEL="$(tr -d '\0' < /proc/device-tree/model)"
[[ "$MODEL" == *"Raspberry Pi 5"* ]] || { echo "Requires Raspberry Pi 5; detected: $MODEL" >&2; exit 1; }
source /etc/os-release
[[ "${VERSION_CODENAME:-}" == "trixie" && "$(dpkg --print-architecture)" == "arm64" ]] || {
  echo "Requires Raspberry Pi OS Trixie (arm64), 64-bit." >&2; exit 1;
}
sudo -v
echo "[1/7] Updating OS packages"
sudo apt-get update
if (( ! NO_UPGRADE )); then sudo apt-get -y full-upgrade; fi
echo "[2/7] Installing dependencies"
sudo apt-get install -y git ca-certificates python3 python3-pip python3-venv \
  python3-evdev python3-smbus2 python3-lgpio python3-gpiozero python3-tk \
  i2c-tools raspi-utils jq xdotool network-manager openssh-client python3-pil python3-pil.imagetk
if apt-cache show wtype >/dev/null 2>&1; then sudo apt-get install -y wtype; fi
echo "[3/7] Configuring I2C and hardware-access groups"
CONFIG="/boot/firmware/config.txt"
[[ -f "$CONFIG" ]] || { echo "Missing $CONFIG" >&2; exit 1; }
if ! grep -Eq '^[[:space:]]*dtparam=i2c_arm=on([[:space:]]*(#.*)?)?$' "$CONFIG"; then
  sudo cp -a "$CONFIG" "$CONFIG.pt35-backup-$(date +%Y%m%d-%H%M%S)"
  echo 'dtparam=i2c_arm=on' | sudo tee -a "$CONFIG" >/dev/null
fi
sudo usermod -aG input,i2c "$USER"
mkdir -p "$HOME/.local/bin" "$HOME/.config/systemd/user" \
  "$HOME/pt35-nfc/archive" "$HOME/.local/share/pt35"
echo "[4/7] Installing PT35 buttons and NFC components"
install -m 0755 "$ROOT/services/pt35-buttons.py" "$HOME/.local/bin/pt35-buttons.py"
install -m 0644 "$ROOT/systemd/user/pt35-buttons.service" \
  "$HOME/.config/systemd/user/pt35-buttons.service"
# Keep archives/configuration. Update tracked NFC software from the source tree.
for name in pt35_nfc.py nfcv_scan.py nfcv_dump.py; do
  if [[ -f "$HOME/pt35-nfc/$name" ]]; then
    cp -a "$HOME/pt35-nfc/$name" "$HOME/.local/share/pt35/$name.backup"
  fi
  install -m 0755 "$ROOT/nfc/$name" "$HOME/pt35-nfc/$name"
done
bash "$ROOT/scripts/install_nfc_gui.sh"
# Button action expects this path, so create a menu wrapper if not already present.
if [[ ! -e "$HOME/.local/bin/pt35-nfc-menu" ]]; then
  cat > "$HOME/.local/bin/pt35-nfc-menu" <<'EOF'
#!/bin/sh
exec "$HOME/.local/bin/pt35-nfc-gui" "$@"
EOF
  chmod +x "$HOME/.local/bin/pt35-nfc-menu"
fi
echo "[5/7] Fetching Collar Pet integration sources"
CROOT="$HOME/src/collar-pet"
mkdir -p "$HOME/src"
if [[ -d "$CROOT/.git" ]]; then
  if [[ "$(git -C "$CROOT" remote get-url origin)" != "https://github.com/DakotaWolfi/collar-pet.git" ]]; then
    echo "Unexpected origin for $CROOT; refusing to update." >&2; exit 1
  fi
  if [[ -n "$(git -C "$CROOT" status --porcelain)" ]]; then
    echo "Local changes in $CROOT; refusing to overwrite." >&2; exit 1
  fi
  git -C "$CROOT" pull --ff-only
elif [[ -e "$CROOT" ]]; then
  echo "Non-git directory $CROOT exists; refusing to overwrite." >&2; exit 1
else
  git clone https://github.com/DakotaWolfi/collar-pet.git "$CROOT"
fi
echo "[6/7] Installing Collar Pet desktop and PetMind tools"
# Use vetted PT35-targeted installation helpers from the project's own repository.
bash "$ROOT/scripts/setup_pi5_collar_link.sh"
bash "$CROOT/pt35/Desktop/Collar_Pet/install-pm35-collarpet-dashboard.sh"
install -m 0755 "$CROOT/pt35/training/cp-petmind-training" "$HOME/.local/bin/cp-petmind-training"
bash "$CROOT/pt35/scripts/update-pt35-petmind-training-ui-v2.sh"
bash "$CROOT/pt35/scripts/add-petmind-training-desktop-shortcut.sh"
# Install optional Vision repo as source reference, not the stereo headset runtime.
VROOT="$HOME/src/vision_pi"
if [[ -d "$VROOT/.git" ]]; then
  if [[ "$(git -C "$VROOT" remote get-url origin)" == "https://github.com/DakotaWolfi/vision_pi.git" && -z "$(git -C "$VROOT" status --porcelain)" ]]; then
    git -C "$VROOT" pull --ff-only
  else
    echo "Vision repo has a different remote or local edits; leaving it unchanged."
  fi
elif [[ ! -e "$VROOT" ]]; then
  git clone https://github.com/DakotaWolfi/vision_pi.git "$VROOT"
fi
echo "[7/7] Preparing services and diagnostics"
systemctl --user daemon-reload
if (( ENABLE_BUTTONS )); then
  systemctl --user enable pt35-buttons.service
  echo "Button service enabled for the next user session."
else
  echo "Button service staged but not enabled (pass --enable-buttons after testing the USB controller)."
fi
bash "$ROOT/scripts/pi5_doctor.sh" || true
cat <<'EOF'

INSTALLATION FINISHED (software baseline, hardware validation pending).
Reboot for I2C and group permissions.
Then run:  bash ~/pt35/scripts/pi5_doctor.sh
Optional:  systemctl --user enable --now pt35-buttons.service

NOT AUTOMATICALLY INSTALLED:
- Pi 5 WS2812 LED backend (Pi 4 DMA service is incompatible)
- MAX17048 native DT overlay (existing overlay is BCM2711 only)
- Old GPIO17 PWM fan service (Pi 5 Active Cooler manages itself)
- Remote Eye controller / device-local startup assets not yet in pt35 repo
EOF
