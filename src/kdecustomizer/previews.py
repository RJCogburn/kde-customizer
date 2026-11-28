"""Pictures for the Global Theme: what System Settings shows for the theme, and the wallpaper package's file name.

A Look-and-Feel package that lacks `contents/previews/*` falls back to the default (Breeze) package's pictures, so
every theme looked like Breeze in System Settings › Global Themes. `render()` draws this theme's mock desktop (the
editor's preview) into the sizes Breeze ships. It needs PySide6; without it (or off the GUI thread) nothing is
written and Plasma keeps showing its fallback.
"""
from __future__ import annotations

import struct
from pathlib import Path

from .spec import Theme

# file -> (width, height) like org.kde.breeze.desktop's
SIZES = {"fullscreenpreview.jpg": (1920, 1080), "preview.png": (600, 337), "lockscreen.png": (600, 337)}


def image_size(path: str | Path) -> tuple[int, int] | None:
    """(width, height) of a PNG, JPEG, GIF or WebP from its header (no image library needed); None if unknown."""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">II", head[16:24])
            if head[:6] in (b"GIF87a", b"GIF89a"):
                return struct.unpack("<HH", head[6:10])
            if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                kind = head[12:16]
                if kind == b"VP8 ":
                    w, h = struct.unpack("<HH", head[26:30])
                    return w & 0x3FFF, h & 0x3FFF
                if kind == b"VP8L":
                    b = head[21:25]
                    return 1 + (((b[1] & 0x3F) << 8) | b[0]), 1 + (((b[3] & 0xF) << 10) | (b[2] << 2) | (b[1] >> 6))
                if kind == b"VP8X":
                    return 1 + int.from_bytes(head[24:27], "little"), 1 + int.from_bytes(head[27:30], "little")
                return None
            if head[:2] == b"\xff\xd8":                 # JPEG: walk the segments to a start-of-frame marker
                f.seek(2)
                while True:
                    marker = f.read(2)
                    if len(marker) < 2 or marker[0] != 0xFF:
                        return None
                    if marker[1] in (0xD8, 0x01) or 0xD0 <= marker[1] <= 0xD7:
                        continue
                    length = struct.unpack(">H", f.read(2))[0]
                    if 0xC0 <= marker[1] <= 0xCF and marker[1] not in (0xC4, 0xC8, 0xCC):
                        h, w = struct.unpack(">xHH", f.read(5))
                        return w, h
                    f.seek(length - 2, 1)
    except (OSError, struct.error):
        return None
    return None


def wallpaper_file_name(path: str | Path) -> str:
    """The name the image gets inside a wallpaper package: contents/images/<width>x<height>.<ext> (Plasma picks
    the size closest to the screen by this name)."""
    p = Path(path)
    w, h = image_size(p) or (1920, 1080)
    return f"{w}x{h}{p.suffix.lower()}"


def render(theme: Theme, previews_dir: Path) -> bool:
    """Write the Global Theme pictures into previews_dir. False (nothing written) without PySide6, or when this
    isn't the thread of a QApplication."""
    try:
        from PySide6.QtCore import QThread, Qt
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return False
    app = QGuiApplication.instance()
    if app is None:
        app = QApplication(["kdec", "-platform", "offscreen"])     # command line: draw without a window
    if not isinstance(app, QApplication) or QThread.currentThread() is not app.thread():
        return False
    from .gui.preview import Preview
    pv = Preview()
    pv.resize(1920, 1200)                   # the 1280x800 canvas at 1.5x, then cut to 16:9
    pv.show_theme(theme)
    full = pv.grab().toImage()
    # cut to 16:9 on the side without panels, so the theme's panels stay whole
    edges = {pnl.location for pnl in theme.panels}
    spare = full.height() - 1080
    top = 0 if "top" in edges and "bottom" not in edges else spare if "bottom" in edges and "top" not in edges \
        else spare // 2
    full = full.copy(0, top, 1920, 1080)
    previews_dir.mkdir(parents=True, exist_ok=True)
    full.save(str(previews_dir / "fullscreenpreview.jpg"), "JPEG", 90)
    w, h = SIZES["preview.png"]
    full.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).save(str(previews_dir / "preview.png"))
    # lock screen: the wallpaper alone (what the screen locker shows behind its prompt)
    lock = (pv._wp.toImage() if not pv._wp.isNull() else full).scaled(
        w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    lock.copy((lock.width() - w) // 2, (lock.height() - h) // 2, w, h).save(str(previews_dir / "lockscreen.png"))
    return True
