#!/usr/bin/env bash
# Install per-user launchers only. Do not install or restart any PT35 service.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:---bind-r}"
if [[ $# -gt 1 || ( "$MODE" != "--bind-r" && "$MODE" != "--no-bind-r" ) ]]; then
  echo "Usage: $0 [--bind-r|--no-bind-r]" >&2
  exit 2
fi
PYTHON="$(command -v python3)"
"$PYTHON" -c 'import tkinter' >/dev/null 2>&1 || {
  echo "Tkinter missing: sudo apt install python3-tk" >&2
  exit 1
}
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"
TARGET="$HOME/.local/bin/pt35-launcher"
LEGACY="$HOME/.local/bin/pt35-nfc-menu"
SOURCE="$ROOT/tools/pt35_launcher.py"
[[ -f "$SOURCE" ]] || { echo "Missing $SOURCE" >&2; exit 1; }

install_shim() {
  local path="$1"
  local content="$2"
  if [[ -e "$path" || -L "$path" ]]; then
    if ! cmp -s <(printf '%s\n' "$content") "$path"; then
      local backup="$path.backup.$(date +%Y%m%d-%H%M%S)"
      cp -a -- "$path" "$backup"
      echo "Backed up old launcher: $backup"
    fi
  fi
  printf '%s\n' "$content" > "$path.new"
  chmod 0755 "$path.new"
  mv -f -- "$path.new" "$path"
}

printf -v command '#!/usr/bin/env bash\nexec %q %q "$@"' "$PYTHON" "$SOURCE"
install_shim "$TARGET" "$command"

if [[ "$MODE" == "--bind-r" ]]; then
  # Existing button daemon maps R to this path; no daemon modification needed.
  printf -v shim '#!/usr/bin/env bash\nexec %q "$@"' "$TARGET"
  install_shim "$LEGACY" "$shim"
  echo "R button launcher target installed: $LEGACY"
else
  echo "R button binding unchanged"
fi

DESKTOP="$HOME/.local/share/applications/pt35-launcher.desktop"
cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=PT35 Tools
Comment=Touch launcher for NFC, AS7341 and rear LEDs
Exec=$TARGET
Terminal=false
Icon=applications-utilities
Categories=Utility;
EOF
echo "Installed $TARGET"
echo "No services installed or restarted."
