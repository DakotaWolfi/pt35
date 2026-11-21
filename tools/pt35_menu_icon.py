#!/usr/bin/env python3
"""Switch PT35 taskbar launcher icon. Wolf requires our patched taskbar."""
import argparse
import re
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=["wolf", "bars", "skull", "status"])
args = parser.parse_args()
theme = Path.home() / ".config/pt35/theme.toml"
marker = Path.home() / ".local/share/pt35/wolf-bar-installed"

if args.mode == "status":
    value = "stock default"
    if theme.exists():
        m = re.search(r'(?m)^\s*menu_icon\s*=\s*"([^"]+)"', theme.read_text())
        if m: value = m.group(1)
    print(f"Menu icon: {value}. Wolf-capable bar installed: {marker.exists()}")
    raise SystemExit(0)

if args.mode == "wolf" and not marker.exists():
    print("Wolf menu button not yet installed. Run scripts/patch_wolf_taskbar.sh --install after building Rust taskbar.")
    raise SystemExit(1)

theme.parent.mkdir(parents=True, exist_ok=True)
text = theme.read_text() if theme.exists() else ""
theme.with_name(theme.name + ".bak").write_text(text)
m = re.search(r'(?m)^\[bar\][ \t]*$', text)
if m:
    a = m.end()
    n = re.search(r'(?m)^\[', text[a:])
    b = a + n.start() if n else len(text)
    section = text[a:b]
    if re.search(r'(?m)^[ \t]*menu_icon[ \t]*=', section):
        section = re.sub(r'(?m)^[ \t]*menu_icon[ \t]*=.*$', f'menu_icon = "{args.mode}"', section)
    else:
        section += f'\nmenu_icon = "{args.mode}"\n'
    text = text[:a] + section + text[b:]
else:
    text = text.rstrip() + f'\n\n[bar]\nmenu_icon = "{args.mode}"\n'
theme.write_text(text)
print(f"Menu icon -> {args.mode}; should update automatically within seconds.")
