#!/usr/bin/env bash
# Build dist/KDE_Customizer-<version>-x86_64.AppImage
#
# Uses python-appimage: a portable manylinux CPython + pip-installed deps (PySide6-Essentials bundles its
# own Qt). Needs network on first run (downloads the base Python image and appimagetool; cached after).
#   packaging/appimage/build.sh            # default Python 3.12
#   PYVER=3.13 packaging/appimage/build.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$ROOT/packaging/appimage"
PYVER="${PYVER:-3.12}"
# Staged in a temp dir: python-appimage splits requirement lines on spaces, and the project path may have them.
WORK="$(mktemp -d "${TMPDIR:-/tmp}/kdec-appimage.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
TOOLS_VENV="${XDG_CACHE_HOME:-$HOME/.cache}/kdecustomizer/appimage-tools"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)"

mkdir -p "$WORK/recipe" "$WORK/wheel" "$ROOT/dist"

# Tooling lives in a private venv so nothing touches the system Python.
if [[ ! -x "$TOOLS_VENV/bin/python-appimage" ]]; then
    python3 -m venv "$TOOLS_VENV"
    "$TOOLS_VENV/bin/pip" -q install python-appimage build
fi
TOOLS="$TOOLS_VENV/bin"

echo "==> building kdecustomizer wheel"
"$TOOLS/python" -m build --wheel --outdir "$WORK/wheel" "$ROOT" >/dev/null
WHEEL="$(ls "$WORK"/wheel/kdecustomizer-*.whl)"

echo "==> staging recipe"
cp "$HERE/entrypoint.sh" "$HERE/kde-customizer.desktop" "$HERE/kde-customizer.png" "$WORK/recipe/"
cat > "$WORK/recipe/requirements.txt" <<EOF
$WHEEL
PySide6-Essentials>=6.6
Pillow
anthropic>=2.8
pypdf
EOF

echo "==> building AppImage (Python $PYVER)"
cd "$WORK"
"$TOOLS/python-appimage" build app --no-packaging -p "$PYVER" -n KDE_Customizer "$WORK/recipe"
APPDIR="$(find "$WORK" -maxdepth 1 -type d -name 'KDE*Customizer-*' | head -1)"

# Package ourselves (python-appimage loses track of the file when the app's display name has a space).
OUT="$ROOT/dist/KDE_Customizer-$VERSION-x86_64.AppImage"
APPIMAGETOOL="$("$TOOLS/python-appimage" which appimagetool)"
ARCH=x86_64 "$APPIMAGETOOL" --no-appstream "$APPDIR" "$OUT" >/dev/null 2>"$WORK/appimagetool.log" \
    || { cat "$WORK/appimagetool.log"; exit 1; }
chmod +x "$OUT"
echo "==> $OUT ($(du -h "$OUT" | cut -f1))"
