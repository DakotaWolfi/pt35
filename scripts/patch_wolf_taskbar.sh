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
CONF="$HOME/.config/pt35/theme.toml"
mkdir -p "$(dirname "$CONF")"
if [ -f "$CONF" ]; then cp -a "$CONF" "$CONF.bak.$(date +%Y%m%d-%H%M%S)"; fi
python3 - "$CONF" <<'PY'
from pathlib import Path
import re,sys
p=Path(sys.argv[1]); s=p.read_text() if p.exists() else ""
if re.search(r"(?m)^\[bar\]\s*$",s):
    m=re.search(r"(?m)^\[bar\]\s*$",s)
    a=m.end(); n=re.search(r"(?m)^\[",s[a:]); b=a+n.start() if n else len(s)
    segment=s[a:b]
    if re.search(r"(?m)^menu_icon\s*=",segment):
        segment=re.sub(r"(?m)^menu_icon\s*=.*$",'menu_icon = "wolf"',segment)
    else: segment += '\nmenu_icon = "wolf"\n'
    s=s[:a]+segment+s[b:]
else: s=s.rstrip()+'\n\n[bar]\nmenu_icon = "wolf"\n'
p.write_text(s)
PY
if ! command -v cargo >/dev/null; then
  echo "Wolf option written. To build, install Rust first and rerun:"
  echo "  curl https://sh.rustup.rs -sSf | sh"
  echo "  source \"$HOME/.cargo/env\""
  exit 0
fi
cd "$SRC"
cargo build --release -p pt35-bar --locked
echo "Build successful. To replace only taskbar binary:"
echo "  sudo cp -a /usr/bin/pt35-bar /usr/bin/pt35-bar.fmi-before-wolf"
echo "  sudo install -m755 $SRC/target/release/pt35-bar /usr/bin/pt35-bar"
echo "  pt35ctl reload"
echo "Existing binary NOT replaced automatically."
