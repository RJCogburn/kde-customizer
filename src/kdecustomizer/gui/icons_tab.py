"""Icons tab: generated icon set (recolored base) + signature icons (AI vectors, local image AI, import)."""
from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QSize, Qt, QThread, Signal
from PySide6.QtGui import QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from .. import iconset, imagegen, signature, spec
from .ai_panel import current_provider

PERFORMANCE = ["", "Speed", "Quality", "Extreme Speed", "Lightning", "Hyper-SD"]


class _Worker(QObject):
    progress = Signal(str)
    done = Signal(list)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn(self.progress.emit))
        except Exception as e:  # AI/network/image errors are shown in the tab
            self.failed.emit(str(e))


class IconsTab(QWidget):
    changed = Signal()          # spec fields edited
    icons_changed = Signal()    # signature files on disk changed (preview should rebuild)

    def __init__(self, get_theme, get_spec_path, ensure_saved):
        super().__init__()
        self.get_theme, self.get_spec_path, self.ensure_saved = get_theme, get_spec_path, ensure_saved
        self.thread: QThread | None = None
        self.s = QSettings("kdecustomizer", "kdec-gui")
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(12)

        g = QGroupBox("Icon set")
        f = QFormLayout(g)
        self.generate = QCheckBox("Generate a matching icon set")
        self.generate.setToolTip("Recolors the base theme's folders and places to your accent color and\n"
                                 "inherits everything else from it. Replaces the Icons choice on the Desktop tab.")
        self.generate.toggled.connect(self.changed)
        self.base = QComboBox()
        self.base.addItems(iconset.svg_themes())
        self.base.currentTextChanged.connect(self.changed)
        self.app_icons = QCheckBox("Restyle every app's icon to the theme")
        self.app_icons.setToolTip("Each installed app keeps its own logo in its own colors; its tile/plate becomes\n"
                                  "a graphite gradient with an accent rim, so the set matches and logos pop.\n"
                                  "Includes Flatpak apps. Free-standing logos are left as they are.")
        self.app_icons.toggled.connect(self.changed)
        self.app_icons.toggled.connect(lambda _: self.icons_changed.emit())
        f.addRow(self.generate)
        f.addRow("Base theme", self.base)
        f.addRow(self.app_icons)
        v.addWidget(g)

        g = QGroupBox("Signature icons")
        sv = QVBoxLayout(g)
        hint = QLabel("Custom-made versions of the 14 icons you see most (folders, home, trash, launcher, "
                      "file manager, terminal, browser, settings). Everything else comes from the icon set above.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(placeholder-text);")
        sv.addWidget(hint)
        sf = QFormLayout()
        self.style = QLineEdit(placeholderText="e.g. brushed champagne-gold metal, dark graphite glass "
                                               "(empty = derived from the palette)")
        self.style.textChanged.connect(self.changed)
        sf.addRow("Style", self.style)
        self.mode = QComboBox()
        self.mode.addItem("AI-drawn vectors (crisp at every size)", "svg")
        self.mode.addItem("Local image AI (rendered, e.g. Fooocus)", "image")
        self.mode.currentIndexChanged.connect(self._mode_changed)
        sf.addRow("Made by", self.mode)
        url_row = QHBoxLayout()
        self.url = QLineEdit(self.s.value("icons/image_url", "http://127.0.0.1:7865"))
        self.url.setToolTip("Fooocus, ComfyUI, or A1111/Forge (started with --api)")
        self.url.editingFinished.connect(lambda: self.s.setValue("icons/image_url", self.url.text().strip()))
        self.detect_btn = QPushButton("Detect")
        self.detect_btn.clicked.connect(self.detect)
        url_row.addWidget(self.url, 1)
        url_row.addWidget(self.detect_btn)
        self.url_label = QLabel("Image AI")
        sf.addRow(self.url_label, url_row)
        self.perf = QComboBox(editable=True)
        self.perf.addItems(PERFORMANCE)
        self.perf.setCurrentText(self.s.value("icons/performance", ""))
        self.perf.setToolTip("Fooocus performance preset (empty = Fooocus' own setting)")
        self.perf.currentTextChanged.connect(lambda t: self.s.setValue("icons/performance", t))
        self.perf_label = QLabel("Fooocus speed")
        sf.addRow(self.perf_label, self.perf)
        sv.addLayout(sf)

        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.IconMode)
        self.grid.setIconSize(QSize(56, 56))
        self.grid.setGridSize(QSize(92, 92))
        self.grid.setResizeMode(QListWidget.Adjust)
        self.grid.setMovement(QListWidget.Static)
        self.grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.grid.setMinimumHeight(210)
        sv.addWidget(self.grid)

        row = QHBoxLayout()
        self.make_all = QPushButton(QIcon.fromTheme("tools-wizard"), "Make all")
        self.make_all.clicked.connect(lambda: self.make(None))
        self.remake = QPushButton(QIcon.fromTheme("view-refresh"), "Remake selected")
        self.remake.clicked.connect(lambda: self.make(self._selected() or None))
        remove = QPushButton(QIcon.fromTheme("edit-delete"), "Remove")
        remove.setToolTip("Remove the selected signature icons (the icon set's version is used again)")
        remove.clicked.connect(self.remove)
        row.addWidget(self.make_all)
        row.addWidget(self.remake)
        row.addWidget(remove)
        row.addStretch()
        sv.addLayout(row)
        row = QHBoxLayout()
        prompts = QPushButton(QIcon.fromTheme("edit-copy"), "Copy prompts…")
        prompts.setToolTip("Prompts and file names for making the icons in any image app (ArtCraft, Krita AI…)")
        prompts.clicked.connect(self.copy_prompts)
        imp = QPushButton(QIcon.fromTheme("document-import"), "Import images…")
        imp.setToolTip("Import a folder of images named after the icons, e.g. folder.png, user-home.png")
        imp.clicked.connect(self.import_dir)
        self.recut_btn = QPushButton(QIcon.fromTheme("edit-cut"), "Re-cut backgrounds")
        self.recut_btn.setToolTip("Cut the background out of the kept renders again (selected icons, or all).\n"
                                  "Uses rembg when it's installed here or in your image AI (Fooocus, ComfyUI…).")
        self.recut_btn.clicked.connect(self.recut)
        row.addWidget(prompts)
        row.addWidget(imp)
        row.addWidget(self.recut_btn)
        row.addStretch()
        sv.addLayout(row)
        self.status = QLabel(wordWrap=True)
        self.status.hide()
        sv.addWidget(self.status)
        v.addWidget(g)
        v.addStretch()
        self._mode_changed()

    # --- spec <-> form ------------------------------------------------------------------
    def load(self, theme: spec.Theme) -> None:
        ics = theme.iconset
        for w in (self.generate, self.base, self.style, self.mode, self.app_icons):
            w.blockSignals(True)
        self.generate.setChecked(ics.generate)
        self.app_icons.setChecked(ics.app_icons == "recolor")
        if self.base.findText(ics.base) < 0:
            self.base.addItem(ics.base)
        self.base.setCurrentText(ics.base)
        self.style.setText(ics.style)
        self.mode.setCurrentIndex(1 if ics.signature == "image" else 0)
        for w in (self.generate, self.base, self.style, self.mode, self.app_icons):
            w.blockSignals(False)
        self._mode_changed()
        self.refresh_grid()

    def store(self, theme: spec.Theme) -> None:
        ics = theme.iconset
        ics.generate = self.generate.isChecked()
        ics.base = self.base.currentText().strip()
        ics.style = self.style.text().strip()
        ics.app_icons = "recolor" if self.app_icons.isChecked() else "keep"

    def _mode_changed(self, *_):
        image = self.mode.currentData() == "image"
        for w in (self.url, self.url_label, self.detect_btn, self.perf, self.perf_label):
            w.setVisible(image)
        self.changed.emit()

    # --- grid ---------------------------------------------------------------------------
    def _sig_dir(self) -> Path | None:
        t = self.get_theme()
        if t.iconset.signature_dir:
            return Path(t.iconset.signature_dir)
        p = self.get_spec_path()
        return signature.default_dir(t, p) if p else None

    def refresh_grid(self):
        have = signature.existing(self._sig_dir())
        selected = set(self._selected())
        self.grid.clear()
        for slot in iconset.SLOTS:
            f = have.get(slot)
            icon = QIcon(QPixmap(str(f))) if f else QIcon.fromTheme("image-missing")
            item = QListWidgetItem(icon, slot.replace("folder-", "").replace("-", " ") if slot != "folder" else slot)
            item.setData(Qt.UserRole, slot)
            item.setToolTip(f"{slot}\n{iconset.SLOTS[slot][1]}\n" + (f"{f.parent.name} · {f.name}" if f else
                                                                       "not made yet — uses the icon set's version"))
            if not f:
                item.setForeground(self.palette().placeholderText())
            self.grid.addItem(item)
            item.setSelected(slot in selected)

    def _selected(self) -> list[str]:
        return [i.data(Qt.UserRole) for i in self.grid.selectedItems()]

    def _say(self, text: str, error: bool = False):
        self.status.setStyleSheet("color:#d4351c;" if error else "")
        self.status.setText(text)
        self.status.setVisible(bool(text))

    # --- actions ------------------------------------------------------------------------
    def detect(self):
        try:
            b = imagegen.detect(self.url.text().strip())
        except imagegen.ImageGenError as e:
            self._say(str(e), True)
            return
        self.s.setValue("icons/image_url", self.url.text().strip())
        self._say(f"Found {b.name} at {b.url}. Background removal: {imagegen.cutout_method()}.")

    def _prepare(self) -> tuple[spec.Theme, Path] | None:
        """Signature icons live next to the spec, so it must be saved first."""
        if not self.ensure_saved():
            return None
        theme = copy.deepcopy(self.get_theme())
        sig = self._sig_dir()
        return theme, sig

    def make(self, only: list[str] | None):
        if self.thread:
            return
        prep = self._prepare()
        if not prep:
            return
        theme, sig = prep
        if self.mode.currentData() == "image":
            url, perf = self.url.text().strip(), self.perf.currentText().strip()

            def job(log):
                return signature.generate_images(theme, sig, url, performance=perf, only=only, log=log)
        else:
            prov, key = current_provider()

            def job(log):
                return signature.generate_svg(theme, sig, prov, api_key=key, only=only, log=log)
        self._run(job, self.mode.currentData(), sig)

    def import_dir(self):
        prep = self._prepare()
        if not prep:
            return
        theme, sig = prep
        d = QFileDialog.getExistingDirectory(self, "Folder with icon images (named folder.png, user-home.png, …)")
        if not d:
            return
        try:
            done = signature.import_images(theme, sig, d)
        except Exception as e:
            QMessageBox.warning(self, "Import failed", str(e))
            return
        if not done:
            self._say("No matching files — name them after the icons, e.g. folder.png, user-trash.png "
                      "(see Copy prompts…).", True)
            return
        self._finished(done, "image", sig)

    def copy_prompts(self):
        QGuiApplication.clipboard().setText(signature.prompts_text(self.get_theme()))
        self._say("Prompts copied. Make each image in your app, save them with the file names shown, "
                  "then use Import images….")

    def recut(self):
        if self.thread:
            return
        sig = self._sig_dir()
        if not sig or not (sig / "raw").is_dir():
            self._say("No kept renders to re-cut (renders are kept from v0.1.17 on; remake the icons once).", True)
            return
        only = self._selected() or None
        self._run(lambda log: signature.recut(sig, only, log=log), "image", sig)

    def remove(self):
        slots = self._selected()
        sig = self._sig_dir()
        if slots and sig:
            signature.clear(sig, slots)
            self.refresh_grid()
            self.icons_changed.emit()

    def _run(self, job, mode, sig):
        self.make_all.setEnabled(False)
        self.remake.setEnabled(False)
        self._say("Starting…")
        self.thread = QThread(self)
        self.worker = _Worker(job)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._progress)
        self._job = (mode, sig)
        # Bound methods (not lambdas) so Qt delivers these on the GUI thread.
        self.worker.done.connect(self._job_done)
        self.worker.failed.connect(self._failed)
        self.thread.start()

    def _job_done(self, done: list):
        self._finished(done, *self._job)

    def _progress(self, s: str):
        self._say(s[:1].upper() + s[1:])

    def _failed(self, msg: str):
        self._stop()
        self._say(msg, True)

    def _finished(self, done: list, mode: str, sig: Path):
        self._stop()
        t = self.get_theme()
        t.iconset.generate = True
        t.iconset.signature = mode
        t.iconset.signature_dir = str(sig)
        self.generate.setChecked(True)
        self.refresh_grid()
        self._say(f"Made {len(done)} icon{'s' if len(done) != 1 else ''}. Save, then Apply to use them.")
        self.changed.emit()
        self.icons_changed.emit()

    def _stop(self):
        self.make_all.setEnabled(True)
        self.remake.setEnabled(True)
        if self.thread:
            self.thread.quit()
            self.thread.wait()
            self.thread = None
