#!/usr/bin/env bash
# Recover PocketTerm35-OS launcher button from unsupported "wolf" theme value.
set -euo pipefail
CONF="$HOME/.config/pt35/theme.toml"
mkdir -p "$(dirname "$CONF")"
if [ -f "$CONF" ]; then cp -a "$CONF" "$CONF.bak.$(date +%Y%m%d-%H%M%S)"; fi
python3 - "$CONF" <<'PY'
from pathlib import Path
import re,sys
p=Path(sys.argv[1]); s=p.read_text() if p.exists() else ""
m=re.search(r"(?m)^\[bar\][ \t]*$",s)
if m:
    a=m.end(); n=re.search(r"(?m)^\[",s[a:]); b=a+n.start() if n else len(s)
    part=s[a:b]
    if re.search(r"(?m)^[ \t]*menu_icon[ \t]*=",part):
        part=re.sub(r"(?m)^[ \t]*menu_icon[ \t]*=.*$",'menu_icon = "bars"',part)
    else: part += '\nmenu_icon = "bars"\n'
    s=s[:a]+part+s[b:]
else: s=s.rstrip()+'\n\n[bar]\nmenu_icon = "bars"\n'
p.write_text(s)
print("PT35 desktop launcher icon reset to supported 'bars'.")
PY
echo "This only changes theme settings; no keyboard, battery or LED modifications."
echo "If the launcher is still inaccessible after a logout/login, collect the user service logs."
