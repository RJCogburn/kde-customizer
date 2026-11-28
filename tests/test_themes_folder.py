"""Default themes folder and naming: system.themes_dir, spec helpers, `kdec new <name>`, the editor's first save."""

import pytest

from conftest import pyside6
from kdecustomizer import cli, spec, system


def test_documents_from_user_dirs(isolated_home):
    (isolated_home / ".config/user-dirs.dirs").write_text('XDG_DOCUMENTS_DIR="$HOME/Dokumente"\n')
    assert system.documents_dir() == isolated_home / "Dokumente"
    assert system.themes_dir() == isolated_home / "Dokumente/KDE Themes"


def test_documents_fallback(isolated_home):
    assert system.documents_dir() == isolated_home / "Documents"


def test_names_and_paths(isolated_home):
    assert spec.is_placeholder_name("Untitled") and spec.is_placeholder_name(" new theme ")
    assert not spec.is_placeholder_name("SC1")
    assert spec.id_for("Neon Night!") == "org.kdecustomizer.neonnight"
    assert spec.is_placeholder_id("org.kdecustomizer.untitled") and spec.is_placeholder_id(spec.id_for("My Desktop"))
    p = spec.default_path(spec.Theme(name="Neon/Night: v2"))
    assert p.parent.name == "Neon-Night- v2" and p.name == "neonnightv2.toml"
    assert p.parent.parent == system.themes_dir()


def test_cli_new_by_name(isolated_home, capsys):
    assert cli.main(["new", "Neon Night"]) == 0
    path = system.themes_dir() / "Neon Night" / "neonnight.toml"
    t = spec.load(path)
    assert (t.name, t.id) == ("Neon Night", "org.kdecustomizer.neonnight")
    assert cli.main(["new", "Neon Night"]) == 1                    # exists


def test_cli_new_by_path_still_works(tmp_path):
    assert cli.main(["new", str(tmp_path / "x-y.toml")]) == 0
    assert spec.load(tmp_path / "x-y.toml").name == "X Y"


@pytest.mark.skipif(not pyside6(), reason="needs PySide6")
def test_first_save_asks_for_a_name_and_uses_the_themes_folder(isolated_home, monkeypatch, qapp):
    from PySide6.QtWidgets import QInputDialog
    app = qapp
    from kdecustomizer.gui.app import Main
    asked = []
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: (asked.append(1), ("Ember", True))[1]))
    w = Main(None)
    w.new()
    assert w.save()
    assert asked and w.path == system.themes_dir() / "Ember" / "ember.toml"
    t = spec.load(w.path)
    assert (t.name, t.id) == ("Ember", "org.kdecustomizer.ember")
    asked.clear()
    assert w.save() and not asked                                   # named + has a path: no questions
    out = w.do_build()
    assert out == system.themes_dir() / "Ember" / "build" / "Ember"  # builds live in the theme's folder
    w.dirty = False
    w.close()
    app.processEvents()
