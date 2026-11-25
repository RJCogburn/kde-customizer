"""Restore points that every install.sh takes (generators/restore.py) — listing and undoing them."""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


def root() -> Path:
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")
    return Path(state) / "kde-customizer" / "restore"


@dataclass
class Point:
    path: Path
    when: datetime | None
    theme: str              # the theme that was installed right after this point

    @property
    def script(self) -> Path:
        return self.path / "restore.sh"

    def label(self) -> str:
        when = self.when.strftime("%Y-%m-%d %H:%M") if self.when else self.path.name
        return f"{when}  before {self.theme}"


def _parse(path: Path) -> Point:
    stamp, _, rest = path.name.partition("-")
    time, _, theme = rest.partition("-")
    try:
        when = datetime.strptime(f"{stamp}-{time}", "%Y%m%d-%H%M%S")
    except ValueError:
        when, theme = None, path.name
    return Point(path, when, theme or "?")


def points() -> list[Point]:
    """Newest first; only complete ones (with restore.sh)."""
    if not root().is_dir():
        return []
    found = [_parse(p) for p in root().iterdir() if (p / "restore.sh").is_file()]
    return sorted(found, key=lambda p: p.path.name, reverse=True)


def revert(point: Point | None = None) -> tuple[int, Point | None]:
    """Run a restore point (default: the newest) and drop it, so the next revert goes one step further back."""
    point = point or next(iter(points()), None)
    if point is None:
        return 1, None
    rc = subprocess.call(["bash", str(point.script)])
    if rc == 0:
        shutil.rmtree(point.path, ignore_errors=True)
    return rc, point
