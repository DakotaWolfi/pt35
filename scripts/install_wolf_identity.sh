#!/usr/bin/env bash
# Unified PT35 wolf identity: bar, launcher switcher card, terminal logo.
# Compiles BOTH affected Rust programs; does not touch keyboard/I2C.
set -euo pipefail
[[ "$(id -u)" != 0 ]] || { echo "Run as login user, no sudo"; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$HOME/pt35-wolf-source"
SVG="$ROOT/assets/pt35-wolf.svg"
[[ -f "$SVG" ]] || { echo "Missing $SVG"; exit 1; }
if [[ ! -d "$SRC/.git" ]]; then git clone https://github.com/therezor/PocketTerm35-OS.git "$SRC"; fi

python3 - "$SRC" <<'PY'
from pathlib import Path
import sys
src=Path(sys.argv[1])
bar=src/"crates/pt35-bar/src/ui.rs"
menu=src/"crates/pt35-menu/src/ui.rs"
b=bar.read_text()
# A real SVG rendered at 22px replaces old hard-coded triangles and holes.
new='''        if self.theme.bar.menu_icon == "wolf" {
            if let Some(wolf) = self.icons.get("pt35-wolf", 22) {
                wolf.draw_tinted(canvas, middle - 11, centre - 11, ink);
            } else {
                pt35_ui::pixel::draw_centred(canvas, pt35_ui::pixel::WOLF, middle, centre, 1, ink);
            }
        } else if self.theme.bar.menu_icon == "bars" {'''
old='''        if self.theme.bar.menu_icon == "bars" {'''
start=b.find('        if self.theme.bar.menu_icon == "wolf" {')
if start >= 0:
    end=b.find('        } else if self.theme.bar.menu_icon == "bars" {',start)
    if end < 0: raise SystemExit("Bar wolf block unexpected; aborting")
    b=b[:start]+new+b[end+len('        } else if self.theme.bar.menu_icon == "bars" {'):]
elif old in b:
    b=b.replace(old,new,1)
else: raise SystemExit("Bar icon selection changed upstream; aborting")
bar.write_text(b)

m=menu.read_text()
original='''                pt35_ui::pixel::draw_centred(
                    canvas,
                    pt35_ui::pixel::SKULL,
                    bx + badge / 2,
                    by + badge / 2,
                    2,
                    theme.color.accent_fg,
                );'''
updated='''                if let Some(wolf) = self.icons.get("pt35-wolf", 32) {
                    wolf.draw_tinted(canvas, bx + 4, by + 4, theme.color.accent_fg);
                } else {
                    pt35_ui::pixel::draw_centred(
                        canvas,
                        pt35_ui::pixel::WOLF,
                        bx + badge / 2,
                        by + badge / 2,
                        2,
                        theme.color.accent_fg,
                    );
                }'''
if original in m:
    m=m.replace(original,updated,1)
elif 'self.icons.get("pt35-wolf", 32)' not in m:
    raise SystemExit("Launcher card bitmap selection changed upstream; aborting")
menu.write_text(m)

pixel=src/"crates/pt35-ui/src/pixel.rs"
p=pixel.read_text()
if "pub const WOLF:" not in p:
    wolf='''/// Fallback wolf icon when SVG theme resources are missing.
pub const WOLF: &[&str] = &[
    "##...............##",
    "###.............###",
    "####...........####",
    "#####.........#####",
    "######.......######",
    "#######.....#######",
    "###################",
    ".#################.",
    "..###...###...###..",
    "..####..###..####..",
    "...#############...",
    "...#####...#####...",
    "....#####.#####....",
    ".....#########.....",
    "......#######......",
    ".......#####.......",
    "........###........",
    ".........#.........",
    "...................",
];
'''
    if 'pub const PIN:' not in p: raise SystemExit("No pixel fallback insertion point")
    p=p.replace('pub const PIN:',wolf+'\npub const PIN:',1)
    pixel.write_text(p)
print("Patched both bar and launcher source for the same SVG wolf artwork.")
PY

if ! command -v cargo >/dev/null; then echo "Rust cargo missing"; exit 1; fi
if ! command -v pkg-config >/dev/null || ! pkg-config --exists xkbcommon wayland-client; then
  echo "Need sudo apt install pkg-config libxkbcommon-dev libwayland-dev"; exit 1
fi

(cd "$SRC" && cargo build --release --locked -p pt35-bar -p pt35-menu)
if [[ "${1:-}" != "--install" ]]; then
  echo "Built; run bash $ROOT/scripts/install_wolf_identity.sh --install"
  exit 0
fi

# Install the artwork FIRST, then executables. Back up installed binaries.
sudo install -D -m644 "$SVG" /usr/local/share/icons/hicolor/scalable/apps/pt35-wolf.svg
for name in pt35-bar pt35-menu; do
  current="$(command -v "$name")"
  [[ -n "$current" ]] || { echo "No installed $name"; exit 1; }
  sudo cp -a "$current" "$current.fmi-wolf-$(date +%Y%m%d-%H%M%S).bak"
  sudo install -m755 "$SRC/target/release/$name" "$current"
done
mkdir -p "$HOME/.local/share/pt35"
touch "$HOME/.local/share/pt35/wolf-bar-installed"
python3 "$ROOT/tools/pt35_menu_icon.py" wolf

# Terminal logo: user override config only, do not edit /etc or upstream distro files.
CONFIG="$HOME/.config/fastfetch/config.jsonc"
mkdir -p "$(dirname "$CONFIG")" "$HOME/.local/share/pt35"
cat > "$HOME/.local/share/pt35/wolf.txt" <<'ART'
$1    /\        /\
$1   /  \______/  \
$1  /  _       _  \
$1  \ / \  /\ / \ /
$1   |   \/  \/   |
$1    \  /\__/\  /
$1     \  \__/  /
$1      \_ /\ _/
$1        \__/
ART
if [[ ! -f "$CONFIG" ]]; then
  upstream=/etc/xdg/fastfetch/config.jsonc
  [[ -f "$upstream" ]] && cp "$upstream" "$CONFIG" || true
fi
if [[ -f "$CONFIG" ]]; then
 python3 - "$CONFIG" "$HOME/.local/share/pt35/wolf.txt" <<'PY'
from pathlib import Path
import sys,re
p=Path(sys.argv[1]); logo=sys.argv[2]
s=p.read_text()
# Replace only standard shipped logo reference, not unrelated custom logos.
s=s.replace('/usr/share/pt35-desktop/fastfetch/skull.txt',logo)
p.write_text(s)
PY
fi
echo "Wolf artwork and both menu applications installed. Log out and back in to restart them."
