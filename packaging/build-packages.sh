#!/usr/bin/env bash
# Build the .tar.gz (any distribution, with install.sh) and, when nfpm is installed, the .deb and .rpm.
# They carry the same self-contained runtime as the AppImage (Python + Qt), so they don't depend on the
# distribution's PySide6. Run packaging/appimage/build.sh first (it leaves the runtime in build/appdir).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)"
DIST="$ROOT/dist"
APPDIR="$ROOT/build/appdir"
NAME="kde-customizer-$VERSION-x86_64"
STAGE="$ROOT/build/pkgroot"                                # fixed path: nfpm.yaml points here
[[ -d "$APPDIR" ]] || { echo "no build/appdir — run packaging/appimage/build.sh first" >&2; exit 1; }
PYDIR="$(cd "$APPDIR/opt" && ls -d python3.* | head -1)"        # e.g. python3.12
PYBIN="python/bin/$PYDIR"
mkdir -p "$DIST"

echo "==> staging $NAME"
rm -rf "$STAGE"
mkdir -p "$STAGE/bin" "$STAGE/share/applications" "$STAGE/share/icons/hicolor/256x256/apps"
cp -a "$APPDIR/opt/$PYDIR" "$STAGE/python"

launcher() {  # launcher <module>: finds the bundled Python relative to itself (works from any prefix)
    cat <<EOF
#!/bin/sh
# KDE Customizer — runs the bundled Python and Qt; no system Python packages needed.
HERE="\$(dirname "\$(readlink -f "\$0")")"
CERTS="\$(ls "\$HERE"/../python/lib/python3.*/site-packages/certifi/cacert.pem 2>/dev/null | head -n1)"
[ -n "\${SSL_CERT_FILE:-}" ] || [ -z "\$CERTS" ] || export SSL_CERT_FILE="\$CERTS"
exec "\$HERE/../$PYBIN" -I -m $1 "\$@"
EOF
}
launcher kdecustomizer.cli > "$STAGE/bin/kdec"
launcher kdecustomizer.gui.app > "$STAGE/bin/kdec-gui"
chmod 755 "$STAGE/bin/kdec" "$STAGE/bin/kdec-gui"
ln -s kdec-gui "$STAGE/bin/kde-customizer"
install -m644 "$ROOT/packaging/kde-customizer.desktop" "$STAGE/share/applications/"
install -m644 "$ROOT/packaging/kde-customizer.png" "$STAGE/share/icons/hicolor/256x256/apps/"
cp -r "$ROOT/examples" "$STAGE/examples"
install -m644 "$ROOT/LICENSE" "$ROOT/README.md" "$STAGE/"
install -m755 "$ROOT/packaging/install.sh" "$STAGE/"

echo "==> $NAME.tar.gz"
touch "$STAGE/update-check"         # the tarball doesn't update itself: the app shows when a new release is out
tar -C "$ROOT/build" --transform "s,^pkgroot,$NAME," -czf "$DIST/$NAME.tar.gz" pkgroot
rm -f "$STAGE/update-check"         # .deb / .rpm: the package manager updates them

if command -v nfpm >/dev/null 2>&1; then
    for fmt in deb rpm; do
        echo "==> .$fmt"
        (cd "$ROOT" && VERSION="$VERSION" nfpm package -f packaging/nfpm.yaml -p "$fmt" -t "$DIST/")
    done
else
    echo "==> nfpm not installed: skipping .deb and .rpm"
fi
ls -la "$DIST"
