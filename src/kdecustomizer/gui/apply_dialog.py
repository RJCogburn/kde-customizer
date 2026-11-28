"""Apply to desktop, step by step: runs install.sh, shows its `==> step` lines as a checklist (full output under
"Details"), then asks "Keep these changes?" with a countdown — no answer puts the desktop back from the restore
point this install just took (like the display settings' confirmation)."""
from __future__ import annotations

import html
import shutil
from pathlib import Path

from PySide6.QtCore import QProcess, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit, QProgressBar,
    QPushButton, QVBoxLayout,
)

from .. import failures, restorepoints

KEEP_SECONDS = 20

# install.sh step text -> what the user reads
STEP_NAMES = {
    "color scheme": "Color scheme", "konsole": "Konsole colors", "plasma style": "Plasma style",
    "icon theme": "Icons", "cursor theme": "Cursors", "app style (Kvantum)": "App style (Kvantum)",
    "window decoration": "Title bars", "gtk 4 / libadwaita": "GNOME / GTK apps", "wallpaper": "Wallpaper",
    "global theme package": "Global theme package", "applying": "Applying the theme", "tweaks": "Tweaks",
    "settings": "Fonts and settings", "GTK 4 / libadwaita apps": "GNOME / GTK apps", "terminals": "Terminals",
    "Firefox / Thunderbird": "Firefox / Thunderbird",
    "login screen": "Login screen", "boot splash": "Boot splash", "reloading KWin": "Reloading the window manager",
}


def step_label(text: str) -> str:
    if text.startswith("asking for the admin password"):
        return "Waiting for your admin password"
    return STEP_NAMES.get(text, text[:1].upper() + text[1:])


class ApplyDialog(QDialog):
    """Runs install.sh with a checklist of its steps, then the keep-or-undo countdown."""

    output = Signal(str)            # every line of output, for the main window's log

    def __init__(self, parent, theme_name: str, script: Path, args: list[str], needs_password: bool):
        super().__init__(parent)
        self.setWindowTitle(f"Applying {theme_name}")
        self.setMinimumWidth(480)
        self.result_text = ""
        self._point: restorepoints.Point | None = None
        self._before = {p.path.name for p in restorepoints.points()}
        self._left = KEEP_SECONDS
        self._phase = "install"     # install -> keep? -> undo -> done

        v = QVBoxLayout(self)
        self.heading = QLabel(f"Installing and applying “{theme_name}”…")
        f = QFont(self.heading.font())
        f.setBold(True)
        self.heading.setFont(f)
        self.heading.setWordWrap(True)
        v.addWidget(self.heading)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setVisible(needs_password)
        self.note.setText("The login screen and boot splash are system-wide: you'll be asked for your admin "
                          "password if they changed since the last time.")
        v.addWidget(self.note)
        self.why = QLabel()                 # after a failure: what probably went wrong, in plain words
        self.why.setWordWrap(True)
        self.why.setTextFormat(Qt.RichText)
        self.why.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.why.setStyleSheet("QLabel { background: rgba(218, 68, 83, 0.12); border: 1px solid "
                               "rgba(218, 68, 83, 0.5); border-radius: 5px; padding: 6px 8px; }")
        self.why.hide()
        v.addWidget(self.why)
        self.steps = QListWidget()
        self.steps.setMinimumHeight(220)
        v.addWidget(self.steps, 1)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        v.addWidget(self.bar)
        self.log = QPlainTextEdit(readOnly=True)
        self.log.setFont(QFont("monospace"))
        self.log.setVisible(False)
        self.log.setMinimumHeight(180)
        v.addWidget(self.log, 1)

        row = QHBoxLayout()
        self.details = QPushButton(QIcon.fromTheme("view-list-text"), "Details")
        self.details.setCheckable(True)
        self.details.toggled.connect(self.log.setVisible)
        row.addWidget(self.details)
        row.addStretch()
        self.buttons = QDialogButtonBox()
        self.keep = self.buttons.addButton("Keep changes", QDialogButtonBox.AcceptRole)
        self.undo = self.buttons.addButton("Undo", QDialogButtonBox.DestructiveRole)
        self.close_btn = self.buttons.addButton(QDialogButtonBox.Close)
        self.keep.clicked.connect(self._keep)
        self.undo.clicked.connect(self._undo)
        self.close_btn.clicked.connect(self.accept)
        for b in (self.keep, self.undo, self.close_btn):
            b.setVisible(False)
        row.addWidget(self.buttons)
        v.addLayout(row)

        self.timer = QTimer(self, interval=1000)
        self.timer.timeout.connect(self._tick)
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyRead.connect(self._read)
        self.proc.finished.connect(self._finished)
        self._buf = ""
        self._current: QListWidgetItem | None = None
        self.proc.start(str(script), args)

    # --- output -------------------------------------------------------------------
    def _read(self) -> None:
        self._buf += bytes(self.proc.readAll()).decode(errors="replace")
        *lines, self._buf = self._buf.split("\n")
        for line in lines:
            self._line(line)

    def _line(self, line: str) -> None:
        """One output line: '==> step' starts a checklist row; known status lines annotate the current row."""
        self.log.appendPlainText(line)
        self.output.emit(line)
        if line.startswith("==> "):
            self._step(step_label(line[4:].strip()))
        elif self._current is not None and line.strip() and (
                line.startswith(("skipped", "already up to date", "not updated", "Neither", "Plymouth is not",
                                 "Kvantum is not"))):
            if line.startswith("skipped"):
                self._current.setText(self._current.text().split("  —")[0] + "  — left as it is")
                self._current.setToolTip(line.strip())
                return
            self._current.setToolTip(line.strip())
            self._current.setText(f"{self._current.text().split('  —')[0]}  — {line.strip()}")

    def _step(self, label: str) -> None:
        self._done_current()
        self._current = QListWidgetItem(QIcon.fromTheme("media-playback-start"), label)
        self.steps.addItem(self._current)
        self.steps.scrollToItem(self._current)

    def _done_current(self, ok: bool = True) -> None:
        if self._current is not None:
            self._current.setIcon(QIcon.fromTheme("checkmark" if ok else "dialog-error",
                                                  QIcon.fromTheme("dialog-ok" if ok else "dialog-cancel")))

    # --- phases -------------------------------------------------------------------
    def _finished(self, code: int, _status=None) -> None:
        """install.sh (or the undo) ended: show the result, explain a failure, or start the keep-or-undo countdown."""
        if self._buf:
            self._line(self._buf)
            self._buf = ""
        self._done_current(code == 0)
        self._current = None
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        if self._phase == "undo":
            if code == 0 and self._point:
                shutil.rmtree(self._point.path, ignore_errors=True)     # used up, like `kdec revert`
            self._end("The previous desktop is back." if code == 0 else
                      f"Restoring failed (exit {code}). See Details.", code == 0)
            self.result_text = "Desktop restored." if code == 0 else f"restore failed (exit {code})"
            return
        if code != 0:
            self.details.setChecked(True)
            self._end(f"Something went wrong (exit {code}). Undo Apply can put the desktop back.", False)
            self.show_reasons(self.log.toPlainText(), code)
            self.result_text = f"install.sh failed (exit {code})"
            return
        self.result_text = "Applied."
        new = [p for p in restorepoints.points() if p.path.name not in self._before]
        if not new:
            self._end("Applied.", True)
            return
        self._point = new[0]
        self._phase = "keep"
        self.keep.setVisible(True)
        self.undo.setVisible(True)
        self.keep.setDefault(True)
        self.keep.setFocus()
        self._tick(start=True)
        self.timer.start()

    def show_reasons(self, output: str, code: int) -> None:
        """Plain-language causes of a failure (failures.explain), else the last error line."""
        reasons = failures.explain(output, code)
        if reasons:
            items = "".join(f"<li>{html.escape(r)}</li>" for r in reasons)
            self.why.setText(f"<b>What probably went wrong</b><ul style='margin:2px 0 0 -20px'>{items}</ul>")
        else:
            last = failures.last_error(output)
            self.why.setText("<b>The last error was:</b><br><code>" + html.escape(last) + "</code>" if last else
                             "The output below shows where it stopped.")
        self.why.show()

    def _tick(self, start: bool = False) -> None:
        if not start:
            self._left -= 1
        if self._left <= 0:
            self._undo()
            return
        self.heading.setText(f"Applied. Keep these changes?\nGoing back to how it was in {self._left} s.")
        self.bar.setRange(0, KEEP_SECONDS)
        self.bar.setValue(self._left)

    def _keep(self) -> None:
        self.timer.stop()
        self.result_text = "Applied."
        self.accept()

    def _undo(self) -> None:
        """Run the restore point this install took (Undo button, Esc, or the countdown ran out)."""
        self.timer.stop()
        if self._phase != "keep" or not self._point:
            return
        self._phase = "undo"
        self.keep.setVisible(False)
        self.undo.setVisible(False)
        self.heading.setText("Putting the previous desktop back…")
        self.bar.setRange(0, 0)
        self._step("Restoring the previous desktop")
        self.log.appendPlainText(f"$ bash {self._point.script}")
        self.proc.start("bash", [str(self._point.script)])

    def _end(self, text: str, ok: bool) -> None:
        self._phase = "done"
        self.heading.setText(text)
        if not ok:
            self.heading.setStyleSheet("color: palette(link-visited)")
        self.close_btn.setVisible(True)
        self.close_btn.setFocus()

    # --- closing ------------------------------------------------------------------
    def reject(self) -> None:
        """Esc / window close: never mid-run; during the countdown it means Undo, like the display settings."""
        if self._phase == "keep":
            self._undo()
        elif self._phase == "done":
            super().reject()
