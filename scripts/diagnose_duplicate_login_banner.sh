#!/usr/bin/env bash
# Locate stale VisionPi login banner; only reports file paths and matching lines.
set -u
echo "=== Login banner hooks ==="
find /etc/update-motd.d /etc/profile.d -maxdepth 2 -type f -printf "%m %p\n" 2>/dev/null | sort || true
echo
echo "=== Sources containing the obsolete VisionPi headline ==="
for f in /etc/motd /etc/bash.bashrc /etc/profile "$HOME/.bashrc" "$HOME/.profile" "$HOME/.bash_profile"; do
  [[ ! -f "$f" ]] || grep -HnE "VisionPi|Wolf-powered vision node|10-visionpi" "$f" 2>/dev/null || true
done
sudo grep -RIlE "VisionPi|Wolf-powered vision node|10-visionpi" \
  /etc/update-motd.d /etc/profile.d /etc/ssh /usr/local/bin /usr/local/sbin \
  2>/dev/null | sort -u || true
echo
echo "=== Banner execution overview ==="
ls -l /etc/update-motd.d/ 2>/dev/null || true
echo "Nothing was modified. Disable only the confirmed extra hook, keeping a backup."

