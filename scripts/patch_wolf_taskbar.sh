#!/usr/bin/env bash
# Build/install matching wolf artwork in BOTH PocketTerm35 taskbar and launcher.
# The Select/Open Tasks launcher card is rendered by pt35-menu, not pt35-bar.
set -Eeuo pipefail
[[ "$(id -u)" != 0 ]] || { echo "Run as normal user (no sudo)." >&2; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$HOME/pt35-wolf-source"
if [[ ! -d "$SRC/.git" ]]; then
  git clone https://github.com/therezor/PocketTerm35-OS.git "$SRC"
fi
python3 - "$SRC" <<'PY'
from pathlib import Path
import sys

root=Path(sys.argv[1])
pixel=root/"crates/pt35-ui/src/pixel.rs"
bar=root/"crates/pt35-bar/src/ui.rs"
menu=root/"crates/pt35-menu/src/ui.rs"
for p in (pixel,bar,menu):
    if not p.is_file():
        raise SystemExit(f"Missing upstream PocketTerm35 source: {p}")

wolf='''/// Custom FMI PT35 wolf: 19 × 19, shared by bar and task switcher.
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
];'''
# Prepare all three modified sources in memory before writing ANY file.
# This also supports a partial patch from an earlier failed attempt.
px=pixel.read_text()
if 'pub const WOLF:' not in px:
    anchor="pub const PIN:"
    if px.count(anchor)!=1:
        raise SystemExit("Unknown upstream pixel source; no files changed.")
    px=px.replace(anchor,wolf+"\n\n"+anchor,1)

bs=bar.read_text()
if "pt35_ui::pixel::WOLF" not in bs:
    anchor='if self.theme.bar.menu_icon == "bars" {'
    if bs.count(anchor)!=1:
        raise SystemExit("Unknown upstream bar icon selection; no files changed.")
    bs=bs.replace(anchor,'''if self.theme.bar.menu_icon == "wolf" {
            pt35_ui::pixel::draw_centred(canvas, pt35_ui::pixel::WOLF, middle, centre, 1, ink);
        } else '''+anchor,1)

ms=menu.read_text()
# The tile and switcher use different geometry. Match each draw call by its
# unique coordinate pair instead of assuming there are exactly two identical
# SKULL tokens (an older attempt may have already modified one call).
import re

def replace_draw(source, coords, scale_old, scale_new):
    pattern=(r'pt35_ui::pixel::draw_centred\(\s*canvas,\s*'
             r'(?P<art>pt35_ui::pixel::SKULL|'
             r'if theme\.bar\.menu_icon == "wolf" \{ pt35_ui::pixel::WOLF \} '
             r'else \{ pt35_ui::pixel::SKULL \})\s*,\s*'
             + re.escape(coords[0]) + r'\s*,\s*'
             + re.escape(coords[1]) + r'\s*,\s*'
             + r'(?P<scale>' + re.escape(str(scale_old)) +
             r'|if theme\.bar\.menu_icon == "wolf" \{ 2 \} else \{ 3 \})\s*,')
    hits=list(re.finditer(pattern,source))
    if len(hits)!=1:
        raise SystemExit(f"Could not uniquely locate original menu art at {coords}: {len(hits)} matches; no files changed.")
    hit=hits[0]
    art='if theme.bar.menu_icon == "wolf" { pt35_ui::pixel::WOLF } else { pt35_ui::pixel::SKULL }'
    return (source[:hit.start("art")] + art
            + source[hit.end("art"):hit.start("scale")]
            + scale_new + source[hit.end("scale"):])

ms=replace_draw(ms,("bx + badge / 2","by + badge / 2"),2,"2")
ms=replace_draw(ms,("middle","icon_y"),3,
    'if theme.bar.menu_icon == "wolf" { 2 } else { 3 }')
# No partial modifications when the original source was unexpected.
for path,data in ((pixel,px),(bar,bs),(menu,ms)):
    if path.read_text()!=data:
        path.write_text(data)
print("Wolf artwork patched in pt35-bar and pt35-menu; stock skull preserved.")
PY
if ! command -v cargo >/dev/null; then
  echo "Rust cargo not installed; source prepared but no binaries changed."
  exit 1
fi
if ! command -v pkg-config >/dev/null || ! pkg-config --exists xkbcommon wayland-client; then
  echo "Missing build deps: sudo apt install pkg-config libxkbcommon-dev libwayland-dev"
  exit 1
fi
(
  cd "$SRC"
  cargo build --release --locked -p pt35-bar -p pt35-menu
)
[[ "$#" -gt 0 && "$1" == "--install" ]] || {
  echo "Both binaries built successfully; install with:"
  echo "  bash $ROOT/scripts/patch_wolf_taskbar.sh --install"
  exit 0
}
BAR="$(command -v pt35-bar)"
MENU="$(command -v pt35-menu)"
[[ -n "$BAR" && -n "$MENU" ]] || { echo "pt35-bar/menu missing from PATH" >&2; exit 1; }
BAR="$(readlink -f "$BAR")"
MENU="$(readlink -f "$MENU")"
[[ -x "$BAR" && -x "$MENU" ]] || { echo "Existing binaries missing" >&2; exit 1; }
for pair in "$BAR pt35-bar" "$MENU pt35-menu"; do
  read -r current name <<<"$pair"
  if [[ ! -f "$current.fmi-before-wolf" ]]; then
    sudo cp -a "$current" "$current.fmi-before-wolf"
  fi
done
# Build both first, then replace. Backups are available for recovery.
sudo install -m755 "$SRC/target/release/pt35-bar" "$BAR"
sudo install -m755 "$SRC/target/release/pt35-menu" "$MENU"
CONF="$HOME/.config/pt35/theme.toml"
mkdir -p "$(dirname "$CONF")"
[[ ! -f "$CONF" ]] || cp -a "$CONF" "$CONF.bak.$(date +%Y%m%d-%H%M%S)"
python3 "$ROOT/tools/pt35_menu_icon.py" bars
mkdir -p "$HOME/.local/share/pt35"
touch "$HOME/.local/share/pt35/wolf-bar-installed"
python3 "$ROOT/tools/pt35_menu_icon.py" wolf
echo "Wolf binaries installed (bar + launcher). Log out and back in to load BOTH processes."
echo "Rollback:"
echo "  sudo cp -a '$BAR.fmi-before-wolf' '$BAR'"
echo "  sudo cp -a '$MENU.fmi-before-wolf' '$MENU'"
