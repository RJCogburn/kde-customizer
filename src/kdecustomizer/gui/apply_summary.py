"""Before Apply: everything that will change, with a checkbox for each part that can be left alone this time
(install.sh --no-…). Unticked parts are remembered per theme."""
from __future__ import annotations

import html
import shutil
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from .. import build, spec, system

WIDTH = 540


def parts(theme: spec.Theme) -> list[tuple[str, str, str]]:
    """[(key, label, note)] for the parts of this theme that can be skipped. key "layout" = replace panels."""
    a = theme.apps
    out = []
    if theme.panels:
        out.append(("layout", "Replace my panels with the theme's", "your current panels and widgets go away"))
    if theme.wallpaper:
        out.append(("wallpaper", "Wallpaper", ""))
    if theme.gtk.generate:
        out.append(("gtk", "GNOME / GTK app colors", "~/.config/gtk-4.0"))
    terms = [n for n, on in [("kitty", a.kitty), ("Ghostty", a.ghostty), ("WezTerm", a.wezterm),
                             ("Alacritty", a.alacritty)] if on]
    if terms:
        out.append(("terminals", "Terminal colors", ", ".join(terms) + " (where installed)"))
    moz = [n for n, on in [("Firefox", a.firefox), ("Thunderbird", a.thunderbird)] if on]
    if moz:
        out.append(("browsers", " and ".join(moz) + " colors", "restart them to see it"))
    if a.vscode:
        out.append(("vscode", "VS Code color theme", "pick it in Color Theme afterwards"))
    n = sum(len(kv) for groups in theme.tweaks.values() for kv in groups.values())
    if n:
        out.append(("tweaks", f"Tweaks ({n} setting{'s' if n != 1 else ''})", "effects and window behavior"))
    if theme.login_screen.generate:
        out.append(("login", "Login screen", "system-wide: asks for your admin password if it changed"))
    if theme.boot_splash.generate:
        out.append(("boot", "Boot splash",
                    "system-wide: admin password, and rebuilding the boot image takes a minute"))
    return out


def always(theme: spec.Theme) -> list[str]:
    """What every Apply sets."""
    items = ["colors"]
    for on, name in [(theme.plasma.generate, "Plasma style"), (theme.iconset.generate, "icons"),
                     (theme.cursorset.generate, "cursors"), (theme.decoration.generate, "title bars"),
                     (theme.widgets.generate, "app style"), (theme.splash_screen.generate, "splash screen"),
                     (theme.konsole, "Konsole colors"), (any(vars(theme.fonts).values()), "fonts")]:
        if on:
            items.append(name)
    return items


def warnings(theme: spec.Theme) -> list[str]:
    """Parts this computer can't do (the Setup check on the start page says how to fix them)."""
    w = []
    if theme.widgets.generate and not system.kvantum_installed():
        w.append(f"Kvantum isn't installed: apps keep the {theme.widget_style} style.")
    if theme.login_screen.generate and not system.login_manager_installed():
        w.append("Neither Plasma Login Manager nor SDDM is set up: the login screen stays as it is.")
    if theme.boot_splash.generate and not shutil.which("plymouth-set-default-theme"):
        w.append("Plymouth isn't installed: the boot splash stays as it is.")
    return w


class ApplySummary(QDialog):
    """What Apply will change, with a checkbox per skippable part and the admin-password note."""

    def __init__(self, parent, theme: spec.Theme, layout: bool, built: Path | None = None):
        """`built`: the theme's build folder — login screen / boot splash that haven't changed since the last
        Apply are marked (install.sh skips them, so no password prompt)."""
        super().__init__(parent)
        self.setWindowTitle("Apply to desktop")
        self.theme = theme
        try:
            self.unchanged = build.unchanged_system_parts(theme, built) if built else set()
        except OSError:
            self.unchanged = set()
        self.settings = QSettings("kdecustomizer", "kdec-gui")
        skipped = set(self.settings.value(self._key(), "", str).split(",")) - {""}
        v = QVBoxLayout(self)
        head = QLabel(f"Apply “{html.escape(theme.name)}” to your desktop")
        f = QFont(head.font())
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * 1.15)
        head.setFont(f)
        v.addWidget(head)
        alw = QLabel("<b>Always:</b> " + html.escape(", ".join(always(theme))) + ".")
        alw.setWordWrap(True)
        v.addWidget(alw)
        self.boxes: dict[str, QCheckBox] = {}
        rows = parts(theme)
        if rows:
            v.addWidget(QLabel("<b>Also</b> (untick what to leave as it is this time):"))
        for key, label, note in rows:
            b = QCheckBox(label)
            b.setChecked(layout if key == "layout" else key not in skipped)
            if key in self.unchanged:
                note = "unchanged since the last Apply: left as it is, no password needed"
            if note:
                b.setToolTip(note)
            v.addWidget(b)
            if note:
                n = QLabel(html.escape(note))
                n.setStyleSheet("color: palette(placeholder-text); margin-left: 26px;")
                n.setWordWrap(True)
                v.addWidget(n)
            self.boxes[key] = b
        for w in warnings(theme):
            lbl = QLabel("⚠ " + html.escape(w))
            lbl.setWordWrap(True)
            v.addWidget(lbl)
        self.password = QLabel()
        self.password.setWordWrap(True)
        v.addSpacing(6)
        v.addWidget(self.password)
        for b in self.boxes.values():
            b.toggled.connect(self._update_password)
        self._update_password()
        tail = QLabel("Everything you have now is saved first. Afterwards you get "
                      "20 seconds to keep the result, or it goes back.")
        tail.setWordWrap(True)
        v.addWidget(tail)
        bb = QDialogButtonBox()
        ok = bb.addButton("Apply", QDialogButtonBox.AcceptRole)
        ok.setDefault(True)
        bb.addButton(QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb, 0, Qt.AlignRight)
        # wrapped labels only know their height for a given width: fix the width, then ask the layout
        self.setFixedWidth(WIDTH)
        self.setFixedHeight(v.totalHeightForWidth(WIDTH))

    def _key(self) -> str:
        return f"apply/skip/{self.theme.id}"

    @property
    def replace_panels(self) -> bool:
        b = self.boxes.get("layout")
        return bool(b and b.isChecked())

    @property
    def skipped(self) -> list[str]:
        return [k for k, b in self.boxes.items() if k != "layout" and not b.isChecked()]

    def args(self) -> list[str]:
        return (["--layout"] if self.replace_panels else []) + build.skip_args(self.skipped)

    def password_parts(self) -> list[str]:
        """System-wide parts that will ask for the admin password this time."""
        names = {"login": "login screen", "boot": "boot splash"}
        return [names[k] for k in ("login", "boot")
                if k in self.boxes and self.boxes[k].isChecked() and k not in self.unchanged]

    def needs_password(self) -> bool:
        return bool(self.password_parts())

    def _update_password(self, *_) -> None:
        parts = self.password_parts()
        self.password.setText("🔒 You'll be asked for your admin password once (" + " and ".join(parts) + ")."
                              if parts else "No admin password needed.")

    def _accept(self) -> None:
        self.settings.setValue(self._key(), ",".join(self.skipped))
        self.accept()
