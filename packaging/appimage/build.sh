#!/usr/bin/env bash
# Build dist/KDE_Customizer-<version>-x86_64.AppImage (and build/appdir, the runtime the
# .deb/.rpm/.tar.gz are made from — run packaging/build-packages.sh next).
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

# python-appimage lists its releases through the GitHub API without logging in: 60 requests/hour per IP, which
# shared CI runners use up. With GITHUB_TOKEN set (CI passes the workflow token), send it on those calls.
pyappimage() {
    "$TOOLS/python" - "$@" <<'PY'
import os, sys, urllib.request
token = os.environ.get("GITHUB_TOKEN")
if token:
    _open = urllib.request.urlopen
    def urlopen(url, *a, **kw):
        if isinstance(url, str) and url.startswith("https://api.github.com/"):
            url = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        return _open(url, *a, **kw)
    urllib.request.urlopen = urlopen      # before python_appimage imports it
sys.argv = ["python-appimage", *sys.argv[1:]]
from python_appimage.__main__ import main
main()
PY
}

echo "==> building kdecustomizer wheel"
"$TOOLS/python" -m build --wheel --outdir "$WORK/wheel" "$ROOT" >/dev/null
WHEEL="$(ls "$WORK"/wheel/kdecustomizer-*.whl)"

echo "==> staging recipe"
cp "$HERE/entrypoint.sh" "$ROOT/packaging/kde-customizer.desktop" "$ROOT/packaging/kde-customizer.png" "$WORK/recipe/"
cat > "$WORK/recipe/requirements.txt" <<EOF
$WHEEL
PySide6-Essentials>=6.6
Pillow
anthropic>=2.8
pypdf
EOF

echo "==> building AppImage (Python $PYVER)"
cd "$WORK"
pyappimage build app --no-packaging -p "$PYVER" -n KDE_Customizer "$WORK/recipe"
APPDIR="$(find "$WORK" -maxdepth 1 -type d -name 'KDE*Customizer-*' | head -1)"
"$ROOT/packaging/trim-runtime.sh" "$APPDIR"

# Keep the finished runtime for the .deb/.rpm/.tar.gz (packaging/build-packages.sh).
rm -rf "$ROOT/build/appdir"
mkdir -p "$ROOT/build"
cp -a "$APPDIR" "$ROOT/build/appdir"

# Package ourselves (python-appimage loses track of the file when the app's display name has a space).
OUT="$ROOT/dist/KDE_Customizer-$VERSION-x86_64.AppImage"
# Only the normal (non --no-packaging) path downloads appimagetool; on a fresh machine fetch it here.
pyappimage install appimagetool >/dev/null
APPIMAGETOOL="$(pyappimage which appimagetool)"
[[ -x "$APPIMAGETOOL" ]] || { echo "appimagetool not found after install" >&2; exit 1; }
ARCH=x86_64 "$APPIMAGETOOL" --no-appstream "$APPDIR" "$OUT" >/dev/null 2>"$WORK/appimagetool.log" \
    || { cat "$WORK/appimagetool.log"; exit 1; }
chmod +x "$OUT"
echo "==> $OUT ($(du -h "$OUT" | cut -f1))"
