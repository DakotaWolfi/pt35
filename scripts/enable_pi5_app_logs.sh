#!/usr/bin/env bash
# Add error logging for exact Pi4 apps and make desktop failures diagnosable.
# Original app files remain untouched; log wrappers run in existing GUI session.
set -Eeuo pipefail
[[ $(id -u) != 0 ]] || { echo "Run without sudo"; exit 1; }
APPDIR="$HOME/.local/bin"
LOGDIR="$HOME/.local/state/pt35/apps"
mkdir -p "$APPDIR" "$LOGDIR"
for app in cp-dashboard cp-petmind-training pt35-eye-control; do
  [[ -x "$APPDIR/$app" ]] || { echo "Missing app: $APPDIR/$app"; exit 1; }
done
for pair in 'cp-dashboard collarpet' 'cp-petmind-training trainer' 'pt35-eye-control eye'; do
  read -r app name <<< "$pair"
  cat > "$APPDIR/pt35-run-$name" <<EOF
#!/usr/bin/env bash
# Preserve the actual Pi4 executable, log any startup traceback.
exec "$APPDIR/$app" "\$@" >> "$LOGDIR/$name.log" 2>&1
EOF
  chmod 755 "$APPDIR/pt35-run-$name"
done
echo "Diagnostic launchers installed. GUI paths:"
for name in collarpet trainer eye; do echo "  $APPDIR/pt35-run-$name"; done
echo "Logs (do not post raw config values): $LOGDIR/"
echo "Refresh menu: bash scripts/install_pi5_shell.sh"
