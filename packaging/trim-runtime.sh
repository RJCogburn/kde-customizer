#!/usr/bin/env bash
# Remove what KDE Customizer never uses from a bundled runtime (an AppDir from python-appimage):
# Qt's QML/Quick stack, Designer, SQL, tests, dev tools, type stubs, pip, Tcl/Tk, Python's test suite.
# Then check every remaining Qt library still resolves its dependencies.
#   packaging/trim-runtime.sh <AppDir>
set -euo pipefail
APPDIR="$1"
PY="$(ls -d "$APPDIR"/opt/python3.*)"
STD="$(ls -d "$PY"/lib/python3.*)"
SP="$STD/site-packages"
Q="$SP/PySide6"
before=$(du -sm "$APPDIR" | cut -f1)

# Python
rm -rf "$STD"/{test,idlelib,tkinter,turtledemo,ensurepip,lib2to3} "$SP"/pip "$SP"/pip-* \
       "$APPDIR"/usr/lib "$APPDIR"/usr/share/tcltk
rm -f "$APPDIR"/usr/bin/pip* "$PY"/bin/pip* "$PY"/bin/kdec* "$STD"/lib-dynload/_tkinter*.so  # pip scripts point at the build dir

# PySide6: Python modules, tools and docs we don't use
rm -rf "$Q"/{assistant,designer,linguist,lrelease,lupdate,qmlformat,qmllint,qmlls,svgtoqml} \
       "$Q"/{doc,include,typesystems,glue,scripts} "$Q"/libpyside6qml.abi3.so*
for m in QtDesigner QtHelp QtLabsStyleKit QtOpenGL QtOpenGLWidgets QtQml QtQmlFeatures QtQuick QtQuickControls2 \
         QtQuickTest QtQuickWidgets QtSql QtTest QtUiTools; do
    rm -f "$Q/$m".abi3.so "$Q/$m".pyi
done
find "$Q" -maxdepth 1 -name '*.pyi' -delete

# Qt libraries and plugins
rm -rf "$Q"/Qt/{qml,translations}
for l in Designer DesignerComponents Help Labs Lottie Qml Quick Sql Test UiTools WaylandCompositor \
         WaylandEglCompositorHwIntegration EglFsKmsSupport EglFSDeviceIntegration; do
    rm -f "$Q"/Qt/lib/libQt6"$l"*.so*
done
rm -rf "$Q"/Qt/plugins/{designer,qmltooling,sqldrivers,egldeviceintegrations,wayland-graphics-integration-server,vectorimageformats}
rm -f "$Q"/Qt/plugins/platforms/{libqeglfs,libqlinuxfb,libqminimalegl,libqvnc,libqvkkhrdisplay}.so
rm -f "$Q"/Qt/plugins/imageformats/libqpdf.so
rm -f "$Q"/Qt/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.so "$Q"/Qt/lib/libQt6VirtualKeyboard*.so*

# Everything left must still find its libraries (bundled ones via RPATH, system ones on the host).
missing=0
while IFS= read -r -d '' so; do
    # Qt/PySide libraries must come from the bundle — not "not found", and not the host's own Qt.
    if out=$(ldd "$so" 2>/dev/null | grep -E 'lib(Qt6|pyside|shiboken)' | grep -v -F "$APPDIR"); then
        echo "BROKEN after trim: $so"; echo "$out"; missing=1
    fi
done < <(find "$Q" -name '*.so*' -type f -print0)
[[ $missing == 0 ]] || { echo "trim removed something still needed" >&2; exit 1; }
echo "==> trimmed runtime: ${before} MB -> $(du -sm "$APPDIR" | cut -f1) MB"
