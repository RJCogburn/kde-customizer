"""kdec-gui — PySide6 editor for theme specs. Thin layer over spec/build; no logic of its own."""
from __future__ import annotations

import sys
from dataclasses import fields
from pathlib import Path

from PySide6.QtCore import QProcess
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from .. import build as builder
from .. import spec


class ColorButton(QPushButton):
    def __init__(self, value: str):
        super().__init__()
        self.setFixedWidth(120)
        self.set(value)
        self.clicked.connect(self._pick)

    def set(self, value: str) -> None:
        self.value = value
        fg = "#000" if QColor(value).lightness() > 128 else "#fff"
        self.setText(value)
        self.setStyleSheet(f"background:{value}; color:{fg};")

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self.value), self)
        if c.isValid():
            self.set(c.name())


class Main(QMainWindow):
    def __init__(self, path: str | None):
        super().__init__()
        self.setWindowTitle("KDE Customizer")
        self.path: Path | None = None
        self.theme = spec.Theme()

        root = QWidget()
        lay = QVBoxLayout(root)

        bar = QHBoxLayout()
        for label, fn in [("Open…", self.open), ("Save", self.save), ("Build", self.do_build),
                          ("Apply", self.apply), ("Export…", self.export)]:
            b = QPushButton(label)
            b.clicked.connect(fn)
            bar.addWidget(b)
        self.with_layout = QCheckBox("Replace panel layout")
        bar.addWidget(self.with_layout)
        bar.addStretch()
        lay.addLayout(bar)

        meta = QGroupBox("Theme")
        mf = QFormLayout(meta)
        self.text: dict[str, QLineEdit] = {}
        for key in ("name", "id", "author", "icons", "cursors", "widget_style", "plasma_style"):
            self.text[key] = QLineEdit()
            mf.addRow(key.replace("_", " ").title(), self.text[key])
        self.text["wallpaper"] = QLineEdit()
        wp_row = QHBoxLayout()
        wp_row.addWidget(self.text["wallpaper"])
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.pick_wallpaper)
        wp_row.addWidget(browse)
        mf.addRow("Wallpaper", wp_row)
        lay.addWidget(meta)

        pal = QGroupBox("Palette")
        pf = QFormLayout(pal)
        self.colors: dict[str, ColorButton] = {}
        for f in fields(spec.Palette):
            if f.name in ("link", "visited"):
                continue
            self.colors[f.name] = ColorButton(f.default)
            pf.addRow(f.name.title(), self.colors[f.name])
        lay.addWidget(pal)

        ps = QGroupBox("Plasma style")
        pv = QVBoxLayout(ps)
        self.plasma: dict[str, QCheckBox] = {}
        for key, label in [("generate", "Generate from palette (overrides Plasma Style above)"),
                           ("blur", "Blur behind panels and popups"),
                           ("adaptive_transparency", "Opaque panels when a window is maximized")]:
            self.plasma[key] = QCheckBox(label)
            pv.addWidget(self.plasma[key])
        self.plasma["generate"].toggled.connect(lambda on: self.text["plasma_style"].setEnabled(not on))
        lay.addWidget(ps)

        self.log = QPlainTextEdit(readOnly=True)
        self.log.setMaximumHeight(160)
        lay.addWidget(self.log)
        self.setCentralWidget(root)

        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyRead.connect(lambda: self.log.appendPlainText(
            bytes(self.proc.readAll()).decode(errors="replace").rstrip()))

        if path:
            self.load(Path(path))
        else:
            self.to_form()

    # --- form <-> theme -------------------------------------------------------
    def to_form(self) -> None:
        for k, w in self.text.items():
            w.setText(getattr(self.theme, k))
        for k, b in self.colors.items():
            b.set(getattr(self.theme.palette, k))
        for k, c in self.plasma.items():
            c.setChecked(getattr(self.theme.plasma, k))
        self.text["plasma_style"].setEnabled(not self.theme.plasma.generate)

    def from_form(self) -> spec.Theme:
        for k, w in self.text.items():
            setattr(self.theme, k, w.text().strip())
        for k, b in self.colors.items():
            setattr(self.theme.palette, k, b.value)
        for k, c in self.plasma.items():
            setattr(self.theme.plasma, k, c.isChecked())
        return self.theme

    # --- actions --------------------------------------------------------------
    def load(self, path: Path) -> None:
        try:
            self.theme = spec.load(path)
        except Exception as e:  # show any parse error to the user
            QMessageBox.critical(self, "Load failed", str(e))
            return
        self.path = path
        self.setWindowTitle(f"KDE Customizer — {path.name}")
        self.to_form()

    def open(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Open theme", "", "Theme spec (*.toml)")
        if f:
            self.load(Path(f))

    def save(self) -> bool:
        if not self.path:
            f, _ = QFileDialog.getSaveFileName(self, "Save theme", "theme.toml", "Theme spec (*.toml)")
            if not f:
                return False
            self.path = Path(f)
        spec.save(self.from_form(), self.path)
        self.log.appendPlainText(f"saved {self.path}")
        return True

    def do_build(self) -> Path | None:
        try:
            out = builder.build(self.from_form(), (self.path.parent if self.path else Path.cwd()) / "build")
        except Exception as e:
            QMessageBox.critical(self, "Build failed", str(e))
            return None
        self.log.appendPlainText(f"built {out}")
        return out

    def pick_wallpaper(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Choose wallpaper", str(Path.home()),
                                           "Images (*.png *.jpg *.jpeg *.webp *.svg)")
        if f:
            self.text["wallpaper"].setText(f)

    def export(self) -> None:
        theme = self.from_form()
        f, _ = QFileDialog.getSaveFileName(self, "Export theme", f"{theme.slug}.tar.gz", "Theme archive (*.tar.gz)")
        if not f:
            return
        root = (self.path.parent if self.path else Path.cwd()) / "build"
        try:
            dest = builder.export(theme, f, root)
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))
            return
        self.log.appendPlainText(f"exported {dest} — recipient extracts it and runs ./install.sh")

    def apply(self) -> None:
        out = self.do_build()
        if out:
            args = ["--layout"] if self.with_layout.isChecked() else []
            self.proc.start(str(out / "install.sh"), args)


def main() -> int:
    app = QApplication(sys.argv)
    w = Main(sys.argv[1] if len(sys.argv) > 1 else None)
    w.resize(560, 720)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
