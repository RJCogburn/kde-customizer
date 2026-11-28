"""Your own icons (a folder of <icon-name>.svg|png) + the Icon names window, and the second usability round:
failure explanations, unchanged login/boot parts, "changed since installed", restore-point history, finding a
setting, a theme from a picture, color-vision simulation, the update notice and the KDE Store export."""
import http.server
import json
import tarfile
import threading
from pathlib import Path

import pytest

from conftest import EXAMPLE, pyside6
from kdecustomizer import ai, build, cli, failures, iconnames, iconset, installed, library, spec, store, updates, vision

gui = pytest.mark.skipif(not pyside6(), reason="needs PySide6")
FOLDER_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48">'
              '<path d="M2 8h44v34H2z" fill="#5294e2"/></svg>')
MY_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
          '<circle cx="32" cy="32" r="30" fill="#f0f"/></svg>')


def png(w: int, h: int) -> bytes:
    """A valid PNG header is all png_as_svg reads; Qt/Pillow aren't needed for these files."""
    import struct
    import zlib
    raw = b"".join(b"\0" + b"\xff\x00\x00\xff" * w for _ in range(h))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


@pytest.fixture
def base(tmp_path):
    """An installed icon theme "FakeBase" with a folder, the trash and a Firefox icon."""
    d = tmp_path / "usr-share" / "icons" / "FakeBase"
    (d / "48" / "places").mkdir(parents=True)
    (d / "48" / "apps").mkdir(parents=True)
    (d / "index.theme").write_text("[Icon Theme]\nName=FakeBase\nDirectories=48/places,48/apps\n\n"
                                   "[48/places]\nSize=48\nContext=Places\nType=Fixed\n\n"
                                   "[48/apps]\nSize=48\nContext=Applications\nType=Fixed\n")
    for n in ("folder", "user-trash", "folder-music"):
        (d / "48" / "places" / f"{n}.svg").write_text(FOLDER_SVG)
    (d / "48" / "apps" / "firefox.svg").write_text(FOLDER_SVG)
    iconnames._index_cache.clear()
    return "FakeBase"


@pytest.fixture
def mine(tmp_path):
    d = tmp_path / "my icons"
    d.mkdir()
    (d / "folder.svg").write_text(MY_SVG)
    (d / "firefox.png").write_bytes(png(40, 20))
    (d / "foldr-musc.svg").write_text(MY_SVG)            # a typo: nothing asks for it
    return d


# --- your own icons ---------------------------------------------------------------------------------------

def test_own_icons_win_and_png_is_wrapped(midnight, base, mine, tmp_path):
    midnight.iconset.generate, midnight.iconset.base, midnight.iconset.custom_dir = True, base, str(mine)
    out = iconset.build(midnight, tmp_path / "out")
    index = (out / "index.theme").read_text()
    dirs = index.split("Directories=")[1].splitlines()[0].split(",")
    assert dirs[:2] == ["custom/scalable/places", "custom/scalable/applications"]      # listed first
    assert "[custom/scalable/places]\nSize=64\nMinSize=8\nMaxSize=512\nType=Scalable\nContext=Places" in index
    assert (out / "custom/scalable/places/folder.svg").read_text() == MY_SVG
    assert not (out / "48/places/folder.svg").exists()                  # no recolored copy competing with it
    assert (out / "48/places/user-trash.svg").exists()                  # the rest is still recolored
    wrapped = (out / "custom/scalable/applications/firefox.svg").read_text()
    assert 'width="40" height="40"' in wrapped and 'y="10"' in wrapped and "data:image/png;base64," in wrapped


def test_names_catalog_index_and_typos(base, mine):
    assert len(iconnames.CATALOG) == len(iconnames.PURPOSE) > 150                   # no name listed twice
    assert set(iconnames.CATEGORY.values()) == set(iconnames.CONTEXTS)
    assert iconnames.context("folder-music") == "Places" and iconnames.context("org.whatever") == "Applications"
    idx = iconnames.theme_index(base)
    assert idx["folder"].context == "Places" and idx["firefox"].path.name == "firefox.svg"
    own = iconnames.custom_icons(mine)
    assert set(own) == {"folder", "firefox", "foldr-musc"}
    assert iconnames.unknown_names(own, base) == ["foldr-musc"]


def test_add_and_remove_own_icon(tmp_path):
    folder = tmp_path / "f"
    (tmp_path / "a.png").write_bytes(png(8, 8))
    (tmp_path / "b.svg").write_text(MY_SVG)
    (tmp_path / "bad.png").write_text("not a png")
    iconnames.add_custom(folder, "user-trash", tmp_path / "a.png")
    iconnames.add_custom(folder, "user-trash", tmp_path / "b.svg")            # replaces the PNG
    assert [p.name for p in folder.iterdir()] == ["user-trash.svg"]
    with pytest.raises(ValueError):
        iconnames.add_custom(folder, "x", tmp_path / "bad.png")
    with pytest.raises(ValueError):
        iconnames.add_custom(folder, "x", tmp_path / "a.jpg")
    iconnames.remove_custom(folder, "user-trash")
    assert not any(folder.iterdir())


def test_own_icons_folder_is_saved_relative_and_bundled(midnight, base, mine, tmp_path):
    folder = mine.parent
    midnight.iconset.generate, midnight.iconset.base, midnight.iconset.custom_dir = True, base, str(mine)
    spec.save(midnight, folder / "t.toml")
    assert 'custom_dir = "my icons"' in (folder / "t.toml").read_text()
    assert spec.load(folder / "t.toml").iconset.custom_dir == str(mine)
    out = build.build(midnight, tmp_path / "b")
    assert (out / "custom-icons/folder.svg").is_file()
    shared = spec.load(out / "theme.toml")
    assert shared.iconset.custom_dir == str(out / "custom-icons") and shared.iconset.signature_dir == ""
    assert str(tmp_path) not in (out / "theme.toml").read_text()


def test_check_warns_about_own_icons(midnight, base, mine, tmp_path):
    midnight.iconset.custom_dir = str(tmp_path / "nope")
    assert any("doesn't exist" in p for p in ai.check(midnight, {}))
    midnight.iconset.custom_dir = str(mine)
    assert any("only used with iconset.generate" in p for p in ai.check(midnight, {}))
    midnight.iconset.generate, midnight.iconset.base = True, base
    assert any("foldr-musc.svg" in p for p in ai.check(midnight, {}))


def test_cli_icon_names_and_custom(midnight, base, mine, tmp_path, capsys):
    assert cli.main(["icon-names", "trash"]) == 0
    assert "user-trash-full" in capsys.readouterr().out
    assert cli.main(["icon-names", "--all", "--base", base, "fire"]) == 0
    assert capsys.readouterr().out.startswith("firefox")
    assert cli.main(["icon-names", "zzzz-nothing"]) == 1
    spec.save(midnight, tmp_path / "t.toml")
    assert cli.main(["icons", str(tmp_path / "t.toml"), "--custom", str(mine)]) == 0
    t = spec.load(tmp_path / "t.toml")
    assert t.iconset.generate and t.iconset.custom_dir == str(mine)
    assert cli.main(["icons", str(tmp_path / "t.toml"), "--custom", ""]) == 0
    assert spec.load(tmp_path / "t.toml").iconset.custom_dir == ""


# --- failures explained ----------------------------------------------------------------------------------

def test_failures_explained():
    out = "==> settings\ninstall.sh: line 40: kwriteconfig6: command not found\ncp: No space left on device\n"
    reasons = failures.explain(out, 127)
    assert reasons[0].startswith("“kwriteconfig6” isn't installed: it comes with KDE Frameworks 6")
    assert any("disk is full" in r for r in reasons)
    assert failures.explain(out, 0) == []
    assert failures.explain("Error executing command as another user: Not authorized", 1)[0].startswith(
        "The admin password prompt was cancelled")
    assert failures.last_error("a\ncp: cannot stat 'x': No such file or directory\nb") .startswith("cp: cannot")


# --- login/boot: unchanged since last time ----------------------------------------------------------------

def test_system_parts_hash_and_unchanged(midnight, tmp_path):
    assert midnight.login_screen.generate
    out = build.build(midnight, tmp_path / "b")
    sums = build.system_stamps(midnight, out)
    assert f"SUM={sums['login']}" in (out / "install.sh").read_text()
    assert build.unchanged_system_parts(midnight, out) == set()
    (build.state_dir()).mkdir(parents=True, exist_ok=True)
    (build.state_dir() / f"login-{midnight.slug}").write_text(sums["login"] + "\n")
    assert build.unchanged_system_parts(midnight, out) == {"login"}
    again = build.build(midnight, tmp_path / "b2")
    assert build.system_stamps(midnight, again) == sums                 # same theme, same hash (any build folder)
    midnight.palette.accent = "#ff8800"
    assert build.system_stamps(midnight, build.build(midnight, tmp_path / "b3"))["login"] != sums["login"]


# --- changed since installed ------------------------------------------------------------------------------

def test_spec_hash_and_outdated(midnight, tmp_path):
    path = tmp_path / "m.toml"
    spec.save(midnight, path)
    h = build.spec_hash(spec.load(path))
    assert h == build.spec_hash(spec.load(path))
    out = build.build(spec.load(path), tmp_path / "b")
    assert f"echo {h} >" in (out / "install.sh").read_text()
    # installed as it is now
    lnf = Path(build.state_dir()).parent.parent / "share/plasma/look-and-feel" / midnight.id
    import shutil
    shutil.copytree(out / "lookandfeel" / midnight.id, lnf)
    build.state_dir().mkdir(parents=True, exist_ok=True)
    (build.state_dir() / f"installed-{midnight.slug}").write_text(h + "\n")
    library.add_recent(path)
    assert installed.outdated() == {}
    t = spec.load(path)
    t.palette.accent = "#ff8800"
    spec.save(t, path)
    assert installed.outdated() == {midnight.id: path}
    assert build.state_dir() / f"installed-{midnight.slug}" in installed.themes()[0].parts()


# --- updates, vision, store ---------------------------------------------------------------------------------

def test_update_check(tmp_path, monkeypatch):
    assert updates.newer("0.1.30", "0.1.24") and not updates.newer("0.1.24", "0.1.24")
    assert updates.newer("0.2.0", "0.1.99") and not updates.newer("0.1.9", "0.1.10")
    monkeypatch.delenv("APPIMAGE", raising=False)
    (tmp_path / "rt" / "python").mkdir(parents=True)
    assert not updates.self_managed(tmp_path / "rt" / "python")
    (tmp_path / "rt" / "update-check").touch()
    assert updates.self_managed(tmp_path / "rt" / "python")
    monkeypatch.setenv("APPIMAGE", "/x.AppImage")
    assert updates.self_managed(tmp_path / "nothing")

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"tag_name": "v9.9.9", "html_url": "https://example.invalid/r"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/latest"
    assert updates.check("0.1.24", url) == ("9.9.9", "https://example.invalid/r")
    assert updates.check("9.9.9", url) is None
    srv.shutdown()
    assert updates.check("0.1.0", "http://127.0.0.1:9/") is None               # offline: no notice, no error


def test_vision_simulation():
    red = (220, 40, 40)
    for mode in ("protanopia", "deuteranopia"):
        a = vision.simulate_rgb(red, mode)
        assert abs(a[0] - a[1]) < abs(red[0] - red[1])                   # red loses its redness
    gray = vision.simulate_rgb((200, 30, 90), "achromatopsia")
    assert gray[0] == gray[1] == gray[2]
    if vision.available():
        row = bytes([220, 40, 40, 40, 180, 40]) + b"\0\0"               # 2 pixels + padding to the stride
        out = vision.simulate_image(row, (2, 1), 8, "achromatopsia")
        assert len(out) == 6 and out[0] == out[1] == out[2]


def test_store_export(midnight, tmp_path):
    midnight.wallpaper = str(tmp_path / "wall.png")
    Path(midnight.wallpaper).write_bytes(png(16, 9))
    files = store.export(midnight, tmp_path / "store", tmp_path / "b")
    names = {p.name for p, _c, _w in files.values()}
    assert {f"{midnight.slug}-global-theme.tar.gz", f"{midnight.slug}.colors", f"{midnight.slug}-plasma-style.tar.gz",
            f"{midnight.slug}-decoration.tar.gz", f"{midnight.slug}-complete.tar.gz",
            f"{midnight.slug}-wallpaper.png"} <= names
    with tarfile.open(tmp_path / "store" / f"{midnight.slug}-global-theme.tar.gz") as tar:
        assert f"{midnight.id}/metadata.json" in tar.getnames()            # one top folder, like the store wants
    text = (tmp_path / "store" / "UPLOAD.md").read_text()
    assert "Global Themes (Plasma 6)" in text and f"{midnight.slug}-complete.tar.gz" in text
    assert str(tmp_path) not in text


# --- GUI -------------------------------------------------------------------------------------------------

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
def test_icon_names_dialog(qapp, base, tmp_path, monkeypatch):
    from kdecustomizer.gui import icon_names
    folder = tmp_path / "mine"
    d = icon_names.IconNamesDialog(None, base, lambda create: (folder.mkdir(exist_ok=True), folder)[1]
                                   if create or folder.exists() else None)
    assert d.proxy.rowCount() == len(iconnames.CATALOG)
    d.select("user-trash")
    assert d._selected() == "user-trash" and d.use_btn.isEnabled() and not d.remove_btn.isEnabled()
    (tmp_path / "t.svg").write_text(MY_SVG)
    monkeypatch.setattr(icon_names.QFileDialog, "getOpenFileName", lambda *a, **k: (str(tmp_path / "t.svg"), ""))
    changed = []
    d.icons_changed.connect(lambda: changed.append(1))
    d.use_image()
    assert (folder / "user-trash.svg").is_file() and changed and d.remove_btn.isEnabled()
    row = next(r for r in range(d.proxy.rowCount()) if d.proxy.index(r, 2).data() == "user-trash")
    assert d.proxy.index(row, 1).data(icon_names.Qt.DecorationRole) is not None       # "Yours" column
    assert d.proxy.index(row, 0).data(icon_names.Qt.DecorationRole) is not None       # what the theme shows now
    d.search.clear()
    d.cats.setCurrentRow(d.cats.count() - 1)                                           # Your icons
    assert d.proxy.rowCount() == 1
    d.cats.setCurrentRow(d.cats.count() - 2)                                           # everything in the base
    assert d.proxy.rowCount() == len(iconnames.theme_index(base))
    d.cats.setCurrentRow(d.cats.count() - 1)
    d.table.selectRow(0)
    d.remove_mine()
    assert not (folder / "user-trash.svg").exists() and d.proxy.rowCount() == 0


@gui
def test_icons_tab_own_icons(win, qapp, base, mine, tmp_path):
    t = spec.load(EXAMPLE)
    t.iconset.base = base
    spec.save(t, tmp_path / "t.toml")
    win.load(tmp_path / "t.toml")
    tab = win.icons_tab
    assert not tab.custom_info.isVisible() and not tab.generate.isChecked()
    tab._set_custom(str(mine))
    qapp.processEvents()
    assert win.theme.iconset.custom_dir == str(mine) and win.theme.iconset.generate
    assert "3 icons" in tab.custom_info.text() and "foldr-musc.svg" in tab.custom_info.text()
    tab._set_custom("")
    p = tab.custom_folder(True)                     # made next to the spec when the theme has none
    assert p == tmp_path / f"{t.slug.lower()}-my-icons" and p.is_dir()
    assert win.theme.iconset.custom_dir == str(p)


@gui
def test_find_a_setting(win, qapp):
    from kdecustomizer.gui import finder
    win.load(EXAMPLE)
    texts = {(t, win.tabs.tabText(i)) for t, i, _w, _tip in finder.entries(win.tabs)}
    assert ("Your own icons", "Icons") in texts and ("Base theme", "Icons") in texts
    win.finder.reindex()
    win.finder.setText("base theme")
    win.finder._search("base theme")
    win.finder._first()
    qapp.processEvents()
    assert win.tabs.tabText(win.tabs.currentIndex()) == "Icons"
    assert qapp.focusWidget() is win.icons_tab.base


@gui
def test_history_dialog_and_revert_picked(win, qapp, monkeypatch):
    from kdecustomizer import restorepoints
    from kdecustomizer.gui.history_dialog import HistoryDialog
    assert not HistoryDialog(None).list.isEnabled()
    for stamp in ("20261120-101010-Midnight", "20261121-111111-Nord"):
        d = restorepoints.root() / stamp
        d.mkdir(parents=True)
        (d / "restore.sh").write_text("true\n")
    h = HistoryDialog(None)
    assert h.list.count() == 2 and "Nord" in h.list.item(0).text() and "the last Apply" in h.list.item(0).text()
    h.list.setCurrentRow(1)
    h._accept()
    assert h.chosen.theme == "Midnight"
    ran = []
    monkeypatch.setattr(win.proc, "start", lambda prog, args: ran.append(args))
    win.revert(h.chosen)                            # picked in the history: no second question
    assert ran == [[str(h.chosen.script)]]


@gui
def test_apply_summary_unchanged_login(qapp, midnight, tmp_path):
    from kdecustomizer.gui.apply_summary import ApplySummary
    out = build.build(midnight, tmp_path / "b")
    d = ApplySummary(None, midnight, False, out)
    d.boxes["login"].setChecked(True)               # (another test may have left it unticked for this theme)
    assert d.needs_password() and "login screen" in d.password.text()
    build.state_dir().mkdir(parents=True, exist_ok=True)
    (build.state_dir() / f"login-{midnight.slug}").write_text(build.system_stamps(midnight, out)["login"])
    d = ApplySummary(None, midnight, False, out)
    d.boxes["login"].setChecked(True)
    assert d.unchanged == {"login"} and not d.needs_password() and "No admin password" in d.password.text()


@gui
def test_variations_render_after_opening(qapp, midnight):
    from kdecustomizer.gui.variations_dialog import VariationsDialog
    d = VariationsDialog(None, midnight)
    first = d.grid.item(0).icon().pixmap(32, 32).toImage()
    assert d._next == 0                                   # nothing drawn yet: the window opens at once
    while d._timer.isActive():
        qapp.processEvents()
    assert d._next == len(d.options) and d.grid.item(0).icon().pixmap(32, 32).toImage() != first


@gui
def test_preview_vision(qapp, midnight):
    from kdecustomizer.gui.preview import Preview
    if not vision.available():
        pytest.skip("needs Pillow")
    p = Preview()
    p.resize(640, 400)
    p.show_theme(midnight)
    normal = p.grab().toImage()
    p.set_vision("achromatopsia")
    gray = p.grab().toImage()
    c = gray.pixelColor(320, 200)
    assert gray != normal and c.red() == c.green() == c.blue()


@gui
def test_theme_from_a_picture(win, qapp, tmp_path):
    from PySide6.QtGui import QColor, QImage
    img = QImage(64, 40, QImage.Format_RGB32)
    img.fill(QColor("#2a6f4e"))
    img.save(str(tmp_path / "forest_lake.png"))
    win.from_image(tmp_path / "forest_lake.png")
    assert win.theme.name == "Forest Lake" and win.theme.wallpaper == str(tmp_path / "forest_lake.png")
    assert win.dirty and win.path is None and win.stack.currentIndex() == 1


@gui
def test_manager_update_and_start_hint(win, qapp, midnight, tmp_path, monkeypatch):
    from kdecustomizer.gui.manager import ThemeManager
    path = tmp_path / "m.toml"
    spec.save(midnight, path)
    monkeypatch.setattr(installed, "outdated", lambda specs=None: {midnight.id: path})
    monkeypatch.setattr(installed, "themes", lambda: [installed.Installed(midnight.id, "Midnight", midnight.slug,
                                                                          tmp_path)])
    win.show_start()
    assert win.start.manage_btn.text() == "Installed themes… (1 changed)"
    m = ThemeManager(win)
    assert "changed since installed" in m.list.item(0).text() and not m.update_btn.isHidden()
    applied = []
    monkeypatch.setattr(win, "apply", lambda: applied.append(win.path))
    m.update_requested.connect(win._update_installed)
    m._update()
    qapp.processEvents()
    assert win.path == path and applied == [path]


@gui
def test_update_banner(win):
    win.start.show_update("9.9.9", "https://example.invalid/r")
    assert not win.start.update_bar.isHidden() and "9.9.9 is out" in win.start.update_text.text()
    win.start._no_updates()
    from PySide6.QtCore import QSettings
    assert win.start.update_bar.isHidden() and QSettings("kdecustomizer", "kdec-gui").value("updates/check") in (
        False, "false")
    QSettings("kdecustomizer", "kdec-gui").remove("updates/check")


# --- speed: caches and background work -------------------------------------------------------------------------

def test_icon_indexes_are_cached_per_data_dirs(base, tmp_path, monkeypatch):
    from kdecustomizer import appicons
    f = appicons.IconFinder.get(base)
    assert appicons.IconFinder.get(base) is f and f.find("firefox").name == "firefox.svg"
    other = tmp_path / "other-share"
    other.mkdir()
    monkeypatch.setenv("XDG_DATA_DIRS", str(other))                  # other folders: never the old index
    assert appicons.IconFinder.get(base) is not f
    assert appicons.installed_apps() is appicons.installed_apps()


@gui
def test_wallpaper_is_decoded_once_and_shared(qapp, midnight, tmp_path):
    from PySide6.QtGui import QColor, QImage
    from kdecustomizer.gui import preview
    img = QImage(3000, 1000, QImage.Format_RGB32)
    img.fill(QColor("#336699"))
    img.save(str(tmp_path / "wide.png"))
    midnight.wallpaper = str(tmp_path / "wide.png")
    a, b = preview.Preview(), preview.Preview()
    a.show_theme(midnight)
    b.show_theme(midnight)
    assert a._wp.cacheKey() == b._wp.cacheKey()                      # one decoded copy
    assert (a._wp.width(), a._wp.height()) == (preview.W, preview.H)    # cut to the canvas, not 3000 px wide


@gui
def test_preview_icons_build_in_background(win, qapp, base, tmp_path):
    import time
    t = spec.load(EXAMPLE)
    t.iconset.generate, t.iconset.base = True, base
    spec.save(t, tmp_path / "t.toml")
    win.load(tmp_path / "t.toml")
    win._build_preview_icons()
    win._build_preview_icons()                                       # while one runs: queued, not a second thread
    assert win._icons_again
    deadline = time.monotonic() + 10
    while (win._icons_thread is not None or win._icons_key is None) and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    from PySide6.QtGui import QIcon
    root = QIcon.themeSearchPaths()[0]
    assert root.endswith(("set0", "set1")) and (Path(root) / t.icons_name / "index.theme").is_file()
    assert win._icons_key[1] == base
