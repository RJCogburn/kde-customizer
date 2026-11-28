"""New-version notice for the AppImage and the .tar.gz (which don't update themselves; distribution packages do).
At most once a day the GUI asks GitHub for the latest release; nothing is sent but the request itself."""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

from . import __version__

REPO = "RJCogburn/kde-customizer"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
PAGE = f"https://github.com/{REPO}/releases/latest"


def self_managed(prefix: str | Path | None = None) -> bool:
    """True for the AppImage and the tarball (its runtime has an `update-check` marker next to python/)."""
    if os.environ.get("APPIMAGE"):
        return True
    return (Path(prefix or sys.prefix).parent / "update-check").is_file()


def parse(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", version)[:4])


def newer(candidate: str, current: str = __version__) -> bool:
    return parse(candidate) > parse(current)


def latest(timeout: float = 6.0, url: str = API) -> tuple[str, str]:
    """(version, release page) of the newest release."""
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "kde-customizer-update-check"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    return str(data.get("tag_name", "")).lstrip("v"), str(data.get("html_url") or PAGE)


def check(current: str = __version__, url: str = API) -> tuple[str, str] | None:
    """The newer release, or None (also when offline)."""
    try:
        version, page = latest(url=url)
    except Exception:       # offline, rate-limited, unexpected reply: no notice
        return None
    return (version, page) if version and newer(version, current) else None
