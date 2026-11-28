"""Theme files, a mixin of `app.Main`: new / from desktop / from a picture / open / save (first save names the
theme and makes its folder), unsaved-changes prompts, starters, shared themes (.tar.gz) and drag and drop."""
from __future__ import annotations

import copy
import re
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from .. import library, spec, system


class FileActions:
    """New, open and save theme files, shared themes and drag and drop (a mixin of app.Main)."""

    def _ensure_saved(self) -> bool:
        """Signature icons are stored next to the spec, so it needs a file first."""
        if self.path and not self.dirty:
            return True
        return self.save()          # first save names the theme and puts it in the themes folder

    def _confirm_discard(self) -> bool:
        """Unsaved changes: Save / Discard / Cancel. True when it's fine to go on."""
        if not self.dirty:
            return True
        r = QMessageBox.question(self, "Unsaved changes", "Save changes to this theme first?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save()
        if r == QMessageBox.Discard:
            self._drop_autosave()
            return True
        return False

    def set_theme(self, theme: spec.Theme, dirty: bool) -> None:
        self.theme = theme
        self.to_form()
        self.dirty = dirty
        self._update_title()
        if dirty:
            self._autosave()
        else:
            self._drop_autosave()

    def _fresh(self, theme: spec.Theme, dirty: bool) -> None:
        """A different theme: the undo history starts over."""
        self.set_theme(theme, dirty)
        self._reset_history()
        self.show_editor()

    def new(self) -> None:
        if self._confirm_discard():
            self.path = None
            self._fresh(spec.Theme(name="New Theme", id="org.kdecustomizer.newtheme"), False)

    def from_desktop(self) -> None:
        """New unsaved theme = snapshot of the running desktop."""
        if not self._confirm_discard():
            return
        from .. import snapshot
        try:
            theme = snapshot.take("My Desktop")
        except Exception as e:  # unreadable config: tell the user rather than crash
            QMessageBox.critical(self, "Snapshot failed", str(e))
            return
        self.path = None
        self._fresh(theme, True)
        self.statusBar().showMessage(snapshot.summary(theme).replace("\n", " · "), 10000)

    def from_image(self, path: Path | None = None) -> None:
        """New unsaved theme: the picture's colors, with the picture as wallpaper."""
        from .. import imagepalette
        if not self._confirm_discard():
            return
        if not path:
            f, _ = QFileDialog.getOpenFileName(self, "Make a theme from a picture", str(Path.home() / "Pictures"),
                                               "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
            if not f:
                return
            path = Path(f)
        name = re.sub(r"[-_]+", " ", path.stem).strip().title()[:40] or "Picture"
        theme = spec.Theme(name=name, id="org.kdecustomizer.newtheme", wallpaper=str(path.resolve()))
        try:
            theme.palette = imagepalette.from_image(path, None, theme.palette)
        except Exception as e:      # unreadable image
            QMessageBox.warning(self, "Make a theme from a picture", str(e))
            return
        self.path = None
        self._fresh(theme, True)
        self.statusBar().showMessage(f"Colors taken from {path.name}. Try Colors › Variations… for nearby palettes; "
                                     "Save names it.", 10000)

    def load(self, path: Path) -> None:
        try:
            theme = spec.load(path)
        except Exception as e:  # show any parse error to the user
            QMessageBox.critical(self, "Load failed", str(e))
            return
        self.path = path
        self._fresh(theme, False)
        library.add_recent(path)

    def open(self) -> None:
        if not self._confirm_discard():
            return
        start = system.themes_dir()
        f, _ = QFileDialog.getOpenFileName(self, "Open theme", str(start if start.is_dir() else Path.home()),
                                           "Theme spec (*.toml)")
        if f:
            self.load(Path(f))

    def _ask_name(self) -> bool:
        """A theme still called "Untitled" / "New Theme"… gets a real name (and matching id) first."""
        t = self.from_form()
        if not spec.is_placeholder_name(t.name):
            return True
        old_id = t.id
        while True:
            name, ok = QInputDialog.getText(self, "Name your theme",
                                            "What should this theme be called?", text="")
            if not ok:
                return False
            if name.strip() and not spec.is_placeholder_name(name):
                break
        self.text["name"].setText(name.strip())
        if spec.is_placeholder_id(old_id) or old_id == spec.id_for(t.name):
            self.text["id"].setText(spec.id_for(name.strip()))
        self.from_form()
        return True

    def save(self) -> bool:
        """First save of a theme: name it if needed, then into the themes folder — no file dialog."""
        if not self.path:
            if not self._ask_name():
                return False
            while True:
                target = spec.default_path(self.from_form())
                if not target.exists():
                    break
                r = QMessageBox.question(
                    self, "Theme already exists",
                    f"{target.parent} already has a theme called “{self.theme.name}”.\n\n"
                    "Replace it, or give this one another name?",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.No)
                if r == QMessageBox.Yes:
                    break
                if r == QMessageBox.Cancel:
                    return False
                self.text["name"].setText("")            # ask again
                if not self._ask_name():
                    return False
            target.parent.mkdir(parents=True, exist_ok=True)
            self.path = target
        return self._write()

    def save_as(self) -> bool:
        """Save to a new file chosen by the user."""
        if not self._ask_name():
            return False
        start = str(self.path if self.path else spec.default_path(self.from_form()))
        Path(start).parent.mkdir(parents=True, exist_ok=True)
        f, _ = QFileDialog.getSaveFileName(self, "Save theme as", start, "Theme spec (*.toml)")
        if not f:
            return False
        self.path = Path(f)
        return self._write()

    def _write(self) -> bool:
        """Write the spec to self.path (paths inside its folder stored relative), add it to recent, clear the
        autosave."""
        out = copy.deepcopy(self.from_form())
        for attr in ("wallpaper",):  # keep files next to the spec portable
            val = getattr(out, attr)
            if val:
                try:
                    setattr(out, attr, str(Path(val).resolve().relative_to(self.path.resolve().parent)))
                except ValueError:
                    pass
        if out.iconset.signature_dir:
            try:
                out.iconset.signature_dir = str(Path(out.iconset.signature_dir).resolve()
                                                .relative_to(self.path.resolve().parent))
            except ValueError:
                pass
        spec.save(out, self.path)
        library.add_recent(self.path)
        self.dirty = False
        self._drop_autosave()
        self._update_title()
        self.statusBar().showMessage(f"Saved {self.path}", 4000)
        return True

    def _open_path(self, path: Path) -> None:
        if path == self.path and not self.dirty:
            self.show_editor()
        elif self._confirm_discard():
            self.load(path)

    def open_starter(self, path: Path) -> None:
        """A built-in starting point opens as a new, unsaved theme (first Save names it)."""
        if not self._confirm_discard():
            return
        try:
            theme = spec.load(path)
        except Exception as e:
            QMessageBox.critical(self, "Load failed", str(e))
            return
        self.path = None
        self._fresh(theme, False)

    def install_shared(self, archive: Path | None) -> None:
        """Unpack a theme someone exported into the themes folder and open its spec (Apply rebuilds it here)."""
        if archive is None:
            f, _ = QFileDialog.getOpenFileName(self, "Install a shared theme", str(Path.home()),
                                               "Shared theme (*.tar.gz *.tgz)")
            if not f:
                return
            archive = Path(f)
        if not self._confirm_discard():
            return
        try:
            toml = library.unpack_shared(archive, system.themes_dir())
            theme = spec.load(toml)
        except Exception as e:
            QMessageBox.critical(self, "Install a shared theme", str(e))
            return
        self.path = toml
        self._fresh(theme, False)
        library.add_recent(toml)
        self.statusBar().showMessage(f"“{theme.name}” unpacked to {toml.parent}. Look it over, then Apply to "
                                     "desktop.", 10000)

    @staticmethod
    def _dropped(e) -> Path | None:
        urls = e.mimeData().urls() if e.mimeData().hasUrls() else []
        if len(urls) != 1 or not urls[0].isLocalFile():
            return None
        p = Path(urls[0].toLocalFile())
        return p if p.suffix == ".toml" or p.name.endswith((".tar.gz", ".tgz")) else None

    def dragEnterEvent(self, e) -> None:
        if self._dropped(e):
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        p = self._dropped(e)
        if not p:
            return
        e.acceptProposedAction()
        if p.suffix == ".toml":
            self._open_path(p)
        else:
            self.install_shared(p)
