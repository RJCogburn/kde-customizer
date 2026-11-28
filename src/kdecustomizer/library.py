"""Recently opened theme specs and the built-in starting points (`starters/*.toml`), for the GUI's start page."""
from __future__ import annotations

import json
import os
from importlib import resources
from pathlib import Path

MAX_RECENT = 12


def _recent_file() -> Path:
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")
    return Path(state) / "kde-customizer" / "recent.json"


def recent() -> list[Path]:
    """Newest first; files that no longer exist are left out."""
    try:
        items = json.loads(_recent_file().read_text())
    except (OSError, ValueError):
        return []
    return [Path(p) for p in items if isinstance(p, str) and Path(p).is_file()]


def _store(paths: list[Path]) -> None:
    f = _recent_file()
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps([str(p) for p in paths[:MAX_RECENT]], indent=1))
    except OSError:
        pass                                    # a read-only home shouldn't break opening a theme


def add_recent(path: str | Path) -> None:
    p = Path(path).resolve()
    _store([p] + [q for q in recent() if q.resolve() != p])


def remove_recent(path: str | Path) -> None:
    p = Path(path).resolve()
    _store([q for q in recent() if q.resolve() != p])


# --- unsaved changes, kept while you edit (recovered after a crash or a forced close) --------------------------

def _autosave_dir() -> Path:
    return _recent_file().parent / "autosave"


def autosave(text: str, path: str | Path | None, name: str) -> None:
    """Keep the theme being edited (TOML text) with the file it belongs to (None = not saved yet)."""
    d = _autosave_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        (d / "theme.toml").write_text(text)
        (d / "info.json").write_text(json.dumps({"path": str(path) if path else None, "name": name}))
    except OSError:
        pass


def autosaved() -> tuple[Path, Path | None, str, float] | None:
    """(kept TOML file, the theme file it belongs to or None, theme name, when) — or None if nothing is kept."""
    d = _autosave_dir()
    try:
        info = json.loads((d / "info.json").read_text())
        when = (d / "theme.toml").stat().st_mtime
    except (OSError, ValueError):
        return None
    path = info.get("path")
    return d / "theme.toml", Path(path) if path else None, str(info.get("name") or "Unsaved theme"), when


def clear_autosave() -> None:
    for f in ("theme.toml", "info.json"):
        try:
            (_autosave_dir() / f).unlink()
        except OSError:
            pass


# --- themes other people shared (`kdec export` archives) -------------------------------------------------------

def unpack_shared(archive: str | Path, dest_root: Path) -> Path:
    """Unpack a `kdec export` archive into dest_root/<its folder> (…-2, -3 if taken) and return its theme.toml.

    Only the spec and what it points at are trusted later: the GUI rebuilds from theme.toml, it never runs the
    archive's own install.sh. Members that would land outside the folder, links and devices are refused."""
    import tarfile
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        tops = {Path(m.name).parts[0] for m in members if m.name not in ("", ".")}
        if len(tops) != 1 or not any(Path(m.name).parts[1:] == ("theme.toml",) for m in members):
            raise ValueError(f"{Path(archive).name} isn't a theme shared with KDE Customizer "
                             "(no <folder>/theme.toml inside)")
        top = tops.pop()
        for m in members:
            p = Path(m.name)
            if p.is_absolute() or ".." in p.parts or not (m.isfile() or m.isdir()):
                raise ValueError(f"{Path(archive).name}: refusing “{m.name}”")
        dest = dest_root / top
        n = 1
        while dest.exists():
            n += 1
            dest = dest_root / f"{top}-{n}"
        dest_root.mkdir(parents=True, exist_ok=True)
        tmp = dest_root / f".unpack-{os.getpid()}"
        kw = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        tar.extractall(tmp, **kw)
    (tmp / top).rename(dest)
    tmp.rmdir()
    return dest / "theme.toml"


def starters() -> list[Path]:
    """The theme specs shipped with the app, sorted by file name (dark ones first: 1-*, then light: 2-*)."""
    d = resources.files("kdecustomizer") / "starters"
    try:
        return sorted((Path(str(f)) for f in d.iterdir() if f.name.endswith(".toml")), key=lambda p: p.name)
    except (OSError, FileNotFoundError):
        return []
