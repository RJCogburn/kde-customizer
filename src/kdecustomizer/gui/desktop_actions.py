"""What reaches outside the editor, a mixin of `app.Main`: build, export (archive / KDE Store), Apply (summary ->
install.sh with the step-by-step window), Undo Apply and earlier restore points, installed themes, the setup
check and the new-release notice."""
from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import QProcess, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from .. import build as builder
from .apply_dialog import ApplyDialog
from .apply_summary import ApplySummary
from .manager import ThemeManager
from .preview import Preview


class DesktopActions:
    """Build, export, apply, undo, installed themes, setup check, update notice (a mixin of app.Main)."""

    def _build_root(self) -> Path:
        return self.path.parent / "build"

    def do_build(self) -> Path | None:
        """Build the theme next to its spec (saving it first if needed). Returns the build folder."""
        if not self.path and not self.save():      # builds live in the theme's own folder
            return None
        try:
            out = builder.build(copy.deepcopy(self.from_form()), self._build_root())
        except Exception as e:
            QMessageBox.critical(self, "Build failed", str(e))
            return None
        self.statusBar().showMessage(f"Built {out}", 6000)
        return out

    def export(self) -> None:
        """Save a shareable .tar.gz (the recipient runs ./install.sh)."""
        if not self.path and not self.save():
            return
        theme = self.from_form()
        f, _ = QFileDialog.getSaveFileName(self, "Export theme", f"{theme.slug}.tar.gz", "Theme archive (*.tar.gz)")
        if not f:
            return
        try:
            dest = builder.export(copy.deepcopy(theme), f, self._build_root())
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))
            return
        self.statusBar().showMessage(f"Exported {dest} — recipient extracts it and runs ./install.sh", 8000)

    def export_store(self) -> None:
        """One file per part for store.kde.org, a preview picture and UPLOAD.md, in a folder."""
        from .. import store
        if not self.path and not self.save():
            return
        theme = copy.deepcopy(self.from_form())
        d = QFileDialog.getExistingDirectory(self, "Folder for the KDE Store files", str(self.path.parent))
        if not d:
            return
        dest = Path(d) / f"{theme.slug}-kde-store"
        try:
            files = store.export(theme, dest, self._build_root())
            pv = Preview()
            pv.resize(1280, 800)
            pv.show_theme(theme)
            pv.grab().save(str(dest / "preview.png"))
        except Exception as e:
            QMessageBox.critical(self, "Export for the KDE Store", str(e))
            return
        r = QMessageBox.information(self, "Export for the KDE Store",
                                    f"{len(files)} files are in {dest}.\n\nUPLOAD.md there says which store "
                                    "category each one goes in.", QMessageBox.Open | QMessageBox.Ok)
        if r == QMessageBox.Open:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(dest)))

    def apply(self) -> None:
        """Build, show the Apply summary, then run install.sh with its options in the Apply window."""
        if self.proc.state() != QProcess.NotRunning:
            return
        t = self.theme
        out = self.do_build()       # first, so the summary can tell what changed since the last Apply
        if not out:
            return
        summary = ApplySummary(self, t, self.with_layout.isChecked(), out)
        if summary.exec() != QDialog.Accepted:
            return
        self.with_layout.setChecked(summary.replace_panels)
        if out:
            args = summary.args()
            self.say(f"$ {out / 'install.sh'} {' '.join(args)}".rstrip())
            dlg = ApplyDialog(self, t.name, out / "install.sh", args, summary.needs_password())
            dlg.output.connect(self.log.appendPlainText)
            dlg.exec()
            self.statusBar().showMessage(dlg.result_text, 8000)

    def history(self) -> None:
        from .history_dialog import HistoryDialog
        if self.proc.state() != QProcess.NotRunning:
            return
        dlg = HistoryDialog(self)
        if dlg.exec() == QDialog.Accepted and dlg.chosen:
            self.revert(dlg.chosen)

    def revert(self, point=None) -> None:
        """Run a restore point: the newest (asks first), or one picked in the history (already confirmed)."""
        from .. import restorepoints
        if self.proc.state() != QProcess.NotRunning:
            return
        pts = restorepoints.points()
        if not pts:
            QMessageBox.information(self, "Undo Apply", "There is nothing to undo yet: each Apply saves the desktop "
                                    "as it was first, and that's what Undo Apply restores.")
            return
        picked = isinstance(point, restorepoints.Point)     # (QAction.triggered passes a bool here)
        pt = point if picked else pts[0]
        if not picked:
            r = QMessageBox.question(self, "Undo Apply",
                                     f"Restore the desktop as it was {pt.label()}?\n\n"
                                     "Colors, styles, icons, cursors, fonts, wallpaper, tweaks and terminal/GTK colors "
                                     "go back. The login screen and boot splash stay as they are.")
            if r != QMessageBox.Yes:
                return

        def done(code: int) -> str:
            if code:
                return f"restore failed (exit {code}) — see Output"
            import shutil
            shutil.rmtree(pt.path, ignore_errors=True)      # the next Undo goes one step further back
            return "Desktop restored."
        self.say(f"$ bash {pt.script}")
        self._proc_done = done
        self.proc.start("bash", [str(pt.script)])

    def manage_themes(self) -> None:
        dlg = ThemeManager(self)
        dlg.update_requested.connect(self._update_installed)
        dlg.exec()
        if self.stack.currentIndex() == 0:
            self.start.refresh(recovery=not self._kept)

    def _update_installed(self, path: str) -> None:
        """Installed themes › Update: open the changed theme file and go through Apply again."""
        p = Path(path)
        if p != self.path or self.dirty:
            if not self._confirm_discard():
                return
            self.load(p)
        if self.path == p:
            self.show_editor()
            QTimer.singleShot(0, self.apply)

    def setup_check(self) -> None:
        from .setup_dialog import SetupDialog
        SetupDialog(self, [self.icons_tab.url.text().strip()]).exec()

    def _check_updates(self) -> None:
        """AppImage / tarball only, at most once a day: look for a newer release on a worker thread."""
        import time
        from PySide6.QtCore import QSettings, QThread
        from .. import updates
        from .icons_tab import _Worker
        st = QSettings("kdecustomizer", "kdec-gui")
        if (not updates.self_managed() or not st.value("updates/check", True, bool)
                or time.time() - float(st.value("updates/last", 0) or 0) < 86400):
            return
        st.setValue("updates/last", time.time())
        self._upd_thread = QThread(self)
        self._upd_worker = _Worker(lambda _log: list(updates.check() or []))
        self._upd_worker.moveToThread(self._upd_thread)
        self._upd_thread.started.connect(self._upd_worker.run)
        self._upd_worker.done.connect(self._update_found)      # bound method: runs on the GUI thread
        self._upd_worker.failed.connect(self._update_found)
        self._upd_thread.start()

    def _update_found(self, found) -> None:
        self._upd_thread.quit()
        self._upd_thread.wait()
        if isinstance(found, list) and found:
            self.start.show_update(*found)
