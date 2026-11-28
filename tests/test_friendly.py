"""Sidebar sections, unsaved-changes recovery, the Apply summary, compare view, setup check, shared themes and
palette variations."""
import colorsys
import tarfile

import pytest

from conftest import EXAMPLE, pyside6
from kdecustomizer import build, cli, color, doctor, library, spec, system, variations

gui = pytest.mark.skipif(not pyside6(), reason="needs PySide6")


# --- unsaved changes kept for recovery ---------------------------------------------------------------------

def test_autosave_round_trip(tmp_path):
    assert library.autosaved() is None
    library.autosave("x = 1\n", tmp_path / "a.toml", "Mine")
    file, path, name, when = library.autosaved()
    assert file.read_text() == "x = 1\n" and path == tmp_path / "a.toml" and name == "Mine" and when > 0
    library.autosave("y = 2\n", None, "New")
    assert library.autosaved()[1] is None
    library.clear_autosave()
    assert library.autosaved() is None


# --- shared themes --------------------------------------------------------------------------------------

def test_unpack_shared_export(midnight, tmp_path):
    archive = build.export(midnight, tmp_path / "m.tar.gz", tmp_path / "b")
    dest = tmp_path / "themes"
    toml = library.unpack_shared(archive, dest)
    assert toml == dest / midnight.slug / "theme.toml" and spec.load(toml).name == midnight.name
    again = library.unpack_shared(archive, dest)                # taken: a new folder next to it
    assert again.parent.name == f"{midnight.slug}-2"
    assert not list(dest.glob(".unpack-*"))


def _tar(path, members):
    with tarfile.open(path, "w:gz") as t:
        for name, data in members:
            info = tarfile.TarInfo(name)
            if data is None:
                info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
            else:
                info.size = len(data)
            t.addfile(info, None if data is None else __import__("io").BytesIO(data))
    return path


@pytest.mark.parametrize("members, why", [
    ([("T/readme", b"x")], "isn't a theme"),
    ([("T/theme.toml", b""), ("T/../../evil", b"x")], "refusing"),
    ([("T/theme.toml", b""), ("T/link", None)], "refusing"),
    ([("A/theme.toml", b""), ("B/x", b"")], "isn't a theme"),
])
def test_unpack_shared_refuses_bad_archives(tmp_path, members, why):
    with pytest.raises(ValueError, match=why):
        library.unpack_shared(_tar(tmp_path / "x.tar.gz", members), tmp_path / "themes")
    assert not (tmp_path / "themes").exists() or not any((tmp_path / "themes").iterdir())


# --- setup check ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, family", [
    ('ID=cachyos\nID_LIKE=arch\nPRETTY_NAME="CachyOS"', "arch"),
    ('ID=kubuntu\nID_LIKE="ubuntu debian"', "debian"),
    ("ID=fedora", "fedora"),
    ('ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"', "suse"),
    ("ID=gentoo", None),
])
def test_distro_family(tmp_path, text, family):
    (tmp_path / "os-release").write_text(text + "\n")
    assert doctor.distro(tmp_path / "os-release")[1] == family


def test_install_commands():
    assert doctor.install_command("kvantum", "debian") == "sudo apt install qt6-style-kvantum"
    assert doctor.install_command("kvantum", "suse") == "sudo zypper install kvantum-qt6"
    assert doctor.install_command("plymouth", "arch") == "sudo pacman -S --needed plymouth"
    assert "package manager" in doctor.install_command("plymouth", None)


def test_doctor_run_and_report(tmp_path, monkeypatch):
    (tmp_path / "os-release").write_text("ID=fedora\n")
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)          # nothing installed
    monkeypatch.setattr(system, "kvantum_installed", lambda: False)
    checks = doctor.run(["http://127.0.0.1:9"], os_release=tmp_path / "os-release")
    by = {c.key: c for c in checks}
    assert by["plasma"].required and not by["plasma"].ok
    assert by["kvantum"].fix == "sudo dnf install kvantum" and by["plymouth"].fix == "sudo dnf install plymouth"
    assert not by["imageai"].ok
    text = doctor.report(checks)
    assert "✗ Plasma 6 tools" in text and "sudo dnf install kvantum" in text
    assert "sudo dnf install kvantum" in doctor.commands(checks)
    assert all(not c.startswith("start ") for c in doctor.commands(checks))


def test_cli_doctor(capsys, monkeypatch):
    monkeypatch.setattr(doctor, "run", lambda urls=None: [doctor.Check("plasma", "Plasma 6 tools", "x", False,
                                                                         required=True)])
    assert cli.main(["doctor"]) == 1
    assert "Plasma 6 tools" in capsys.readouterr().out


def test_cli_apply_skip(midnight, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "run_install", lambda args: (calls.append(args), (0, ""))[1])
    spec.save(midnight, tmp_path / "m.toml")
    assert cli.main(["apply", str(tmp_path / "m.toml"), "-o", str(tmp_path / "b"), "--skip", "gtk",
                     "--skip", "boot", "--layout"]) == 0
    assert calls[0][1:] == ["--layout", "--no-gtk", "--no-boot"]
    with pytest.raises(SystemExit):
        cli.main(["apply", str(tmp_path / "m.toml"), "--skip", "nonsense"])


# --- palette variations -------------------------------------------------------------------------------------

@pytest.mark.parametrize("path", [EXAMPLE, *library.starters()])
def test_variations_are_readable_and_distinct(path):
    p = spec.load(path).palette
    vs = variations.variations(p)
    assert len(vs) >= 7 and len({label for label, _ in vs}) == len(vs)
    dark = color.is_dark(p.background)
    for label, v in vs:
        assert color.is_dark(v.background) == dark, label                 # stays a dark / light theme
        assert color.contrast(v.foreground, v.background) >= 4.5, label
        assert color.contrast(v.foreground, v.surface) >= 4.5, label
        assert color.contrast(v.accent, v.background) >= 3.5, label
        for k in ("positive", "neutral", "negative"):
            assert color.contrast(getattr(v, k), v.background) >= 3.0, (label, k)


def test_warmer_and_cooler_lean_the_right_way(midnight):
    vs = dict(variations.variations(midnight.palette))

    def hue(c):
        r, g, b = color.parse(c)
        return colorsys.rgb_to_hls(r / 255, g / 255, b / 255)[0]
    assert hue(vs["Warmer"].background) < 0.15                                # orange-brown, not pink
    assert 0.5 < hue(vs["Cooler"].background) < 0.7                           # blue


# --- GUI ------------------------------------------------------------------------------------------------------

@pytest.fixture
def win(qapp):
    from kdecustomizer.gui.app import Main
    w = Main(None)
    w.resize(1320, 820)
    w.show()
    qapp.processEvents()
    yield w
    w.dirty = False
    w.close()


@gui
def test_sidebar_shows_every_section(win):
    names = [win.tabs.tabText(i) for i in range(win.tabs.count())]
    assert names == ["Theme", "Colors", "Desktop", "Icons", "Panels", "Fonts", "Tweaks"]
    win.tabs.setCurrentIndex(5)
    assert win.tabs.currentIndex() == 5 and win.tabs.stack.currentIndex() == 5
    lst = win.tabs.list
    last = lst.visualItemRect(lst.item(lst.count() - 1))
    assert last.bottom() <= lst.viewport().height()                          # no scrolling to reach Tweaks
    assert win.ai.use_wp.width() >= win.ai.use_wp.sizeHint().width()          # "Match wallpaper" not clipped


@gui
def test_unsaved_changes_are_kept_and_recovered(win, qapp, tmp_path):
    win.load(EXAMPLE)
    win.colors["accent"].set("#00ff88")
    win.changed()
    win._commit()
    kept = library.autosaved()
    assert kept and kept[1] == EXAMPLE and "#00ff88" in kept[0].read_text()

    # the app goes away without saving (crash): the next window offers the changes on its start page
    win._kept = False
    from kdecustomizer.gui.app import Main
    w2 = Main(None)
    w2.show_start()
    assert w2.start.recovery.isVisibleTo(w2.start) and "Midnight" in w2.start.recovery_text.text()
    w2.load(EXAMPLE)                                     # opening something else keeps another session's copy
    assert library.autosaved() is not None
    w2.recover()
    assert w2.theme.palette.accent == "#00ff88" and w2.dirty and w2.path == EXAMPLE
    w2.path = tmp_path / "saved.toml"
    w2._write()                                          # saving drops the kept copy
    assert library.autosaved() is None
    w2.close()


@gui
def test_discard_recovery(win):
    library.autosave(spec.dumps(spec.load(EXAMPLE)), None, "Old")
    win.show_start()
    assert win.start.recovery.isVisibleTo(win.start)
    win.start.discard_recovery.emit()
    assert library.autosaved() is None and not win.start.recovery.isVisibleTo(win.start)


@gui
def test_apply_summary_skips_and_remembers(qapp, midnight):
    from kdecustomizer.gui.apply_summary import ApplySummary, parts
    midnight.wallpaper = "/x.png"
    keys = [k for k, _, _ in parts(midnight)]
    assert keys[:2] == ["layout", "wallpaper"] and {"gtk", "terminals", "browsers", "vscode", "tweaks",
                                                     "login"} <= set(keys)
    d = ApplySummary(None, midnight, layout=True)
    assert d.replace_panels and d.args() == ["--layout"] and d.needs_password()
    d.boxes["gtk"].setChecked(False)
    d.boxes["login"].setChecked(False)
    assert d.args() == ["--layout", "--no-gtk", "--no-login"] and not d.needs_password()
    d._accept()
    again = ApplySummary(None, midnight, layout=False)              # remembered for this theme
    assert again.skipped == ["gtk", "login"] and not again.replace_panels
    assert again.height() == again.layout().totalHeightForWidth(again.width())     # wrapped text never clipped


@gui
def test_compare_view(win, qapp):
    win.load(EXAMPLE)
    win.compare_btn.setChecked(True)
    qapp.processEvents()
    assert win.right_stack.currentWidget() is win.compare
    assert not win.compare.before.isNull() and not win.compare.after.isNull()
    assert win.compare.after_label == "Midnight"
    before = win.compare.after.toImage()
    win.colors["background"].set("#ffffff")
    win.changed()
    win._show_preview()
    assert win.compare.after.toImage() != before                    # follows the edits
    win.compare_btn.setChecked(False)
    assert win.right_stack.currentWidget() is win.preview


@gui
def test_variations_dialog_is_one_undo_step(win, qapp):
    from kdecustomizer.gui.variations_dialog import VariationsDialog
    win.load(EXAMPLE)
    old = win.theme.palette.background
    d = VariationsDialog(win, win.theme)
    assert d.grid.count() == len(d.options) and not d.grid.item(0).icon().isNull()
    warmer = next(i for i, (label, _) in enumerate(d.options) if label == "Warmer")
    d._pick(d.grid.item(warmer))
    win._set_palette(d.chosen, "x")
    assert win.theme.palette.background == d.chosen.background != old
    win.undo()
    assert win.theme.palette.background == old


@gui
def test_setup_dialog(qapp, monkeypatch):
    from kdecustomizer.gui.setup_dialog import SetupDialog
    import time

    def slow(urls=None):
        yield doctor.Check("plasma", "Plasma 6 tools", "all", True, "all there", required=True)
        time.sleep(0.3)                                 # like the image-AI check asking the network
        yield doctor.Check("kvantum", "Kvantum", "app style", False, "missing", "sudo pacman -S --needed kvantum")
    monkeypatch.setattr(doctor, "run_iter", slow)
    t0 = time.monotonic()
    d = SetupDialog()
    assert time.monotonic() - t0 < 0.2                  # the window doesn't wait for the checks
    assert "Checking" in d.heading.text() and not d.copy.isEnabled()
    deadline = time.monotonic() + 5
    while d.checking is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert "1 of 2 work here" in d.heading.text() and d.copy.isEnabled()
    assert "missing" in d.rows["kvantum"][1].text()
    d._copy()
    from PySide6.QtGui import QGuiApplication
    assert QGuiApplication.clipboard().text() == "sudo pacman -S --needed kvantum"


@gui
def test_install_shared_and_drop(win, midnight, tmp_path, monkeypatch):
    from PySide6.QtCore import QMimeData, QUrl
    archive = build.export(midnight, tmp_path / "m.tar.gz", tmp_path / "b")

    class Drop:
        def __init__(self, path):
            self.m = QMimeData()
            self.m.setUrls([QUrl.fromLocalFile(str(path))])

        def mimeData(self):
            return self.m
    assert win._dropped(Drop(archive)) == archive and win._dropped(Drop(EXAMPLE)) == EXAMPLE
    assert win._dropped(Drop(tmp_path / "x.png")) is None
    win.install_shared(archive)
    assert win.stack.currentIndex() == 1 and win.theme.name == midnight.name
    assert win.path.parent.parent == system.themes_dir() and not win.dirty
    assert library.recent()[0] == win.path.resolve()
