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


def starters() -> list[Path]:
    """The theme specs shipped with the app, sorted by file name (dark ones first: 1-*, then light: 2-*)."""
    d = resources.files("kdecustomizer") / "starters"
    try:
        return sorted((Path(str(f)) for f in d.iterdir() if f.name.endswith(".toml")), key=lambda p: p.name)
    except (OSError, FileNotFoundError):
        return []
