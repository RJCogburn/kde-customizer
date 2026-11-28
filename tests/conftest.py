"""Shared fixtures. Every test runs with HOME and the XDG dirs pointed at a temp dir, so nothing reads or
writes the real desktop's config."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from kdecustomizer import spec

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "midnight.toml"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    for sub in (".config", ".local/share", ".local/state", ".cache"):
        (home / sub).mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local/share"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local/state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))
    monkeypatch.setenv("XDG_CONFIG_DIRS", str(tmp_path / "etc-xdg"))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "usr-share"))
    (tmp_path / "usr-share").mkdir()
    _guard_path(tmp_path, monkeypatch)
    return home


# Tools that reach outside the temp HOME: root (pkexec, sudo), the running session (Plasma, KWin, D-Bus, the user's
# systemd) or the user's apps. Every test gets do-nothing stand-ins first on PATH, so a script that runs by mistake
# can't change the real system. pkexec/sudo refuse, like a cancelled password prompt. A test that wants to see the
# calls puts its own stubs in front.
GUARDED = ["pkexec", "sudo", "plasma-apply-lookandfeel", "plasma-apply-colorscheme", "plasma-apply-desktoptheme",
           "plasma-apply-cursortheme", "plasma-apply-wallpaperimage", "plasma-changeicons", "qdbus6", "qdbus",
           "dbus-send", "kquitapp6", "plasmashell", "systemctl", "code", "codium", "code-oss", "flatpak",
           "plymouth-set-default-theme", "xdg-open"]


def _guard_path(tmp_path: Path, monkeypatch) -> None:
    bin_ = tmp_path / "guard-bin"
    bin_.mkdir()
    for c in GUARDED:
        refuse = c in ("pkexec", "sudo")
        (bin_ / c).write_text(f"#!/bin/sh\necho 'test guard: {c} not run' >&2\nexit {126 if refuse else 0}\n")
        (bin_ / c).chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}:{os.environ['PATH']}")


@pytest.fixture
def midnight() -> spec.Theme:
    return spec.load(EXAMPLE)


SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32">'
       '<filter id="f"><feGaussianBlur stdDeviation=".6"/></filter>'
       '<path d="M4 5v16l4-4z" filter="url(#f)" opacity=".2"/>'
       '<path d="M4 4v16l4-4z" fill="#fff"/>'
       '<path d="M5 6v12l3-3z"/>'
       '<circle cx="20" cy="20" r="3" fill="#46a7ac"/></svg>')


@pytest.fixture
def cursor_base(tmp_path) -> Path:
    """A minimal SVG cursor theme named breeze_cursors in XDG_DATA_DIRS: one static cursor, one animated,
    one alias symlink."""
    d = tmp_path / "usr-share" / "icons" / "breeze_cursors"
    (d / "cursors").mkdir(parents=True)
    (d / "index.theme").write_text("[Icon Theme]\nName=Breeze\n")
    sc = d / "cursors_scalable"
    (sc / "default").mkdir(parents=True)
    (sc / "default" / "default.svg").write_text(SVG)
    (sc / "default" / "metadata.json").write_text(json.dumps(
        [{"filename": "default.svg", "hotspot_x": 4, "hotspot_y": 4, "nominal_size": 24}]))
    (sc / "wait").mkdir()
    frames = []
    for i in (1, 2):
        (sc / "wait" / f"wait-{i:02}.svg").write_text(SVG)
        frames.append({"filename": f"wait-{i:02}.svg", "delay": 30, "hotspot_x": 16, "hotspot_y": 15,
                       "nominal_size": 24})
    (sc / "wait" / "metadata.json").write_text(json.dumps(frames))
    os.symlink("default", sc / "arrow")
    os.symlink("default", d / "cursors" / "arrow")
    return d


@pytest.fixture(scope="session")
def qapp():
    """One QApplication (widgets) for the whole run: a QGuiApplication created first would break widget tests."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def qtsvg() -> bool:
    try:
        import PySide6.QtSvg  # noqa: F401
        return True
    except ImportError:
        return False


def pyside6() -> bool:
    try:
        import PySide6  # noqa: F401
        return True
    except ImportError:
        return False
