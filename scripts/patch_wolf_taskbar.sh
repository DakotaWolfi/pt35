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
# Preserve upstream stock skull; add one independent wolf bitmap.
s=pixel.read_text()
if 'pub const WOLF:' not in s:
    anchor="pub const PIN:"
    if s.count(anchor)!=1:
        raise SystemExit("Unknown upstream pixel source; no files modified.")
    s=s.replace(anchor,wolf+"\n\n"+anchor,1)
else:
    a=s.index("pub const WOLF:")
    a=s.rfind("///",0,a) if "Custom FMI PT35 wolf:" in s[max(0,a-100):a] else a
    b=s.index("];",s.index("pub const WOLF:",a))+2
    s=s[:a]+wolf+s[b:]
pixel.write_text(s)

s=bar.read_text()
if "pt35_ui::pixel::WOLF" not in s:
    anchor='if self.theme.bar.menu_icon == "bars" {'
    if s.count(anchor)!=1:
        raise SystemExit("Unknown upstream pt35-bar icon selection; no bar changes.")
    s=s.replace(anchor,'''if self.theme.bar.menu_icon == "wolf" {
            pt35_ui::pixel::draw_centred(canvas, pt35_ui::pixel::WOLF, middle, centre, 1, ink);
        } else '''+anchor,1)
    bar.write_text(s)

# Two original PT35 menu render sites: Launcher tile and Select/Open Tasks card.
# Both should respect the same theme field as the bar.
s=menu.read_text()
needle="pt35_ui::pixel::SKULL,"
if s.count(needle) != 2 and "PT35 FMI wolf or skull" not in s:
    raise SystemExit(f"Unexpected original menu skull sites ({s.count(needle)}). Refusing patch.")
if "PT35 FMI wolf or skull" not in s:
    s=s.replace(needle,
        '/* PT35 FMI wolf or skull */\n                    if theme.bar.menu_icon == "wolf" { pt35_ui::pixel::WOLF } else { pt35_ui::pixel::SKULL },',
        1)
    # The task switcher uses scale 3, which is too wide for 19-pixel wolf.
    # Scale 2 for the wolf; retain 3 for the original skull.
    first=s.index("/* PT35 FMI wolf or skull */")
    pos=s.index(needle,first)
    s=s[:pos]+s[pos:].replace(needle,
        '/* PT35 FMI wolf or skull */\n                    if theme.bar.menu_icon == "wolf" { pt35_ui::pixel::WOLF } else { pt35_ui::pixel::SKULL },',1)
    # replace only the second draw_centred call's scale to avoid clipping
    pos=s.index("/* PT35 FMI wolf or skull */",first+1)
    end=s.index("theme.color.accent,",pos)
    snippet=s[pos:end]
    if "                    3,\n" in snippet:
        s=s[:pos]+s[pos:end].replace("                    3,\n",
            '                    if theme.bar.menu_icon == "wolf" { 2 } else { 3 },\n',1)+s[end:]
    else:
        raise SystemExit("Unknown switcher art scale; refusing to write menu.")
    menu.write_text(s)
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
