"""Live preview: a mock Plasma desktop painted from the same color roles the generators write.

Everything is drawn on a fixed 1280x800 logical canvas and scaled to fit, so proportions match a
real screen. Colors come from generators.colors.scheme() / konsole.ansi(), never re-derived here.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from .. import system
from ..generators import colors as color_gen
from ..generators import konsole as konsole_gen
from ..spec import Panel, Theme

W, H = 1280, 800  # logical canvas


def _q(c, alpha: float = 1.0) -> QColor:
    if isinstance(c, str):
        q = QColor(c)
    else:
        q = QColor(*c)
    q.setAlphaF(alpha)
    return q


def _font(spec: str, fallback_pt: float, bold: bool = False) -> QFont:
    f = QFont()
    family, _, size = spec.partition(",")
    if family.strip():
        f.setFamily(family.strip())
    try:
        f.setPointSizeF(float(size) if size.strip() else fallback_pt)
    except ValueError:
        f.setPointSizeF(fallback_pt)
    f.setBold(bold)
    return f


def ensure_icon_paths() -> None:
    """Outside a KDE session Qt may only search ':/icons'; add the XDG icon dirs."""
    paths = QIcon.themeSearchPaths()
    for d in [Path.home() / ".icons", *(b / "icons" for b in system._data_dirs())]:
        if d.is_dir() and str(d) not in paths:
            paths.append(str(d))
    QIcon.setThemeSearchPaths(paths)
    if not QIcon.themeName():
        QIcon.setThemeName("breeze")
    if not QIcon.fallbackThemeName():
        QIcon.setFallbackThemeName("hicolor")


class IconCache:
    """Pixmaps from a *specific* icon theme, without changing the app's own icons."""

    def __init__(self):
        self._cache: dict[tuple[str, str, int], QPixmap] = {}
        ensure_icon_paths()

    def get(self, theme: str, names: tuple[str, ...], size: int) -> QPixmap:
        key = (theme, names[0], size)
        if key not in self._cache:
            prev = QIcon.themeName()
            QIcon.setThemeName(theme or prev)
            pm = QPixmap()
            for n in names:
                icon = QIcon.fromTheme(n)
                if not icon.isNull():
                    pm = icon.pixmap(QSize(size, size))  # render now, while the theme is set
                    break
            QIcon.setThemeName(prev)
            self._cache[key] = pm
        return self._cache[key]

    def clear(self) -> None:
        self._cache.clear()


# Panel widget id -> how to draw it: ("icon", names) | ("tasks",) | ("tray",) | ("clock",) | ("spacer",) ...
_TASK_ICONS = [("system-file-manager", "folder"), ("internet-web-browser", "applications-internet"),
               ("utilities-terminal", "terminal"), ("systemsettings", "preferences-system")]
_TRAY_ICONS = [("network-wireless", "network-wired"), ("audio-volume-high",), ("battery-080", "battery"),
               ("notifications",)]


class Preview(QWidget):
    launcherToggled = Signal(bool)

    def __init__(self):
        super().__init__()
        self.theme: Theme | None = None
        self.icons = IconCache()
        self._wp_path = ""
        self._wp = QPixmap()
        self.launcher_open = False      # draw the Kickoff menu open over the desktop
        self._launcher_rect: QRectF | None = None
        self._kickoff: tuple[QRectF, str] | None = None   # launcher icon box + panel location (canvas coords)
        self._xform = (0.0, 0.0, 1.0)   # widget -> canvas: offset x, offset y, scale
        self.setToolTip("Click the app launcher in the panel to open its menu")
        self.setMinimumSize(480, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def show_theme(self, theme: Theme) -> None:
        self.theme = theme
        if theme.wallpaper != self._wp_path:
            self._wp_path = theme.wallpaper
            p = Path(theme.wallpaper).expanduser() if theme.wallpaper else None
            self._wp = QPixmap(str(p)) if p and p.is_file() else QPixmap()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(800, 500)

    def set_launcher_open(self, on: bool) -> None:
        if on != self.launcher_open:
            self.launcher_open = on
            self.launcherToggled.emit(on)
            self.update()

    def mousePressEvent(self, e) -> None:
        ox, oy, k = self._xform
        pt = QPointF((e.position().x() - ox) / k, (e.position().y() - oy) / k)
        if self._kickoff and self._kickoff[0].contains(pt):
            self.set_launcher_open(not self.launcher_open)
        elif self.launcher_open and not (self._launcher_rect and self._launcher_rect.contains(pt)):
            self.set_launcher_open(False)   # click outside closes it, like the real thing
        super().mousePressEvent(e)

    # --- painting --------------------------------------------------------------
    def paintEvent(self, _):
        if not self.theme:
            return
        t = self.theme
        try:
            self.s = color_gen.scheme(t)
            self.ansi = konsole_gen.ansi(t)
        except ValueError:      # half-typed color in the editor
            return
        # Paint into an image (not the widget) so blurred Plasma surfaces can read what's behind them.
        dpr = self.devicePixelRatioF()
        canvas = QImage(max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr)),
                        QImage.Format_ARGB32_Premultiplied)
        canvas.setDevicePixelRatio(dpr)
        p = QPainter(canvas)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), self.palette().window())

        scale = min(self.width() / W, self.height() / H)
        ox, oy = (self.width() - W * scale) / 2, (self.height() - H * scale) / 2
        p.translate(ox, oy)
        p.scale(scale, scale)
        self._xform = (ox, oy, scale)
        self.px = scale * self.devicePixelRatioF()  # for crisp icons
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, W, H), 10, 10)
        p.setClipPath(clip)

        self._wallpaper(p)
        area = self._usable_area()
        self._konsole(p, QRectF(area.x() + 90, area.y() + 60, 560, 330))
        self._app_window(p, QRectF(area.x() + 380, area.y() + 150, 700, 440))
        self._kickoff = None
        self._launcher_rect = None
        for panel in t.panels:
            self._panel(p, panel)
        if self.launcher_open and self._kickoff:
            self._launcher(p, *self._kickoff)
        else:
            self._notification(p, area)
        self._pointer(p, QPointF(area.x() + 760, area.y() + 470))
        p.end()
        QPainter(self).drawImage(0, 0, canvas)

    def _pointer(self, p: QPainter, hotspot: QPointF) -> None:
        """The mouse pointer from the theme's cursors (24 px nominal), hotspot at `hotspot`."""
        t = self.theme
        key = (t.cursorset.generate, t.cursorset.base, t.cursorset.fill, t.cursors,
               t.palette.background, t.palette.foreground, t.palette.accent)
        if getattr(self, "_ptr_key", None) != key:
            self._ptr_key = key
            from .. import cursorset
            try:
                self._ptr = cursorset.preview_svg(t)
            except (OSError, ValueError):
                self._ptr = None
        if not self._ptr:
            return
        from PySide6.QtCore import QByteArray
        from PySide6.QtSvg import QSvgRenderer
        text, frame = self._ptr
        r = QSvgRenderer(QByteArray(text.encode()))
        k = 24 / frame.get("nominal_size", 24)
        size = r.defaultSize()
        r.render(p, QRectF(hotspot.x() - frame.get("hotspot_x", 0) * k, hotspot.y() - frame.get("hotspot_y", 0) * k,
                           size.width() * k, size.height() * k))

    def c(self, section: str, key: str, alpha: float = 1.0) -> QColor:
        return _q(self.s[section][key], alpha)

    def _wallpaper(self, p: QPainter) -> None:
        if not self._wp.isNull():
            pm = self._wp.scaled(W, H, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            p.drawPixmap(QPointF((W - pm.width()) / 2, (H - pm.height()) / 2), pm)
            return
        pal = self.theme.palette
        g = QLinearGradient(0, 0, W, H)
        g.setColorAt(0, _q(pal.background))
        g.setColorAt(0.55, _q(pal.surface))
        g.setColorAt(1, QColor(_q(pal.accent)).darker(160) if self.theme.dark else _q(pal.accent).lighter(150))
        p.fillRect(QRectF(0, 0, W, H), g)

    def _panel_rect(self, panel: Panel) -> tuple[QRectF, bool]:
        h = max(24, min(panel.height, 120))
        gap = 8 if panel.floating else 0
        vertical = panel.location in ("left", "right")
        full = (H if vertical else W) - 2 * gap
        if panel.length_mode == "fit":
            n = sum(4 if w.endswith("tasks") else 1 for w in panel.widgets) + 2
            length = min(full, n * h * 0.95)
        else:
            length = full
        start = {"left": gap, "center": (full - length) / 2 + gap, "right": full - length + gap}.get(
            panel.alignment, gap)
        if vertical:
            x = gap if panel.location == "left" else W - h - gap
            return QRectF(x, start, h, length), True
        y = gap if panel.location == "top" else H - h - gap
        return QRectF(start, y, length, h), False

    def _usable_area(self) -> QRectF:
        r = QRectF(0, 0, W, H)
        for panel in self.theme.panels:
            pr, _ = self._panel_rect(panel)
            if panel.location == "bottom":
                r.setBottom(min(r.bottom(), pr.top()))
            elif panel.location == "top":
                r.setTop(max(r.top(), pr.bottom()))
            elif panel.location == "left":
                r.setLeft(max(r.left(), pr.right()))
            else:
                r.setRight(min(r.right(), pr.left()))
        return r

    def _plasma_radius(self) -> float:
        ps = self.theme.plasma
        return ps.radius if ps.generate else 8

    def _blur_behind(self, p: QPainter, rect: QRectF, radius: float) -> None:
        """What KWin's blur does under translucent Plasma surfaces: blur the already-painted pixels."""
        dev = p.device()
        if not isinstance(dev, QImage):
            return
        dpr = dev.devicePixelRatio()
        src = p.worldTransform().mapRect(rect)
        src = QRectF(src.x() * dpr, src.y() * dpr, src.width() * dpr, src.height() * dpr).toAlignedRect()
        src = src.intersected(dev.rect())
        if src.width() < 4 or src.height() < 4:
            return
        piece = dev.copy(src)
        k = max(6, round(14 * dpr))           # downscale factor = blur radius
        small = piece.scaled(max(1, src.width() // k), max(1, src.height() // k),
                             Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        blurred = small.scaled(src.width(), src.height(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        p.save()
        p.setClipPath(path, Qt.IntersectClip)
        p.drawImage(rect, blurred)
        p.restore()

    def _plasma_bg(self, p: QPainter, rect: QRectF, radius: float) -> None:
        """Plasma surface: Window color, translucent when the style blurs; shape from [plasma]."""
        ps = self.theme.plasma
        if ps.blur:
            self._blur_behind(p, rect, radius)
        if ps.generate:
            alpha, edge = ps.opacity, (0.18 if ps.outline else 0.0)
        else:
            alpha, edge = (0.82 if ps.blur else 1.0), 0.12
        p.setPen(QPen(self.c("Colors:Window", "ForegroundNormal", edge), 1) if edge else Qt.NoPen)
        p.setBrush(self.c("Colors:Window", "BackgroundNormal", alpha))
        p.drawRoundedRect(rect, radius, radius)

    def _panel(self, p: QPainter, panel: Panel) -> None:
        rect, vertical = self._panel_rect(panel)
        self._plasma_bg(p, rect, self._plasma_radius() if panel.floating else 0)
        thick = rect.width() if vertical else rect.height()
        icon = int(thick * 0.62)
        cell = thick
        # Lay widgets out along the panel; spacers absorb leftover length.
        items = []
        for w in panel.widgets:
            short = w.rsplit(".", 1)[-1]
            if short in ("icontasks", "taskmanager"):
                items.append(("tasks", cell * len(_TASK_ICONS)))
            elif short == "systemtray":
                items.append(("tray", cell * 0.62 * len(_TRAY_ICONS)))
            elif short == "digitalclock":
                items.append(("clock", cell * 1.6 if not vertical else cell))
            elif short == "marginsseparator" or short == "panelspacer":
                items.append(("spacer", 0))
            else:
                items.append((short, cell))
        length = rect.height() if vertical else rect.width()
        fixed = sum(size for _, size in items)
        spacers = sum(1 for k, _ in items if k == "spacer") or 1
        spare = max(0.0, length - fixed - cell * 0.3)
        pos = cell * 0.15

        fg = self.c("Colors:Window", "ForegroundNormal")
        for kind, size in items:
            if kind == "spacer":
                pos += spare / spacers
                continue
            box = (QRectF(rect.x(), rect.y() + pos, thick, size) if vertical
                   else QRectF(rect.x() + pos, rect.y(), size, thick))
            self._panel_item(p, kind, box, icon, cell, vertical, fg, panel.location)
            pos += size

    def _icon(self, p: QPainter, names: tuple[str, ...], center: QPointF, size: int) -> None:
        pm = self.icons.get(self.theme.icons_name, names, max(16, int(size * self.px)))
        if pm.isNull():
            p.setPen(Qt.NoPen)
            p.setBrush(_q(self.theme.palette.accent, 0.8))
            p.drawRoundedRect(QRectF(center.x() - size / 2, center.y() - size / 2, size, size), 4, 4)
        else:
            p.drawPixmap(QRectF(center.x() - size / 2, center.y() - size / 2, size, size), pm, QRectF(pm.rect()))

    def _panel_item(self, p, kind, box: QRectF, icon, cell, vertical, fg, location: str) -> None:
        if kind == "tasks":
            for i, names in enumerate(_TASK_ICONS):
                c = (QPointF(box.center().x(), box.y() + cell * (i + 0.5)) if vertical
                     else QPointF(box.x() + cell * (i + 0.5), box.center().y()))
                if i == 1:  # the "active" task
                    hl = QRectF(c.x() - cell / 2 + 2, c.y() - cell / 2 + 3, cell - 4, cell - 6)
                    p.setPen(Qt.NoPen)
                    p.setBrush(self.c("Colors:Selection", "BackgroundNormal", 0.25))
                    p.drawRoundedRect(hl, 4, 4)
                    p.setBrush(self.c("Colors:Selection", "BackgroundNormal"))
                    bar = (QRectF(hl.left() if location != "right" else hl.right() - 3,
                                  hl.top() + 6, 3, hl.height() - 12) if vertical
                           else QRectF(hl.left() + 6, hl.bottom() - 3, hl.width() - 12, 3))
                    p.drawRoundedRect(bar, 1.5, 1.5)
                self._icon(p, names, c, icon)
        elif kind == "tray":
            small = int(icon * 0.6)
            step = cell * 0.62
            for i, names in enumerate(_TRAY_ICONS):
                c = (QPointF(box.center().x(), box.y() + step * (i + 0.5)) if vertical
                     else QPointF(box.x() + step * (i + 0.5), box.center().y()))
                self._icon(p, names, c, small)
        elif kind == "clock":
            p.setPen(fg)
            p.setFont(_font(self.theme.fonts.general, 10))
            now = _dt.datetime.now()
            text = now.strftime("%H:%M") if vertical or cell < 40 else now.strftime("%H:%M\n%m/%d")
            p.drawText(box, Qt.AlignCenter, text)
        elif kind == "kickoff":
            if self._kickoff is None:
                self._kickoff = (QRectF(box), location)
            if self.launcher_open and self._kickoff[0] == box:
                p.setPen(Qt.NoPen)
                p.setBrush(self.c("Colors:Selection", "BackgroundNormal", 0.3))
                p.drawRoundedRect(box.adjusted(3, 3, -3, -3), 5, 5)
            self._icon(p, ("start-here-kde-plasma", "start-here-kde", "start-here"), box.center(), icon)
        elif kind == "showdesktop":
            self._icon(p, ("user-desktop", "desktop"), box.center(), int(icon * 0.7))
        elif kind == "pager":
            p.setPen(QPen(fg, 1))
            p.setBrush(self.c("Colors:Selection", "BackgroundNormal", 0.35))
            s = icon * 0.45
            c = box.center()
            p.drawRect(QRectF(c.x() - s - 1, c.y() - s / 2, s, s))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(c.x() + 1, c.y() - s / 2, s, s))
        else:
            self._icon(p, ("application-x-plasma", "plasma", "preferences-desktop-plasma"), box.center(), icon)

    # --- launcher (Kickoff) -------------------------------------------------------------
    def _launcher(self, p: QPainter, anchor: QRectF, location: str) -> None:
        """Plasma 6 Kickoff, opened from `anchor` (the launcher icon) on a panel at `location`."""
        w, h, gap = 560.0, 500.0, 6.0
        if location == "bottom":
            x, y = anchor.left(), anchor.top() - gap - h
        elif location == "top":
            x, y = anchor.left(), anchor.bottom() + gap
        elif location == "left":
            x, y = anchor.right() + gap, anchor.top()
        else:
            x, y = anchor.left() - gap - w, anchor.top()
        x = max(8.0, min(x, W - w - 8))
        y = max(8.0, min(y, H - h - 8))
        rect = QRectF(x, y, w, h)
        self._launcher_rect = rect
        radius = self._plasma_radius()
        self._shadow(p, rect, radius, 0.55)
        self._plasma_bg(p, rect, radius)

        fg = self.c("Colors:Window", "ForegroundNormal")
        dim = self.c("Colors:Window", "ForegroundInactive")
        general = self.theme.fonts.general

        # header: avatar, search field (PlasmoidHeading = Header colors)
        head = QRectF(rect.x(), rect.y(), w, 62)
        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        p.save()
        p.setClipPath(clip, Qt.IntersectClip)
        p.fillRect(head, self.c("Colors:Header", "BackgroundNormal", 0.55))
        p.setPen(QPen(self.c("Colors:Window", "ForegroundNormal", 0.12), 1))
        p.drawLine(head.bottomLeft(), head.bottomRight())
        p.restore()
        self._icon(p, ("user-identity", "im-user", "user"), QPointF(head.x() + 34, head.center().y()), 34)
        search = QRectF(head.x() + 64, head.center().y() - 16, w - 64 - 52, 32)
        wr = self.theme.widgets.radius if self.theme.widgets.generate else 4
        p.setPen(QPen(self.c("Colors:View", "DecorationFocus"), 1.5))
        p.setBrush(self.c("Colors:View", "BackgroundNormal"))
        p.drawRoundedRect(search, wr, wr)
        self._icon(p, ("search", "edit-find"), QPointF(search.x() + 16, search.center().y()), 16)
        p.setPen(dim)
        p.setFont(_font(general, 10))
        p.drawText(search.adjusted(32, 0, 0, 0), Qt.AlignVCenter, "Search…")
        self._icon(p, ("configure", "settings-configure"), QPointF(rect.right() - 26, head.center().y()), 18)

        # sidebar: categories
        body_top, foot_h = head.bottom() + 6, 48
        side = QRectF(rect.x() + 8, body_top, 178, rect.bottom() - foot_h - body_top - 4)
        cats = [("Favorites", ("bookmarks", "favorites")), ("All Applications", ("applications-all", "view-list-icons")),
                ("Development", ("applications-development",)), ("Graphics", ("applications-graphics",)),
                ("Internet", ("applications-internet",)), ("Multimedia", ("applications-multimedia",)),
                ("Office", ("applications-office",)), ("Settings", ("preferences-system", "applications-system")),
                ("System", ("applications-system",)), ("Utilities", ("applications-utilities",))]
        row_h = min(34.0, side.height() / len(cats))
        p.setFont(_font(general, 10))
        for i, (name, icons) in enumerate(cats):
            r = QRectF(side.x(), side.y() + i * row_h, side.width(), row_h)
            if i == 0:   # current category: Plasma's highlight (selection tint + outline)
                p.setPen(QPen(self.c("Colors:Selection", "BackgroundNormal", 0.8), 1))
                p.setBrush(self.c("Colors:Selection", "BackgroundNormal", 0.25))
                p.drawRoundedRect(r.adjusted(0, 1, 0, -1), 4, 4)
            self._icon(p, icons, QPointF(r.x() + 18, r.center().y()), 20)
            p.setPen(fg)
            p.drawText(r.adjusted(36, 0, -4, 0), Qt.AlignVCenter, name)

        # favorites grid
        grid = QRectF(side.right() + 10, body_top + 4, rect.right() - side.right() - 18, side.height() - 4)
        apps = [("Files", ("system-file-manager", "org.kde.dolphin")), ("Browser", ("internet-web-browser",)),
                ("Terminal", ("utilities-terminal", "org.kde.konsole")), ("Settings", ("systemsettings", "preferences-system")),
                ("Discover", ("plasmadiscover", "system-software-install")), ("Text Editor", ("accessories-text-editor", "kate")),
                ("Documents", ("okular", "application-pdf")), ("Screenshot", ("spectacle", "applets-screenshooter")),
                ("Archives", ("ark", "utilities-file-archiver")), ("Calculator", ("accessories-calculator", "kcalc")),
                ("Music", ("elisa", "multimedia-audio-player")), ("Help", ("help-browser", "system-help"))]
        cols, cell_w = 4, grid.width() / 4
        cell_h = min(104.0, grid.height() / 3)
        p.setFont(_font(general, 9))
        for i, (label, icons) in enumerate(apps):
            r = QRectF(grid.x() + (i % cols) * cell_w, grid.y() + (i // cols) * cell_h, cell_w, cell_h)
            if i == 5:   # hovered item
                p.setPen(QPen(self.c("Colors:Selection", "BackgroundNormal", 0.6), 1))
                p.setBrush(self.c("Colors:Selection", "BackgroundNormal", 0.15))
                p.drawRoundedRect(r.adjusted(4, 2, -4, -2), 4, 4)
            self._icon(p, icons, QPointF(r.center().x(), r.y() + cell_h * 0.38), 48)
            p.setPen(fg)
            p.drawText(QRectF(r.x() + 2, r.y() + cell_h * 0.66, r.width() - 4, 20), Qt.AlignHCenter | Qt.AlignTop, label)

        # footer: Applications / Places, power buttons
        foot = QRectF(rect.x(), rect.bottom() - foot_h, w, foot_h)
        p.save()
        p.setClipPath(clip, Qt.IntersectClip)
        p.fillRect(foot, self.c("Colors:Header", "BackgroundNormal", 0.35))
        p.setPen(QPen(self.c("Colors:Window", "ForegroundNormal", 0.12), 1))
        p.drawLine(foot.topLeft(), foot.topRight())
        p.restore()
        p.setFont(_font(general, 10))
        x0 = foot.x() + 10
        for i, (label, icons) in enumerate([("Applications", ("applications-all", "view-list-icons")),
                                            ("Places", ("compass", "folder-open"))]):
            tab = QRectF(x0, foot.y() + 8, 128, foot_h - 16)
            if i == 0:
                p.setPen(Qt.NoPen)
                p.setBrush(self.c("Colors:Selection", "BackgroundNormal", 0.25))
                p.drawRoundedRect(tab, 4, 4)
            self._icon(p, icons, QPointF(tab.x() + 16, tab.center().y()), 18)
            p.setPen(fg)
            p.drawText(tab.adjusted(30, 0, 0, 0), Qt.AlignVCenter, label)
            x0 += 134
        for i, icons in enumerate([("system-shutdown",), ("system-reboot", "view-refresh"),
                                   ("system-suspend", "system-suspend-hibernate")]):
            self._icon(p, icons, QPointF(foot.right() - 24 - i * 38, foot.center().y()), 20)

    # --- windows -----------------------------------------------------------------
    def _shadow(self, p: QPainter, rect: QRectF, radius: float, strength: float) -> None:
        p.setPen(Qt.NoPen)
        for i in range(10, 0, -1):
            p.setBrush(QColor(0, 0, 0, int(strength * 9 / i)))
            p.drawRoundedRect(rect.adjusted(-i * 1.6, -i * 1.0, i * 1.6, i * 2.2), radius + i, radius + i)

    def _window_radius(self) -> tuple[float, float]:
        """(top, bottom) corner radius of app windows: the generated decoration's, else Breeze-like."""
        d = self.theme.decoration
        if d.generate:
            return d.radius, (d.radius if d.border >= d.radius else 0)
        return 8, 8

    def _window_bg(self, p: QPainter, rect: QRectF, color: QColor) -> None:
        """Window body with the decoration's top and bottom corner radii."""
        top, bot = self._window_radius()
        x0, y0, x1, y1 = rect.left(), rect.top(), rect.right(), rect.bottom()
        path = QPainterPath()
        path.moveTo(x0, y0 + top)
        path.arcTo(QRectF(x0, y0, 2 * top, 2 * top), 180, -90)
        path.lineTo(x1 - top, y0)
        path.arcTo(QRectF(x1 - 2 * top, y0, 2 * top, 2 * top), 90, -90)
        path.lineTo(x1, y1 - bot)
        path.arcTo(QRectF(x1 - 2 * bot, y1 - 2 * bot, 2 * bot, 2 * bot), 0, -90)
        path.lineTo(x0 + bot, y1)
        path.arcTo(QRectF(x0, y1 - 2 * bot, 2 * bot, 2 * bot), 270, -90)
        path.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawPath(path)

    def _titlebar(self, p: QPainter, rect: QRectF, title: str, active: bool) -> QRectF:
        d = self.theme.decoration
        top_r = self._window_radius()[0]
        tb = QRectF(rect.x(), rect.y(), rect.width(), d.title_height if d.generate else 32)
        wm = "active" if active else "inactive"
        bg = self.c("WM", f"{wm}Background")
        fg = self.c("WM", f"{wm}Foreground")
        path = QPainterPath()
        path.addRoundedRect(tb.adjusted(0, 0, 0, max(top_r, 1)), top_r, top_r)
        p.save()
        p.setClipRect(tb)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawPath(path)
        p.restore()
        p.setPen(fg)
        p.setFont(_font(self.theme.fonts.window_title or self.theme.fonts.general, 10, bold=True))
        align = {"left": Qt.AlignLeft, "right": Qt.AlignRight}.get(d.title_align, Qt.AlignHCenter) \
            if d.generate else Qt.AlignHCenter
        # keep clear of the button rows when the title isn't centered
        text_rect = tb.adjusted(18 + 26 * len(d.buttons_left), 0, -18 - 26 * len(d.buttons_right), 0) \
            if align != Qt.AlignHCenter else tb
        p.drawText(text_rect, align | Qt.AlignVCenter, title)
        self._buttons(p, d.buttons_left, QPointF(tb.left() + 18, tb.center().y()), 1, fg, active)
        self._buttons(p, d.buttons_right, QPointF(tb.right() - 18, tb.center().y()), -1, fg, active)
        return tb

    def _buttons(self, p, codes: str, start: QPointF, step_dir: int, fg: QColor, active: bool) -> None:
        seq = codes if step_dir == 1 else codes[::-1]
        x = start.x()
        pal = self.theme.palette
        dots = self.theme.decoration.generate and self.theme.decoration.button_style == "dots"
        for code in seq:
            c = QPointF(x, start.y())
            r = 8
            if dots and code != "M":
                if code == "_":
                    x += 6 * step_dir
                    continue
                col = {"X": pal.negative, "I": pal.neutral, "A": pal.positive}.get(code, pal.accent)
                p.setPen(Qt.NoPen)
                p.setBrush(_q(col) if active else self.c("WM", "inactiveForeground", 0.45))
                p.drawEllipse(c, 7, 7)
                x += 22 * step_dir
                continue
            if code == "X" and active:
                p.setPen(Qt.NoPen)
                p.setBrush(_q(self.theme.palette.negative))
                p.drawEllipse(c, r + 1, r + 1)
                pen_c = QColor(255, 255, 255)
            else:
                pen_c = fg
            p.setPen(QPen(pen_c, 1.6, Qt.SolidLine, Qt.RoundCap))
            p.setBrush(Qt.NoBrush)
            if code == "X":
                p.drawLine(c + QPointF(-4, -4), c + QPointF(4, 4))
                p.drawLine(c + QPointF(-4, 4), c + QPointF(4, -4))
            elif code == "A":
                path = QPainterPath()
                path.moveTo(c + QPointF(-5, 3)); path.lineTo(c + QPointF(0, -2)); path.lineTo(c + QPointF(5, 3))
                p.drawPath(path)
            elif code == "I":
                path = QPainterPath()
                path.moveTo(c + QPointF(-5, -2)); path.lineTo(c + QPointF(0, 3)); path.lineTo(c + QPointF(5, -2))
                p.drawPath(path)
            elif code == "M":
                self._icon(p, ("system-file-manager", "folder"), c, 16)
            elif code == "S":
                p.drawEllipse(c, 4, 4)
            elif code in "FB":
                p.drawLine(c + QPointF(-4, 0), c + QPointF(4, 0))
                p.drawLine(c + QPointF(0, -4 if code == "F" else 4), c)
            elif code == "H":
                p.drawText(QRectF(c.x() - 6, c.y() - 8, 12, 16), Qt.AlignCenter, "?")
            elif code == "_":
                x += 6 * step_dir
                continue
            else:
                continue
            x += 26 * step_dir

    def _app_window(self, p: QPainter, rect: QRectF) -> None:
        s = self.c
        wr = self.theme.widgets.radius if self.theme.widgets.generate else 4   # button/field corners
        self._shadow(p, rect, self._window_radius()[0], 1.0)
        self._window_bg(p, rect, s("Colors:Window", "BackgroundNormal"))
        tb = self._titlebar(p, rect, "Files — Home", True)
        font = _font(self.theme.fonts.general, 10)
        small = _font(self.theme.fonts.small or self.theme.fonts.general, 8.5)
        p.setFont(font)

        # Header / toolbar
        hdr = QRectF(rect.x(), tb.bottom(), rect.width(), 42)
        p.fillRect(hdr, s("Colors:Header", "BackgroundNormal"))
        bx = hdr.x() + 10
        for label in ("‹", "›"):
            b = QRectF(bx, hdr.y() + 7, 28, 28)
            p.setPen(QPen(s("Colors:Button", "ForegroundNormal", 0.18), 1))
            p.setBrush(s("Colors:Button", "BackgroundNormal"))
            p.drawRoundedRect(b, wr, wr)
            p.setPen(s("Colors:Button", "ForegroundNormal"))
            p.drawText(b, Qt.AlignCenter, label)
            bx += 34
        field = QRectF(bx + 6, hdr.y() + 7, rect.width() - (bx - rect.x()) - 140, 28)
        p.setPen(QPen(s("Colors:View", "DecorationFocus"), 1.5))
        p.setBrush(s("Colors:View", "BackgroundNormal"))
        p.drawRoundedRect(field, wr, wr)
        p.setPen(s("Colors:View", "ForegroundNormal"))
        p.drawText(field.adjusted(10, 0, 0, 0), Qt.AlignVCenter, "Home › Pictures › Wallpapers")
        btn = QRectF(field.right() + 10, hdr.y() + 7, 104, 28)
        p.setPen(Qt.NoPen)
        p.setBrush(s("Colors:Selection", "BackgroundNormal"))
        p.drawRoundedRect(btn, wr, wr)
        p.setPen(s("Colors:Selection", "ForegroundNormal"))
        p.drawText(btn, Qt.AlignCenter, "Apply")
        p.fillRect(QRectF(hdr.x(), hdr.bottom() - 1, hdr.width(), 1), s("Colors:Window", "ForegroundNormal", 0.12))

        # Sidebar (Window role) and content (View role)
        body = QRectF(rect.x(), hdr.bottom(), rect.width(), rect.bottom() - hdr.bottom() - 26)
        side = QRectF(body.x(), body.y(), 170, body.height())
        p.setPen(s("Colors:Window", "ForegroundInactive"))
        p.setFont(small)
        p.drawText(QRectF(side.x() + 14, side.y() + 8, 150, 18), Qt.AlignVCenter, "Places")
        p.setFont(font)
        places = [("Home", ("user-home", "folder-home")), ("Desktop", ("user-desktop", "folder")),
                  ("Documents", ("folder-documents", "folder")), ("Pictures", ("folder-pictures", "folder")),
                  ("Trash", ("user-trash", "trash-empty"))]
        for i, (name, icon) in enumerate(places):
            row = QRectF(side.x() + 6, side.y() + 30 + i * 30, side.width() - 12, 28)
            if i == 3:
                p.setPen(Qt.NoPen)
                p.setBrush(s("Colors:Selection", "BackgroundNormal", 0.3))
                p.drawRoundedRect(row, wr, wr)
            self._icon(p, icon, QPointF(row.x() + 16, row.center().y()), 18)
            p.setPen(s("Colors:Window", "ForegroundNormal"))
            p.drawText(row.adjusted(32, 0, 0, 0), Qt.AlignVCenter, name)

        view = QRectF(side.right(), body.y(), body.right() - side.right(), body.height())
        p.fillRect(view, s("Colors:View", "BackgroundNormal"))
        p.fillRect(QRectF(view.x(), view.y(), 1, view.height()), s("Colors:Window", "ForegroundNormal", 0.12))
        rows = [("aurora.png", "4.2 MB", None), ("dunes.jpg", "2.8 MB", None),
                ("forest-night.png", "6.1 MB", "sel"), ("README — open link", "", "link"),
                ("Sync complete", "", "pos"), ("Low disk space", "", "neu"), ("Upload failed", "", "neg"),
                ("old-backup.tar", "Disabled", "dis")]
        for i, (name, size, kind) in enumerate(rows):
            row = QRectF(view.x() + 1, view.y() + i * 30, view.width() - 1, 30)
            if kind == "sel":
                p.fillRect(row, s("Colors:Selection", "BackgroundNormal"))
                fg = s("Colors:Selection", "ForegroundNormal")
            else:
                if i % 2:
                    p.fillRect(row, s("Colors:View", "BackgroundAlternate"))
                fg = {
                    "link": s("Colors:View", "ForegroundLink"),
                    "pos": s("Colors:View", "ForegroundPositive"),
                    "neu": s("Colors:View", "ForegroundNeutral"),
                    "neg": s("Colors:View", "ForegroundNegative"),
                    "dis": s("Colors:View", "ForegroundInactive"),
                }.get(kind, s("Colors:View", "ForegroundNormal"))
            icon = ("image-png", "image-x-generic") if name.endswith((".png", ".jpg")) else ("text-x-generic",)
            self._icon(p, icon, QPointF(row.x() + 18, row.center().y()), 20)
            p.setPen(fg)
            f = QFont(font)
            f.setUnderline(kind == "link")
            p.setFont(f)
            p.drawText(row.adjusted(36, 0, -12, 0), Qt.AlignVCenter, name)
            p.setFont(font)
            if size:
                p.setPen(fg if kind == "sel" else s("Colors:View", "ForegroundInactive"))
                p.drawText(row.adjusted(0, 0, -14, 0), Qt.AlignVCenter | Qt.AlignRight, size)

        # Status bar with a progress bar (accent)
        st = QRectF(rect.x(), rect.bottom() - 26, rect.width(), 26)
        p.setPen(s("Colors:Window", "ForegroundInactive"))
        p.setFont(small)
        p.drawText(st.adjusted(12, 0, 0, 0), Qt.AlignVCenter, "8 items, 13.1 MB")
        track = QRectF(st.right() - 180, st.center().y() - 3, 160, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(s("Colors:Window", "ForegroundNormal", 0.15))
        p.drawRoundedRect(track, 3, 3)
        p.setBrush(s("Colors:Selection", "BackgroundNormal"))
        p.drawRoundedRect(QRectF(track.x(), track.y(), track.width() * 0.62, track.height()), 3, 3)

    def _konsole(self, p: QPainter, rect: QRectF) -> None:
        if not self.theme.konsole:
            return
        a = self.ansi
        self._shadow(p, rect, self._window_radius()[0], 0.6)
        self._window_bg(p, rect, _q(a["Background"]))
        tb = self._titlebar(p, rect, "Konsole", False)
        font = _font(self.theme.fonts.fixed or "Monospace", 10)
        font.setStyleHint(QFont.Monospace)
        p.setFont(font)
        lines = [
            [("user@plasma", "Color2"), (" ", None), ("~/themes", "Color4"), (f" $ kdec build {self.theme.slug.lower()}.toml", None)],
            [(f"built build/{self.theme.slug}", None)],
            [("$ ", None), ("ls", None)],
            [("install.sh", "Color2"), ("  ", None), ("lookandfeel/", "Color4"), ("  ", None),
             ("theme.toml", None), ("  ", None), ("plasma/", "Color4")],
            [("warning:", "Color3"), (" wallpaper not set", None)],
            [("error:", "Color1"), (" nothing — all good", None)],
            [("", None)],
        ]
        lh = 20
        y = tb.bottom() + 12
        fm = p.fontMetrics()
        for line in lines:
            x = rect.x() + 14
            for text, slot in line:
                p.setPen(_q(a[slot] if slot else a["Foreground"]))
                p.drawText(QPointF(x, y + fm.ascent()), text)
                x += fm.horizontalAdvance(text)
            y += lh
        # palette strip
        x = rect.x() + 14
        for i in range(8):
            for intense in ("", "Intense"):
                p.fillRect(QRectF(x, y + 4, 14, 14), _q(a[f"Color{i}{intense}"]))
                x += 16
        # cursor
        p.fillRect(QRectF(rect.x() + 14, y - lh + 2, 9, 16), _q(a["Foreground"], 0.8))

    def _notification(self, p: QPainter, area: QRectF) -> None:
        rect = QRectF(area.right() - 340, area.bottom() - 100, 324, 84)
        self._shadow(p, rect, self._plasma_radius(), 0.5)
        self._plasma_bg(p, rect, self._plasma_radius())
        self._icon(p, ("preferences-desktop-theme-global", "preferences-desktop-theme", "preferences-desktop"),
                   QPointF(rect.x() + 32, rect.center().y()), 36)
        p.setPen(self.c("Colors:Window", "ForegroundNormal"))
        p.setFont(_font(self.theme.fonts.general, 10, bold=True))
        p.drawText(QRectF(rect.x() + 62, rect.y() + 14, 250, 22), Qt.AlignVCenter, f"{self.theme.name} applied")
        p.setPen(self.c("Colors:Window", "ForegroundInactive"))
        p.setFont(_font(self.theme.fonts.general, 9.5))
        p.drawText(QRectF(rect.x() + 62, rect.y() + 38, 250, 34), Qt.TextWordWrap,
                   "Panels, colors and windows now match your palette.")
