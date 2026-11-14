"""AI panel: describe a theme, the preview updates when the AI answers. Logic lives in kdecustomizer.ai."""
from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, QThread, Signal
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QToolButton, QVBoxLayout, QWidget,
)

from .. import ai, spec


def _settings() -> QSettings:
    return QSettings("kdecustomizer", "kdec-gui")


def current_provider() -> tuple[ai.Provider, str | None]:
    s = _settings()
    key = s.value("ai/provider", "claude-code")
    prov = replace(ai.PRESETS.get(key, ai.PRESETS["claude-code"]))
    prov.model = s.value(f"ai/{key}/model", prov.model) or prov.model
    prov.base_url = s.value(f"ai/{key}/base_url", prov.base_url) or prov.base_url
    return prov, (s.value(f"ai/{key}/api_key", "") or None)


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI settings")
        self.s = _settings()
        f = QFormLayout(self)
        self.provider = QComboBox()
        for k, p in ai.PRESETS.items():
            self.provider.addItem(p.name, k)
        self.model = QLineEdit()
        self.base_url = QLineEdit()
        self.key = QLineEdit(echoMode=QLineEdit.Password)
        self.key_hint = QLabel(wordWrap=True)
        self.key_hint.setStyleSheet("color: palette(placeholder-text);")
        f.addRow("Provider", self.provider)
        f.addRow("Model", self.model)
        f.addRow("API URL", self.base_url)
        f.addRow("API key", self.key)
        f.addRow(self.key_hint)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self.provider.currentIndexChanged.connect(self._load)
        self.provider.setCurrentIndex(max(0, self.provider.findData(self.s.value("ai/provider", "claude-code"))))
        self._load()

    def _key(self) -> str:
        return self.provider.currentData()

    def _load(self, *_):
        k = self._key()
        p = ai.PRESETS[k]
        self.model.setText(self.s.value(f"ai/{k}/model", p.model))
        self.model.setPlaceholderText(p.model or "required, e.g. the model's id at this provider")
        self.base_url.setText(self.s.value(f"ai/{k}/base_url", p.base_url))
        self.base_url.setEnabled(p.kind == "openai")
        self.key.setText(self.s.value(f"ai/{k}/api_key", ""))
        self.key.setEnabled(p.kind != "claude-code")
        if p.kind == "claude-code":
            self.model.setPlaceholderText("your Claude Code default (or: opus, sonnet, haiku)")
            self.key_hint.setText("Uses your Claude Code sign-in — the same account as the VS Code extension. "
                                  "No API key; requests count toward your Claude plan. If it says you're not "
                                  "signed in, run `claude` in a terminal once and log in.")
            return
        env ="ANTHROPIC_API_KEY (or `ant auth login`)" if p.kind == "anthropic" else p.key_env
        self.key_hint.setText(
            (f"Leave empty to use {env} from your environment. " if env else "No key needed for local models. ")
            + "A key entered here is stored unencrypted in ~/.config/kdecustomizer/.")

    def _save(self):
        k = self._key()
        self.s.setValue("ai/provider", k)
        self.s.setValue(f"ai/{k}/model", self.model.text().strip())
        self.s.setValue(f"ai/{k}/base_url", self.base_url.text().strip())
        self.s.setValue(f"ai/{k}/api_key", self.key.text().strip())
        self.accept()


class _Worker(QObject):
    progress = Signal(str)
    done = Signal(object, str, list)
    failed = Signal(str)

    def __init__(self, request, theme, prov, key, use_wp, refs):
        super().__init__()
        self.args = (request, theme, prov, key, use_wp, refs)

    def run(self):
        request, theme, prov, key, use_wp, refs = self.args
        try:
            result = ai.generate(request, theme, prov, api_key=key, use_wallpaper=use_wp, references=refs,
                                 log=self.progress.emit)
        except ai.AIError as e:
            self.failed.emit(str(e))
        except Exception as e:  # network/SDK surprises shouldn't kill the GUI
            self.failed.emit(f"{type(e).__name__}: {e}")
        else:
            self.done.emit(*result)


class AIPanel(QWidget):
    """Emits `theme_ready(theme)`; the main window applies it (and keeps undo history)."""
    theme_ready = Signal(object)

    def __init__(self, get_theme):
        super().__init__()
        self.get_theme = get_theme
        self.thread: QThread | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 4)
        v.setSpacing(6)

        head = QHBoxLayout()
        title = QLabel("<b>Design with AI</b>")
        self.provider_label = QLabel()
        self.provider_label.setStyleSheet("color: palette(placeholder-text);")
        gear = QToolButton(icon=QIcon.fromTheme("configure"), toolTip="AI settings")
        gear.clicked.connect(self.settings)
        more = QToolButton(icon=QIcon.fromTheme("application-menu"), toolTip="Use any AI without an API key")
        more.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(more)
        menu.addAction(QAction("Copy prompt for any chat AI", self, triggered=self.copy_prompt))
        menu.addAction(QAction("Paste AI reply…", self, triggered=self.paste_reply))
        menu.addSeparator()
        menu.addAction(QAction("Copy spec guide (for coding agents)", self,
                               triggered=lambda: self._copy(ai.reference(), "Spec guide copied")))
        more.setMenu(menu)
        head.addWidget(title)
        head.addStretch()
        head.addWidget(self.provider_label)
        head.addWidget(gear)
        head.addWidget(more)
        v.addLayout(head)

        self.prompt = QPlainTextEdit(placeholderText="Describe a theme or a change… e.g. “cozy autumn, warm browns, "
                                                     "dock-style bottom panel” or “make the accent teal”")
        self.prompt.setFixedHeight(64)
        v.addWidget(self.prompt)

        self.refs: list[str] = []
        self.refs_list = QListWidget()
        self.refs_list.setFixedHeight(58)
        self.refs_list.setToolTip("Reference files the AI builds the theme from — select and press Delete to remove")
        self.refs_list.hide()
        v.addWidget(self.refs_list)
        QShortcut(QKeySequence.Delete, self.refs_list, activated=self._remove_selected_refs)
        self.setAcceptDrops(True)

        row = QHBoxLayout()
        attach = QPushButton(QIcon.fromTheme("mail-attachment"), "Attach")
        attach.setToolTip("Add images, PDFs (brochure, brand guide, mood board…), Word or text files — or a\n"
                          "link to one — to design from. You can also drag files or links onto this panel.")
        attach_menu = QMenu(attach)
        attach_menu.addAction(QAction(QIcon.fromTheme("document-open"), "Files…", self, triggered=self.pick_refs))
        attach_menu.addAction(QAction(QIcon.fromTheme("link"), "Link (URL)…", self, triggered=self.pick_link))
        attach.setMenu(attach_menu)
        row.addWidget(attach)
        self.use_wp = QCheckBox("Match wallpaper")
        self.use_wp.setToolTip("Send the wallpaper image so the palette is drawn from it")
        self.use_wp.setChecked(True)
        self.go = QPushButton(QIcon.fromTheme("tools-wizard"), "Generate")
        self.go.setDefault(True)
        self.go.clicked.connect(self.generate)
        self.undo = QPushButton(QIcon.fromTheme("edit-undo"), "Undo")
        self.undo.setEnabled(False)
        row.addWidget(self.use_wp)
        row.addStretch()
        row.addWidget(self.undo)
        row.addWidget(self.go)
        v.addLayout(row)

        self.status = QLabel(wordWrap=True)
        self.status.setTextFormat(Qt.PlainText)
        self.status.hide()
        v.addWidget(self.status)
        self._show_provider()

    def _show_provider(self):
        prov, _ = current_provider()
        self.provider_label.setText(f"{prov.name}{' · ' + prov.model if prov.model else ''}")

    # --- reference attachments ------------------------------------------------------
    def add_refs(self, paths: list[str]):
        bad = []
        for path in paths:
            ext = Path(path).suffix.lower()
            if ai.is_url(path):
                if path not in self.refs:
                    self.refs.append(path)  # type is checked when it's downloaded
            elif ext not in ai.IMAGE_EXT | ai.TEXT_EXT | {".pdf", ".docx"}:
                bad.append(Path(path).name)
            elif path not in self.refs:
                self.refs.append(path)
        self._show_refs()
        if bad:
            self._say("Can't use: " + ", ".join(bad) + " — attach images, PDFs, .docx or text files.", True)

    def _show_refs(self):
        self.refs_list.clear()
        for path in self.refs:
            p = Path(path.split("?")[0])
            icon = ("image-x-generic" if p.suffix.lower() in ai.IMAGE_EXT else
                    "application-pdf" if p.suffix.lower() == ".pdf" else "text-x-generic")
            label = p.name or path
            if ai.is_url(path):
                icon, label = ("application-pdf" if icon == "application-pdf" else "link"), f"{label}  (link)"
            item = QListWidgetItem(QIcon.fromTheme(icon), label)
            item.setToolTip(path)
            self.refs_list.addItem(item)
        self.refs_list.setVisible(bool(self.refs))

    def _remove_selected_refs(self):
        for item in self.refs_list.selectedItems():
            self.refs.remove(item.toolTip())
        self._show_refs()

    def pick_refs(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Attach reference files", str(Path.home()),
                                                ai.ATTACH_FILTER + ";;All files (*)")
        if files:
            self.add_refs(files)

    def pick_link(self):
        clip = QGuiApplication.clipboard().text().strip()
        url, ok = QInputDialog.getText(self, "Attach a link", "URL of a PDF, image or page to design from:",
                                       text=clip if ai.is_url(clip) else "")
        if ok and url.strip():
            if not ai.is_url(url):
                self._say("That doesn't look like an http(s) link.", True)
                return
            self.add_refs([url.strip()])

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_refs([u.toLocalFile() if u.isLocalFile() else u.toString()
                       for u in e.mimeData().urls() if u.isLocalFile() or u.scheme() in ("http", "https")])

    def _say(self, text: str, error: bool = False):
        self.status.setStyleSheet("color:#d4351c;" if error else "")
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def _copy(self, text: str, msg: str):
        QGuiApplication.clipboard().setText(text)
        self._say(msg)

    def settings(self):
        if SettingsDialog(self).exec():
            self._show_provider()

    def copy_prompt(self):
        self._copy(ai.prompt_text(self.prompt.toPlainText(), self.get_theme(), self.refs),
                   "Prompt copied — paste it into any chat AI"
                   + (" and attach your reference files there too" if self.refs else "")
                   + ", then use “Paste AI reply…” with its answer.")

    def paste_reply(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Paste AI reply")
        lay = QVBoxLayout(dlg)
        box = QPlainTextEdit(placeholderText="Paste the AI's whole answer (the ```toml block is found automatically)")
        box.setPlainText(QGuiApplication.clipboard().text())
        lay.addWidget(box)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        dlg.resize(560, 420)
        if not dlg.exec():
            return
        try:
            theme = ai.parse_reply(box.toPlainText(), self.get_theme())
        except ValueError as e:
            QMessageBox.warning(self, "Couldn't read the reply", str(e))
            return
        self.theme_ready.emit(theme)
        problems = ai.check(theme)
        self._say("Applied pasted theme." + ("\n⚠ " + "\n⚠ ".join(problems) if problems else ""), bool(problems))

    def generate(self):
        if self.thread:
            return
        prov, key = current_provider()
        theme = copy.deepcopy(self.get_theme())
        self.go.setEnabled(False)
        self.go.setText("Working…")
        self._say(f"Asking {prov.name}…")
        self.thread = QThread(self)
        self.worker = _Worker(self.prompt.toPlainText(), theme, prov, key, self.use_wp.isChecked(), list(self.refs))
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        # Bound methods of this widget (not lambdas) so Qt queues them onto the GUI thread.
        self.worker.progress.connect(self._progress)
        self.worker.done.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.thread.start()

    def _progress(self, s: str):
        self._say(s[:1].upper() + s[1:])

    def _failed(self, msg: str):
        self._finish(msg, True)

    def _done(self, theme, note, problems):
        self.theme_ready.emit(theme)
        text = note or "Theme updated."
        if problems:
            text += "\n⚠ " + "\n⚠ ".join(problems)
        self._finish(text, bool(problems))

    def _finish(self, text: str, error: bool):
        self._say(text, error)
        self.go.setEnabled(True)
        self.go.setText("Generate")
        self.thread.quit()
        self.thread.wait()
        self.thread = None
