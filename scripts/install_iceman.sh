#!/usr/bin/env bash
# Build the RRG Iceman userspace client for the device's existing firmware.
set -euo pipefail
usage() {
    echo "Usage: $0 --platform PM3RDV4|PM3GENERIC|PM3ICOPYX|PM3ULTIMATE --rev TAG_OR_FULL_SHA [--install-deps]"
}
PLATFORM=
REV=
INSTALL_DEPS=0
while (( $# )); do
    case "$1" in
        --platform) PLATFORM="${2:?Missing platform}"; shift 2 ;;
        --rev) REV="${2:?Missing firmware revision}"; shift 2 ;;
        --install-deps) INSTALL_DEPS=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done
case "$PLATFORM" in
    PM3RDV4|PM3GENERIC|PM3ICOPYX|PM3ULTIMATE) ;;
    *) usage >&2; exit 2 ;;
esac
if [[ ! "$REV" =~ ^[0-9a-fA-F]{40}$ && ! "$REV" =~ ^v[0-9][0-9A-Za-z._-]*$ ]]; then
    usage >&2
    exit 2
fi
if (( INSTALL_DEPS )); then
    PACKAGES=(git ca-certificates build-essential pkg-config libreadline-dev libbz2-dev liblz4-dev zlib1g-dev libssl-dev)
    printf 'Install the Debian build dependencies?\n%s\n' "${PACKAGES[*]}"
    read -r -p "Type yes to proceed: " ANSWER
    if [[ "$ANSWER" != yes ]]; then exit 1; fi
    sudo apt-get update
    sudo apt-get install --no-install-recommends "${PACKAGES[@]}"
fi
ROOT="$HOME/.local/lib/pt35-iceman"
SOURCE="$ROOT/$PLATFORM-$REV"
ORIGIN=https://github.com/RfidResearchGroup/proxmark3.git
mkdir -p "$ROOT"
if [[ ! -e "$SOURCE" ]]; then
    STAGE="$(mktemp -d "$ROOT/.build.XXXXXXXX")"
    trap 'rm -rf -- "$STAGE"' EXIT
    git clone --no-checkout "$ORIGIN" "$STAGE/source"
    if [[ "$REV" =~ ^[0-9a-fA-F]{40}$ ]]; then
        REF="$REV"
    else
        REF="refs/tags/$REV"
    fi
    git -C "$STAGE/source" checkout --detach "$REF"
    git -C "$STAGE/source" submodule update --init --recursive
    make -C "$STAGE/source" -j2 client PLATFORM="$PLATFORM" SKIPQT=1 SKIPBT=1 SKIPPYTHON=1
    test -x "$STAGE/source/client/proxmark3"
    mv -T -- "$STAGE/source" "$SOURCE"
fi
test "$(git -C "$SOURCE" remote get-url origin)" = "$ORIGIN"
test -x "$SOURCE/client/proxmark3"
if [[ -e "$ROOT/current" && ! -L "$ROOT/current" ]]; then
    echo "Choose the client manually. $ROOT/current is already in use." >&2
    exit 2
fi
ln -sfn "$SOURCE" "$ROOT/current"
printf 'Iceman client built at %s/client/proxmark3\n' "$SOURCE"
git -C "$SOURCE" rev-parse HEAD
printf 'Connect the device and run: python3 nfc/pt35_nfc.py status --backend proxmark3\n'
