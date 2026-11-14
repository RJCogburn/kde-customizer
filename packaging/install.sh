#!/bin/sh
# Install KDE Customizer from this folder (the release .tar.gz), on any distribution.
#
#   ./install.sh               for your user: ~/.local (no root)
#   ./install.sh --system      for everyone:  /opt/kde-customizer + /usr/local/bin (uses sudo)
#   ./install.sh --uninstall   remove it again (add --system for a system install)
#
# It also runs straight from this folder: ./bin/kdec-gui  (GUI)  ./bin/kdec --help  (command line)
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
PREFIX="$HOME/.local"
APPDIR="$HOME/.local/opt/kde-customizer"
SUDO=""
UNINSTALL=0
for arg in "$@"; do
    case "$arg" in
        --system) PREFIX="/usr/local"; APPDIR="/opt/kde-customizer"; SUDO="sudo" ;;
        --uninstall) UNINSTALL=1 ;;
        -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
        *) echo "unknown option: $arg (see --help)" >&2; exit 1 ;;
    esac
done
if [ "$(id -u)" = 0 ]; then SUDO=""; fi

DESKTOP="$PREFIX/share/applications/kde-customizer.desktop"
ICON="$PREFIX/share/icons/hicolor/256x256/apps/kde-customizer.png"

if [ "$UNINSTALL" = 1 ]; then
    $SUDO rm -f "$PREFIX/bin/kdec" "$PREFIX/bin/kdec-gui" "$PREFIX/bin/kde-customizer" "$DESKTOP" "$ICON"
    $SUDO rm -rf "$APPDIR"
    echo "Removed KDE Customizer. Your themes and settings (~/.config/kdecustomizer) were left alone."
    exit 0
fi

echo "==> Installing to $APPDIR (commands in $PREFIX/bin)"
$SUDO mkdir -p "$APPDIR" "$PREFIX/bin" "$(dirname "$DESKTOP")" "$(dirname "$ICON")"
$SUDO rm -rf "$APPDIR/python"
$SUDO cp -a "$HERE/python" "$HERE/bin" "$HERE/examples" "$APPDIR/"
for c in kdec kdec-gui kde-customizer; do
    $SUDO ln -sf "$APPDIR/bin/$c" "$PREFIX/bin/$c"
done
$SUDO cp "$HERE/share/applications/kde-customizer.desktop" "$DESKTOP"
$SUDO cp "$HERE/share/icons/hicolor/256x256/apps/kde-customizer.png" "$ICON"
command -v update-desktop-database >/dev/null 2>&1 && $SUDO update-desktop-database -q "$(dirname "$DESKTOP")" || true

echo "Done. Start it from your application menu (KDE Customizer) or run: kde-customizer"
case ":$PATH:" in *":$PREFIX/bin:"*) ;; *) echo "Note: $PREFIX/bin is not on your PATH." ;; esac
