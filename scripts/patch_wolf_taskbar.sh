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
# Always start from the untouched upstream version stored in this checkout.
# Earlier failed installers may have patched one source file but not the others.
# Importantly, no git reset/checkout modifies any user files.
import subprocess
from datetime import datetime
import shutil

def pristine(relative):
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "show", "HEAD:" + relative],
            text=True)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Could not read Git baseline for {relative}: {exc}")

pixel_rel="crates/pt35-ui/src/pixel.rs"
bar_rel="crates/pt35-bar/src/ui.rs"
menu_rel="crates/pt35-menu/src/ui.rs"
px=pristine(pixel_rel)
bs=pristine(bar_rel)
ms=pristine(menu_rel)

# Refuse unexpected upstream changes before touching any files.
if px.count("pub const PIN:") != 1 or "pub const WOLF:" in px:
    raise SystemExit("Unknown upstream pixel baseline; no changes made.")
if bs.count('if self.theme.bar.menu_icon == "bars" {') != 1:
    raise SystemExit("Unknown upstream bar baseline; no changes made.")

# Both positions are distinct, but their *original bitmap argument* is the
# same. Check full original call fragments, then replace the two exact calls.
tile='''pt35_ui::pixel::draw_centred(
                    canvas,
                    pt35_ui::pixel::SKULL,
                    bx + badge / 2,
                    by + badge / 2,
                    2,
                    theme.color.accent_fg,
                );'''
switcher='''pt35_ui::pixel::draw_centred(
                    canvas,
                    pt35_ui::pixel::SKULL,
                    middle,
                    icon_y,
                    3,
                    theme.color.accent,
                );'''
if ms.count(tile)!=1 or ms.count(switcher)!=1:
    raise SystemExit("Upstream launcher skull drawing changed; no files modified.")

px=px.replace("pub const PIN:",wolf+"\n\npub const PIN:",1)
# Use one shared SVG for all UI locations (top bar, launcher tile,
# and Select/Open Tasks card), with the existing pixel wolf as fallback.
bs=bs.replace(
    'if self.theme.bar.menu_icon == "bars" {',
    '''if self.theme.bar.menu_icon == "wolf" {
            if let Some(wolf) = self.icons.get("pt35-wolf", 22) {
                wolf.draw_tinted(canvas, middle - 11, centre - 11, ink);
            } else {
                pt35_ui::pixel::draw_centred(
                    canvas, pt35_ui::pixel::WOLF, middle, centre, 1, ink
                );
            }
        } else if self.theme.bar.menu_icon == "bars" {''',1)

tile_wolf=tile.replace(
    '''pt35_ui::pixel::draw_centred(''',
    '''                if theme.bar.menu_icon == "wolf" {
                    if let Some(wolf) = self.icons.get("pt35-wolf", 32) {
                        wolf.draw_tinted(canvas, bx + 4, by + 4, theme.color.accent_fg);
                    } else {
                        pt35_ui::pixel::draw_centred(
                            canvas, pt35_ui::pixel::WOLF,
                            bx + badge / 2, by + badge / 2, 2,
                            theme.color.accent_fg,
                        );
                    }
                } else {
                    pt35_ui::pixel::draw_centred(''',1)
tile_wolf=tile_wolf.replace(
    '''                    theme.color.accent_fg,
                );''',
    '''                    theme.color.accent_fg,
                    );
                }''',1)

switcher_wolf=switcher.replace(
    '''pt35_ui::pixel::draw_centred(''',
    '''                if theme.bar.menu_icon == "wolf" {
                    if let Some(wolf) = self.icons.get("pt35-wolf", 40) {
                        wolf.draw_tinted(canvas, middle - 20, icon_y - 20, theme.color.accent);
                    } else {
                        pt35_ui::pixel::draw_centred(
                            canvas, pt35_ui::pixel::WOLF,
                            middle, icon_y, 2, theme.color.accent,
                        );
                    }
                } else {
                    pt35_ui::pixel::draw_centred(''',1)
switcher_wolf=switcher_wolf.replace(
    '''                    theme.color.accent,
                );''',
    '''                    theme.color.accent,
                    );
                }''',1)

# Fail closed if either replacement did not introduce the intended branch.
if 'if theme.bar.menu_icon == "wolf"' not in tile_wolf or 'if theme.bar.menu_icon == "wolf"' not in switcher_wolf:
    raise SystemExit("Wolf menu rendering replacement did not match; no files modified.")
ms=ms.replace(tile,tile_wolf,1)
ms=ms.replace(switcher,switcher_wolf,1)

# Source edit only after ALL three independent checks passed. Retain current
# partially patched copies for manual recovery rather than silently discarding.
stamp=datetime.now().strftime("%Y%m%d-%H%M%S")
for path,data in ((pixel,px),(bar,bs),(menu,ms)):
    if path.read_text()!=data:
        backup=path.with_name(path.name+".fmi-before-wolf-"+stamp+".bak")
        shutil.copy2(path,backup)
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
# Install the shared wolf SVG before installing either executable.
SVG="$ROOT/assets/pt35-wolf.svg"
[[ -f "$SVG" ]] || { echo "Missing wolf SVG: $SVG" >&2; exit 1; }
sudo install -D -m644 "$SVG" /usr/local/share/icons/hicolor/scalable/apps/pt35-wolf.svg
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
echo "Shared SVG wolf installed for bar, launcher and Open Tasks. Reload the graphical shell to activate."
echo "Rollback:"
echo "  sudo cp -a '$BAR.fmi-before-wolf' '$BAR'"
echo "  sudo cp -a '$MENU.fmi-before-wolf' '$MENU'"
