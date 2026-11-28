"""Editor state, a mixin of `app.Main`: form <-> Theme (`to_form` / `from_form`), what happens after every edit
(preview refresh, compare view, icon-preview rebuild on a worker thread, problem strip, contrast), undo/redo as
whole-Theme snapshots, and the autosave kept for recovery."""
from __future__ import annotations

import copy
import html
import re
from pathlib import Path

from PySide6.QtCore import QStandardPaths, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QComboBox, QMessageBox

from .. import ai, color, iconset, library, spec
from .preview import Preview


class Editing:
    """Form <-> Theme, the reactions to an edit, undo/redo and autosave (a mixin of app.Main)."""

    def to_form(self) -> None:
        """Fill every section's fields from self.theme (`_loading` is set meanwhile: loading isn't an edit)."""
        self._loading = True
        t = self.theme
        for k, w in self.text.items():
            val = getattr(t, k)
            w.setCurrentText(val) if isinstance(w, QComboBox) else w.setText(val)
        self.description.setPlainText(t.description)
        for k, cf in self.colors.items():
            cf.set(getattr(t.palette, k))
        for k, c in self.plasma.items():
            c.setChecked(getattr(t.plasma, k))
        self.s_generate.setChecked(t.splash_screen.generate)
        self.s_background.setCurrentText(t.splash_screen.background)
        self.s_text.setText(t.splash_screen.text)
        self._splash_generate_toggled(t.splash_screen.generate)
        self.b_generate.setChecked(t.boot_splash.generate)
        self.b_background.setCurrentText(t.boot_splash.background)
        self.b_text.setText(t.boot_splash.text)
        self.b_background.setEnabled(t.boot_splash.generate)
        self.b_text.setEnabled(t.boot_splash.generate)
        self.l_generate.setChecked(t.login_screen.generate)
        self.l_background.setCurrentText(t.login_screen.background)
        self.l_clock.setChecked(t.login_screen.clock)
        self._login_generate_toggled(t.login_screen.generate)
        self.c_generate.setChecked(t.cursorset.generate)
        self.c_base.setCurrentText(t.cursorset.base)
        self.c_fill.setCurrentText(t.cursorset.fill)
        self._cursor_generate_toggled(t.cursorset.generate)
        self.w_generate.setChecked(t.widgets.generate)
        self.w_radius.setValue(t.widgets.radius)
        self.w_radius.setEnabled(t.widgets.generate)
        self.p_radius.setValue(t.plasma.radius)
        self.p_opacity.setValue(round(t.plasma.opacity * 100))
        self._plasma_generate_toggled(t.plasma.generate)
        self.konsole.setChecked(t.konsole)
        self.g_generate.setChecked(t.gtk.generate)
        for k, c in self.apps.items():
            c.setChecked(getattr(t.apps, k))
        self.g_flatpak.setChecked(t.gtk.flatpak)
        self.g_flatpak.setEnabled(t.gtk.generate)
        self.light_dark.setChecked(t.light_dark.auto)
        for k, w in self.deco.items():
            w.setText(getattr(t.decoration, k))
        d = t.decoration
        self.d_generate.setChecked(d.generate)
        self.d_radius.setValue(d.radius)
        self.d_height.setValue(d.title_height)
        self.d_border.setValue(d.border)
        self.d_align.setCurrentText(d.title_align)
        self.d_style.setCurrentText(d.button_style)
        self._deco_generate_toggled(d.generate)
        for k, ff in self.fonts.items():
            ff.edit.setText(getattr(t.fonts, k))
        self._fill_panel_list()
        self._tweaks_to_form(t.tweaks)
        self.icons_tab.load(t)
        self.text["icons"].setEnabled(not t.iconset.generate)
        self._loading = False
        self._after_change()

    def from_form(self) -> spec.Theme:
        """Read every section's fields into self.theme and return it."""
        t = self.theme
        for k, w in self.text.items():
            setattr(t, k, (w.currentText() if isinstance(w, QComboBox) else w.text()).strip())
        t.description = self.description.toPlainText().strip()
        for k, cf in self.colors.items():
            try:
                color.parse(cf.value)
                setattr(t.palette, k, cf.value)
            except ValueError:
                pass  # keep last valid color while the user is mid-typing
        for k, c in self.plasma.items():
            setattr(t.plasma, k, c.isChecked())
        t.splash_screen.generate = self.s_generate.isChecked()
        t.splash_screen.background = self.s_background.currentText()
        t.splash_screen.text = self.s_text.text().strip()
        t.boot_splash.generate = self.b_generate.isChecked()
        t.boot_splash.background = self.b_background.currentText()
        t.boot_splash.text = self.b_text.text().strip()
        t.login_screen.generate = self.l_generate.isChecked()
        t.login_screen.background = self.l_background.currentText()
        t.login_screen.clock = self.l_clock.isChecked()
        t.cursorset.generate = self.c_generate.isChecked()
        t.cursorset.base = self.c_base.currentText().strip() or "breeze_cursors"
        t.cursorset.fill = self.c_fill.currentText()
        t.widgets.generate = self.w_generate.isChecked()
        t.widgets.radius = self.w_radius.value()
        t.plasma.radius = self.p_radius.value()
        t.plasma.opacity = self.p_opacity.value() / 100
        t.konsole = self.konsole.isChecked()
        t.gtk.generate = self.g_generate.isChecked()
        for k, c in self.apps.items():
            setattr(t.apps, k, c.isChecked())
        t.gtk.flatpak = self.g_flatpak.isChecked()
        t.light_dark.auto = self.light_dark.isChecked()
        t.tweaks = self._tweaks_from_form()
        for k, w in self.deco.items():
            setattr(t.decoration, k, w.text().strip())
        d = t.decoration
        d.generate = self.d_generate.isChecked()
        d.title_height = self.d_height.value()
        d.radius = min(self.d_radius.value(), d.title_height // 2)
        d.border = self.d_border.value()
        d.title_align = self.d_align.currentText()
        d.button_style = self.d_style.currentText()
        for k, ff in self.fonts.items():
            setattr(t.fonts, k, ff.edit.text().strip())
        self.icons_tab.store(t)
        return t

    def changed(self, *_) -> None:
        if self._loading:
            return
        self.from_form()
        if not self.dirty:
            self.dirty = True
            self._update_title()
        self._commit_timer.start()
        self._after_change()

    def _after_change(self) -> None:
        self._refresh.start()
        self._update_contrast()
        self._check_timer.start()
        ics = self.theme.iconset
        key = (ics.generate, ics.base, ics.signature_dir, ics.custom_dir, ics.app_icons, self.theme.palette.accent,
               self.theme.slug)
        if ics.generate and key != self._icons_key:
            self._icons_timer.start()

    def _show_preview(self) -> None:
        self.preview.show_theme(self.theme)
        if self.compare_btn.isChecked():
            self._update_compare()

    def set_compare(self, on: bool) -> None:
        """Show or hide the compare view; the first time, snapshot the running desktop once."""
        if on and self._now_theme is None:
            from .. import snapshot
            try:
                self._now_theme = snapshot.take("Your desktop now")
            except Exception as e:      # unreadable config
                QMessageBox.warning(self, "Compare", f"Can't read your current desktop: {e}")
                self.compare_btn.setChecked(False)
                return
            # both sides from offscreen previews: resizing the live one (a page of the same stack) loops
            self._now_preview, self._then_preview = Preview(), Preview()
        self.right_stack.setCurrentIndex(1 if on else 0)
        if on:
            self._update_compare()

    def _update_compare(self) -> None:
        """Render both sides offscreen at the compare view's size (guarded: resizing triggers it again)."""
        if not self.compare_btn.isChecked() or self._now_preview is None or getattr(self, "_comparing", False):
            return
        self._comparing = True
        try:
            images = []
            for pv, theme in ((self._now_preview, self._now_theme), (self._then_preview, self.theme)):
                pv.resize(self.compare.size())
                pv.set_popup(self.popup.currentData())
                pv.set_vision(self.vision.currentData())
                pv.show_theme(theme)
                images.append(pv.grab())
            self.compare.set_images(*images, self.theme.name or "This theme")
        finally:
            self._comparing = False

    def _schedule_icons(self) -> None:
        self._icons_key = None
        self._icons_timer.start()

    def _build_preview_icons(self) -> None:
        """Rebuild the generated icon set the preview draws from, on a worker thread (~0.1 s with restyled app
        icons; it runs after every accent change). Builds alternate between two cache folders, so the preview
        never reads a half-written set; the icon search path switches once a build is done."""
        from PySide6.QtCore import QThread
        from .icons_tab import _Worker
        t = self.theme
        if not t.iconset.generate:
            return
        if getattr(self, "_icons_thread", None):       # one at a time; the newest edit is built next
            self._icons_again = True
            return
        self._icons_again = False
        theme = copy.deepcopy(t)
        self._icons_gen = getattr(self, "_icons_gen", 0) + 1
        out = Path(QStandardPaths.writableLocation(QStandardPaths.CacheLocation)) / "preview-icons" / \
            f"set{self._icons_gen % 2}"

        def job(_log):
            iconset.build(theme, out, only=iconset.preview_names())     # just what the preview draws
            ics = theme.iconset
            return [str(out), (ics.generate, ics.base, ics.signature_dir, ics.custom_dir, ics.app_icons,
                               theme.palette.accent, theme.slug)]
        self._icons_thread = QThread(self)
        self._icons_worker = _Worker(job)
        self._icons_worker.moveToThread(self._icons_thread)
        self._icons_thread.started.connect(self._icons_worker.run)
        self._icons_worker.done.connect(self._preview_icons_done)       # bound methods: run on the GUI thread
        self._icons_worker.failed.connect(self._preview_icons_failed)
        self._icons_thread.start()

    def _stop_icons_thread(self) -> None:
        self._icons_thread.quit()
        self._icons_thread.wait()
        self._icons_thread = None
        if self._icons_again:
            self._build_preview_icons()

    def _preview_icons_done(self, result: list) -> None:
        root, self._icons_key = result[0], tuple(result[1])
        parent = str(Path(root).parent)
        paths = [p for p in QIcon.themeSearchPaths() if not p.startswith(parent)]
        QIcon.setThemeSearchPaths([root, *paths])       # also makes Qt drop its cached lookups
        self.preview.icons.clear()
        self.preview.update()
        self._stop_icons_thread()

    def _preview_icons_failed(self, msg: str) -> None:     # missing base theme, unreadable files…
        self.statusBar().showMessage(f"Icon preview: {msg}", 6000)
        self._stop_icons_thread()

    def _update_problems(self) -> None:
        """`kdec check` on the theme being edited; each problem links to the tab where it's fixed."""
        try:
            found = ai.check(self.theme, self.installed)
        except Exception:           # half-typed values: check again on the next edit
            return
        tabs = {"contrast": 1, "iconset": 3, "icons": 2, "cursor": 2, "widget": 2, "plasma": 2, "splash": 2,
                "login": 2, "wallpaper": 2}

        def tab(p: str) -> int:
            return next((i for k, i in tabs.items() if p.startswith(k) or p.split()[0].startswith(k)), 1)
        names = [self.tabs.tabText(i) for i in range(self.tabs.count())]

        def text(p: str) -> str:        # the full lists of installed themes are too long for the strip
            return html.escape(re.sub(r" \((installed|usable): [^)]*\)", "", p))
        items = "".join(f"<li>{text(p)} — <a href='tab:{tab(p)}'>{names[tab(p)]}</a></li>" for p in found)
        n = len(found)
        self.problems.setText(f"<b>⚠ {n} thing{'s' if n > 1 else ''} to check</b>"
                              f"<ul style='margin:2px 0 0 -20px'>{items}</ul>")
        self.problems.setVisible(bool(found))

    def _commit(self) -> None:
        """Make the current theme one undo step (if it changed since the last one)."""
        self._commit_timer.stop()
        if self.theme == self._committed:
            return
        self._undo_stack.append(self._committed)
        del self._undo_stack[:-100]
        self._committed = copy.deepcopy(self.theme)
        self._redo_stack.clear()
        self._update_undo()
        if self.dirty:
            self._autosave()

    def _autosave(self) -> None:
        try:
            text = spec.dumps(self.theme)
        except Exception:           # half-typed values: keep the last good copy
            return
        library.autosave(text, self.path, self.theme.name)
        self._kept = True

    def _drop_autosave(self) -> None:
        """Only ever the copy this window kept: another session's leftovers wait for Recover/Discard."""
        if self._kept:
            library.clear_autosave()
            self._kept = False

    def recover(self) -> None:
        """Open the unsaved changes kept from last time (they stay unsaved until Save)."""
        kept = library.autosaved()
        if not kept or not self._confirm_discard():
            return
        file, path, _, _ = kept
        try:
            theme = spec.load(file)
        except Exception as e:
            QMessageBox.critical(self, "Recover", f"The kept changes can't be read: {e}")
            return
        self.path = path if path and path.exists() else None
        self._fresh(theme, True)
        self.statusBar().showMessage("Unsaved changes recovered. Save to keep them.", 8000)

    def discard_recovery(self) -> None:
        library.clear_autosave()
        self.start.refresh(recovery=False)

    def _reset_history(self) -> None:
        self._commit_timer.stop()
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._committed = copy.deepcopy(self.theme)
        self._update_undo()

    def _update_undo(self) -> None:
        self.undo_act.setEnabled(bool(self._undo_stack) and self.stack.currentIndex() == 1)
        self.redo_act.setEnabled(bool(self._redo_stack) and self.stack.currentIndex() == 1)
        self.ai.undo.setEnabled(bool(self._undo_stack))

    def _step_to(self, theme: spec.Theme) -> None:
        tab = self.tabs.currentIndex()
        self.set_theme(copy.deepcopy(theme), True)
        self.tabs.setCurrentIndex(tab)
        self._update_undo()

    def undo(self) -> None:
        self._commit()
        if self._undo_stack:
            self._redo_stack.append(self._committed)
            self._committed = self._undo_stack.pop()
            self._step_to(self._committed)

    def redo(self) -> None:
        self._commit()
        if self._redo_stack:
            self._undo_stack.append(self._committed)
            self._committed = self._redo_stack.pop()
            self._step_to(self._committed)

    def _ai_theme(self, theme: spec.Theme) -> None:
        self._commit()
        self.set_theme(theme, True)
        self._commit()                  # one undo step back to before the AI's version

    def _go_to_setting(self, section: int, widget) -> None:
        from .finder import reveal
        self.tabs.setCurrentIndex(section)
        if widget is not self.tabs.widget(section):
            QTimer.singleShot(0, lambda: reveal(widget))
