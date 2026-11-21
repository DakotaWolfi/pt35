#!/usr/bin/env bash
# Change PocketTerm35-OS taskbar menu button to a 15x16 wolf pixel icon.
# Uses a separate upstream checkout and recompiles pt35-bar only.
set -euo pipefail
if [ "$(id -u)" = 0 ]; then echo "Run as your normal user"; exit 1; fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$HOME/pt35-wolf-source"
if [ ! -d "$SRC/.git" ]; then git clone https://github.com/therezor/PocketTerm35-OS.git "$SRC"; fi
python3 - "$SRC" <<'PY'
from pathlib import Path
import sys
src=Path(sys.argv[1])
pixel=src/"crates/pt35-ui/src/pixel.rs"
ui=src/"crates/pt35-bar/src/ui.rs"
data=pixel.read_text()
wolf = """
/// Wolf head for the PT35 launcher button, 15 x 16 pixels.
pub const WOLF: &[&str] = &[
    "#.............#",
    "##...........##",
    "###.........###",
    "####.......####",
    "#####.....#####",
    "###############",
    "###############",
    "###...###...###",
    "###...###...###",
    "####.#####.####",
    ".#############.",
    "..####...####..",
    "...####.####...",
    "....#######....",
    ".....#####.....",
    "......###......",
];
"""
if "pub const WOLF:" not in data:
    anchor="pub const PIN:"
    if anchor not in data: raise SystemExit("Cannot locate pixel-art insertion point; upstream changed")
    data=data.replace(anchor,wolf+"\n"+anchor,1)
    pixel.write_text(data)
data=ui.read_text()
old='''        if self.theme.bar.menu_icon == "bars" {'''
new='''        if self.theme.bar.menu_icon == "wolf" {
            pt35_ui::pixel::draw_centred(canvas, pt35_ui::pixel::WOLF, middle, centre, 1, ink);
        } else if self.theme.bar.menu_icon == "bars" {'''
if old in data: data=data.replace(old,new,1); ui.write_text(data)
elif "pt35_ui::pixel::WOLF" not in data: raise SystemExit("Cannot locate menu icon selection; upstream changed")
print("Wolf source patch applied.")
PY
# Keep the installed desktop unchanged until a wolf-capable bar is ready.
if ! command -v cargo >/dev/null; then
  echo "Wolf source staged, but Rust cargo isn't installed. Existing desktop untouched."
  exit 0
fi
# Verify native dependencies before starting a large Rust compilation.
if ! command -v pkg-config >/dev/null || ! pkg-config --exists xkbcommon wayland-client; then
  echo "Missing native build libraries for PocketTerm35-OS."
  echo "Install with:"
  echo "  sudo apt install pkg-config libxkbcommon-dev libwayland-dev"
  exit 1
fi
cd "$SRC"
cargo build --release -p pt35-bar --locked
echo "Wolf bar compiled. Installed desktop has not been changed."
if [[ "$#" -eq 0 || "$1" != "--install" ]]; then
  echo "To install: bash $ROOT/scripts/patch_wolf_taskbar.sh --install"
  exit 0
fi
CURRENT="$(command -v pt35-bar)"
BACKUP="$CURRENT.fmi-before-wolf"
if [[ ! -f "$BACKUP" ]]; then sudo cp -a "$CURRENT" "$BACKUP"; fi
sudo install -m755 "$SRC/target/release/pt35-bar" "$CURRENT"
CONF="$HOME/.config/pt35/theme.toml"
mkdir -p "$(dirname "$CONF")"
[[ -f "$CONF" ]] && cp -a "$CONF" "$CONF.bak.$(date +%Y%m%d-%H%M%S)" || true
python3 - "$CONF" <<'PY'
from pathlib import Path
import re,sys
p=Path(sys.argv[1]); s=p.read_text() if p.exists() else ""
m=re.search(r"(?m)^\[bar\][ \t]*$",s)
if m:
    a=m.end(); n=re.search(r"(?m)^\[",s[a:]); b=a+n.start() if n else len(s)
    section=s[a:b]
    if re.search(r"(?m)^[ \t]*menu_icon[ \t]*=",section):
        section=re.sub(r"(?m)^[ \t]*menu_icon[ \t]*=.*$",'menu_icon = "wolf"',section)
    else: section += '\nmenu_icon = "wolf"\n'
    s=s[:a]+section+s[b:]
else: s=s.rstrip()+'\n\n[bar]\nmenu_icon = "wolf"\n'
p.write_text(s)
PY
mkdir -p "$HOME/.local/share/pt35"
touch "$HOME/.local/share/pt35/wolf-bar-installed"
echo "Wolf installed. The Settings > Wolf / Normal menu entries can now switch the icon."
echo "Rollback executable: sudo cp -a '$BACKUP' '$CURRENT'"
