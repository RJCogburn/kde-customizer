"""Desktop section: wallpaper (pick or make with the image AI), Plasma style, app style, title bars,
cursors, splash, login screen, boot splash, GTK / terminal / browser colors, light-dark switching. The
`*_generate_toggled` handlers enable the fields that only matter when a part is generated."""
from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QWidget,
)

from ... import cursorset, spec, system
from ..fields import combo, scroll
from . import FormHelpers


class DesktopPage(FormHelpers):
    """The Desktop section (a mixin of app.Main)."""

    def _desktop_tab(self) -> QWidget:
        """Everything about how the desktop looks besides colors: one group per part, built below."""
        page, v = self._form_page()

        self._desktop_wallpaper(v)
        self._desktop_plasma_style(v)
        self._desktop_app_style(v)
        self._desktop_look(v)
        self._desktop_other_apps(v)
        self._desktop_cursors(v)
        self._desktop_splash(v)
        self._desktop_boot_splash(v)
        self._desktop_login_screen(v)
        self._desktop_decoration(v)
        v.addStretch()
        return scroll(page)

    def _desktop_wallpaper(self, v) -> None:
        """Desktop › Wallpaper."""
        f = self._group("Wallpaper", v)
        row = QHBoxLayout()
        self.text["wallpaper"] = QLineEdit(placeholderText="none — preview uses a palette gradient")
        self.text["wallpaper"].textChanged.connect(self.changed)
        browse = QPushButton(QIcon.fromTheme("document-open"), "")
        browse.setToolTip("Choose image…")
        browse.clicked.connect(self.pick_wallpaper)
        self.wp_make = QPushButton(QIcon.fromTheme("games-config-background"), "Make…")
        self.wp_make.setToolTip("Render a wallpaper in this palette with your local image AI (the one set up "
                                "in the Icons tab: Fooocus, ComfyUI or A1111/Forge)")
        self.wp_make.clicked.connect(self.make_wallpaper)
        row.addWidget(self.text["wallpaper"])
        row.addWidget(browse)
        row.addWidget(self.wp_make)
        f.addRow("Image", row)

    def _desktop_plasma_style(self, v) -> None:
        """Desktop › Plasma style."""
        f = self._group("Plasma style", v)
        self.plasma: dict[str, QCheckBox] = {}
        for key, label in [("generate", "Generate from palette"),
                           ("blur", "Blur behind panels and popups"),
                           ("adaptive_transparency", "Opaque panels when a window is maximized")]:
            self.plasma[key] = QCheckBox(label)
            self.plasma[key].toggled.connect(self.changed)
            f.addRow(self.plasma[key])
        self.p_radius = QSpinBox(minimum=0, maximum=32, suffix=" px",
                                 toolTip="Corner radius of floating panels, popups and tooltips")
        self.p_opacity = QSpinBox(minimum=30, maximum=100, suffix=" %",
                                  toolTip="Fill opacity of panels and popups (Breeze: 85 %)")
        for w in (self.p_radius, self.p_opacity):
            w.valueChanged.connect(self.changed)
        f.addRow("Corner radius", self.p_radius)
        f.addRow("Opacity", self.p_opacity)
        self.plasma["outline"] = QCheckBox("Outline panels and popups")
        self.plasma["outline"].toggled.connect(self.changed)
        f.addRow(self.plasma["outline"])
        self.text["plasma_style"] = combo(self.installed["plasma_style"])
        f.addRow("Installed style", self.text["plasma_style"])
        self.plasma["generate"].toggled.connect(self._plasma_generate_toggled)

    def _desktop_app_style(self, v) -> None:
        """Desktop › App style."""
        f = self._group("App style", v)
        self.w_generate = QCheckBox("Generate a Kvantum style from palette")
        self.w_generate.setToolTip("Buttons, fields, menus and tabs drawn in the theme's colors. Needs the "
                                   "kvantum package; without it apps keep the App style chosen below.")
        self.w_generate.toggled.connect(self.changed)
        self.w_generate.toggled.connect(lambda on: self.w_radius.setEnabled(on))
        f.addRow(self.w_generate)
        self.w_radius = QSpinBox(minimum=0, maximum=12, suffix=" px",
                                 toolTip="Corner radius of buttons, fields, menus, tabs and check boxes")
        self.w_radius.valueChanged.connect(self.changed)
        f.addRow("Corner radius", self.w_radius)
        if not system.kvantum_installed():
            note = QLabel("Kvantum isn't installed here, so the preview and this machine keep the "
                          "fallback style. The theme still includes it for others.")
            note.setWordWrap(True)
            note.setStyleSheet("color: palette(placeholder-text)")
            f.addRow(note)

    def _desktop_look(self, v) -> None:
        """Desktop › Look."""
        f = self._group("Look", v)
        for attr, label in [("icons", "Icons"), ("cursors", "Cursors"), ("widget_style", "App style")]:
            c = combo(self.installed[attr])
            c.currentTextChanged.connect(self.changed)
            self.text[attr] = c
            f.addRow(label, c)
        self._line(f, "Splash", "splash")
        self.konsole = QCheckBox("Matching Konsole color scheme")
        self.konsole.toggled.connect(self.changed)
        f.addRow(self.konsole)
        self.g_generate = QCheckBox("Matching GNOME / GTK 4 apps")
        self.g_generate.setToolTip("libadwaita apps ignore KDE color schemes; this gives them the palette "
                                   "through ~/.config/gtk-4.0")
        self.g_generate.toggled.connect(self.changed)
        self.g_generate.toggled.connect(lambda on: self.g_flatpak.setEnabled(on))
        f.addRow(self.g_generate)
        self.g_flatpak = QCheckBox("Flatpak GNOME apps too")
        self.g_flatpak.setToolTip("Gives Flatpak apps read-only access to ~/.config/gtk-4.0 "
                                  "(flatpak override --user)")
        self.g_flatpak.toggled.connect(self.changed)
        f.addRow(self.g_flatpak)
        self.light_dark = QCheckBox("Light and dark versions, switched by time of day")
        self.light_dark.setToolTip("Also builds the opposite version (same hues) and lets Plasma switch between "
                                   "the two at sunrise and sunset (Night Light's schedule). GTK apps, terminals "
                                   "and Konsole follow; apps use the fallback style instead of Kvantum.")
        self.light_dark.toggled.connect(self.changed)
        f.addRow(self.light_dark)

    def _desktop_other_apps(self, v) -> None:
        """Desktop › Other terminals and editors."""
        f = self._group("Other terminals and editors", v)
        note = QLabel("Matching colors for these apps, when they are installed.")
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(placeholder-text)")
        f.addRow(note)
        self.apps: dict[str, QCheckBox] = {}
        for key, label, tip in [
            ("kitty", "kitty", "Theme file + an include at the end of kitty.conf"),
            ("alacritty", "Alacritty", "Imports a theme; alacritty.toml's own [colors.*] tables are commented out "
                                       "(backup kept, restored when this is off)"),
            ("wezterm", "WezTerm", "Installs a color scheme; select it in wezterm.lua"),
            ("ghostty", "Ghostty", "Theme file + `theme =` at the end of Ghostty's config"),
            ("vscode", "VS Code / VSCodium", "Installs a theme extension; pick it in Preferences > Color Theme"),
            ("firefox", "Firefox / LibreWolf", "Toolbar, tabs, address bar and menus via each profile's "
                                               "userChrome.css; restart the browser to see it"),
            ("thunderbird", "Thunderbird", "Via each profile's userChrome.css; restart Thunderbird to see it"),
        ]:
            c = QCheckBox(label)
            c.setToolTip(tip)
            c.toggled.connect(self.changed)
            self.apps[key] = c
            f.addRow(c)

    def _desktop_cursors(self, v) -> None:
        """Desktop › Cursors."""
        f = self._group("Cursors", v)
        self.c_generate = QCheckBox("Generate cursors from palette")
        self.c_generate.setToolTip("Recolor an SVG cursor theme to the palette (replaces Cursors above)")
        self.c_generate.toggled.connect(self.changed)
        self.c_generate.toggled.connect(self._cursor_generate_toggled)
        f.addRow(self.c_generate)
        self.c_base = combo(cursorset.scalable_themes() or ["breeze_cursors"])
        self.c_base.setToolTip("Installed cursor theme with SVG cursors to recolor")
        self.c_base.currentTextChanged.connect(self.changed)
        f.addRow("Base", self.c_base)
        self.c_fill = QComboBox()
        self.c_fill.addItems(list(spec.CursorSet.FILLS))
        self.c_fill.setToolTip("Pointer body color; the outline takes the contrasting palette color")
        self.c_fill.currentTextChanged.connect(self.changed)
        f.addRow("Body", self.c_fill)

    def _desktop_splash(self, v) -> None:
        """Desktop › Splash screen."""
        f = self._group("Splash screen", v)
        self.s_generate = QCheckBox("Generate a splash screen from palette")
        self.s_generate.setToolTip("Theme name and a progress bar in the palette's colors "
                                   "(replaces the Splash above)")
        self.s_generate.toggled.connect(self.changed)
        self.s_generate.toggled.connect(self._splash_generate_toggled)
        f.addRow(self.s_generate)
        self.s_background = QComboBox()
        self.s_background.addItems(list(spec.SplashScreen.BACKGROUNDS))
        self.s_background.setToolTip("wallpaper uses the theme's wallpaper, dimmed; without one it falls "
                                     "back to the gradient")
        self.s_background.currentTextChanged.connect(self.changed)
        f.addRow("Background", self.s_background)
        self.s_text = QLineEdit(placeholderText="the theme name")
        self.s_text.textChanged.connect(self.changed)
        f.addRow("Text", self.s_text)

    def _desktop_boot_splash(self, v) -> None:
        """Desktop › Boot splash."""
        f = self._group("Boot splash", v)
        self.b_generate = QCheckBox("Generate a boot splash (Plymouth)")
        self.b_generate.setToolTip("Theme name and a progress bar while booting and at disk-unlock prompts. "
                                   "Installing asks for the admin password and rebuilds the initramfs.")
        self.b_generate.toggled.connect(self.changed)
        self.b_generate.toggled.connect(lambda on: (self.b_background.setEnabled(on), self.b_text.setEnabled(on)))
        f.addRow(self.b_generate)
        self.b_background = QComboBox()
        self.b_background.addItems(list(spec.BootSplash.BACKGROUNDS))
        self.b_background.currentTextChanged.connect(self.changed)
        f.addRow("Background", self.b_background)
        self.b_text = QLineEdit(placeholderText="the theme name")
        self.b_text.textChanged.connect(self.changed)
        f.addRow("Text", self.b_text)

    def _desktop_login_screen(self, v) -> None:
        """Desktop › Login screen."""
        f = self._group("Login screen", v)
        self.l_generate = QCheckBox("Theme the login screen")
        self.l_generate.setToolTip("Colors, Plasma style, icons, cursors and wallpaper on the login screen "
                                   "(Plasma Login Manager or SDDM). Installing asks for the admin password "
                                   "(only when it changed).")
        self.l_generate.toggled.connect(self.changed)
        self.l_generate.toggled.connect(self._login_generate_toggled)
        f.addRow(self.l_generate)
        self.l_background = QComboBox()
        self.l_background.addItems(list(spec.LoginScreen.BACKGROUNDS))
        self.l_background.setToolTip("wallpaper = the theme's wallpaper (palette color without one); "
                                     "color = the palette background")
        self.l_background.currentTextChanged.connect(self.changed)
        f.addRow("Background", self.l_background)
        self.l_clock = QCheckBox("Show the clock")
        self.l_clock.toggled.connect(self.changed)
        f.addRow(self.l_clock)

    def _desktop_decoration(self, v) -> None:
        """Desktop › Window decoration."""
        f = self._group("Window decoration", v)
        self.deco: dict[str, QLineEdit] = {}
        for attr, label, tip in [
            ("library", "Library", ""), ("theme", "Theme", ""),
            ("buttons_left", "Left buttons", "M menu · S all desktops · H help · F above · B below · _ spacer"),
            ("buttons_right", "Right buttons", "I minimize · A maximize · X close"),
        ]:
            w = QLineEdit()
            w.setToolTip(tip)
            w.textChanged.connect(self.changed)
            self.deco[attr] = w
            f.addRow(label, w)
        self.d_generate = QCheckBox("Generate title bars from palette")
        self.d_generate.setToolTip("Build an Aurorae window decoration in the theme's colors "
                                   "(replaces Library/Theme above)")
        self.d_generate.toggled.connect(self.changed)
        self.d_generate.toggled.connect(self._deco_generate_toggled)
        f.addRow(self.d_generate)
        self.d_radius = QSpinBox(minimum=0, maximum=16, suffix=" px", toolTip="Top corner radius")
        self.d_height = QSpinBox(minimum=20, maximum=60, suffix=" px", toolTip="Title bar height")
        self.d_border = QSpinBox(minimum=0, maximum=12, suffix=" px", toolTip="Side and bottom border (0 = none)")
        self.d_align = QComboBox()
        self.d_align.addItems(list(spec.Decoration.TITLE_ALIGNS))
        self.d_style = QComboBox()
        self.d_style.addItems(list(spec.Decoration.BUTTON_STYLES))
        self.d_style.setToolTip("glyph: symbols with a round hover · dots: colored circles "
                                "(close = negative, minimize = neutral, maximize = positive)")
        for w in (self.d_radius, self.d_height, self.d_border):
            w.valueChanged.connect(self.changed)
        for w in (self.d_align, self.d_style):
            w.currentTextChanged.connect(self.changed)
        f.addRow("Corner radius", self.d_radius)
        f.addRow("Title height", self.d_height)
        f.addRow("Border", self.d_border)
        f.addRow("Title align", self.d_align)
        f.addRow("Buttons", self.d_style)

    def _login_generate_toggled(self, on: bool) -> None:
        self.l_background.setEnabled(on)
        self.l_clock.setEnabled(on)

    def _cursor_generate_toggled(self, on: bool) -> None:
        self.text["cursors"].setEnabled(not on)
        self.c_base.setEnabled(on)
        self.c_fill.setEnabled(on)

    def _splash_generate_toggled(self, on: bool) -> None:
        self.text["splash"].setEnabled(not on)
        self.s_background.setEnabled(on)
        self.s_text.setEnabled(on)

    def _deco_generate_toggled(self, on: bool) -> None:
        for w in (self.deco["library"], self.deco["theme"]):
            w.setEnabled(not on)
        for w in (self.d_radius, self.d_height, self.d_border, self.d_align, self.d_style):
            w.setEnabled(on)

    def _plasma_generate_toggled(self, on: bool) -> None:
        """Shape options only exist for the generated style; the installed one is used otherwise."""
        self.text["plasma_style"].setEnabled(not on)
        for w in (self.p_radius, self.p_opacity, self.plasma["outline"]):
            w.setEnabled(on)

    def pick_wallpaper(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Choose wallpaper", str(Path.home()),
                                           "Images (*.png *.jpg *.jpeg *.webp *.svg)")
        if f:
            self.text["wallpaper"].setText(f)

    def make_wallpaper(self) -> None:
        """Ask what to show, then render a wallpaper in the palette with the image AI on a worker thread."""
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QInputDialog
        from ... import wallpaper
        from ..icons_tab import _Worker
        if getattr(self, "_wp_thread", None):
            return
        idea, ok = QInputDialog.getText(self, "Make wallpaper", "What should it show? (it gets this theme's "
                                        "colors)", text=self.theme.description)
        if not ok or not self._ensure_saved():
            return
        theme = copy.deepcopy(self.from_form())
        it = self.icons_tab
        url, perf, model, folder = it.url.text().strip(), it.perf.currentText().strip(), it._model(), self.path.parent

        def job(log):
            return [str(wallpaper.generate(theme, folder, url, idea=idea, performance=perf, model=model, log=log))]
        self.wp_make.setEnabled(False)
        self._wp_thread = QThread(self)
        self._wp_worker = _Worker(job)
        self._wp_worker.moveToThread(self._wp_thread)
        self._wp_thread.started.connect(self._wp_worker.run)
        # bound methods so Qt runs these on the GUI thread
        self._wp_worker.progress.connect(self._wp_progress)
        self._wp_worker.done.connect(self._wp_done)
        self._wp_worker.failed.connect(self._wp_failed)
        self._wp_thread.start()

    def _wp_progress(self, text: str) -> None:
        self.statusBar().showMessage(text[:1].upper() + text[1:])

    def _wp_stop(self) -> None:
        self.wp_make.setEnabled(True)
        self._wp_thread.quit()
        self._wp_thread.wait()
        self._wp_thread = None

    def _wp_done(self, paths: list) -> None:
        self._wp_stop()
        self.text["wallpaper"].setText(paths[0])
        self.statusBar().showMessage("Wallpaper made. Save, then Apply to use it.", 8000)

    def _wp_failed(self, msg: str) -> None:
        self._wp_stop()
        QMessageBox.warning(self, "Make wallpaper", msg)
