"""kdec — command-line front end."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from . import build as builder
from . import spec


def cmd_new(a) -> int:
    path = Path(a.path)
    if path.exists() and not a.force:
        print(f"{path} exists (use --force)", file=sys.stderr)
        return 1
    name = a.name or path.stem.replace("-", " ").title()
    t = spec.Theme(name=name, id=f"org.kdecustomizer.{re.sub(r'[^a-z0-9]+', '', name.lower())}")
    spec.save(t, path)
    print(f"wrote {path}")
    return 0


def cmd_build(a) -> int:
    out = builder.build(spec.load(a.spec), a.out)
    print(f"built {out}")
    return 0


def cmd_apply(a) -> int:
    out = builder.build(spec.load(a.spec), a.out)
    script = out / "install.sh"
    if a.dry_run:
        print(script.read_text())
        return 0
    return subprocess.call([str(script)] + (["--layout"] if a.layout else []))


def cmd_layout(a) -> int:
    """Run only the panel/wallpaper layout script against the live shell."""
    out = builder.build(spec.load(a.spec), a.out)
    js = (out / "layout.js").read_text()
    if a.dry_run:
        print(js)
        return 0
    return subprocess.call(["qdbus6", "org.kde.plasmashell", "/PlasmaShell",
                            "org.kde.PlasmaShell.evaluateScript", js])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kdec", description="Build and apply KDE Plasma themes")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("new", help="create a starter theme spec")
    s.add_argument("path")
    s.add_argument("--name")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_new)

    for name, fn, hlp in [("build", cmd_build, "generate theme files into build/"),
                          ("apply", cmd_apply, "build, install and apply a theme"),
                          ("layout", cmd_layout, "apply only the panel/wallpaper layout live")]:
        s = sub.add_parser(name, help=hlp)
        s.add_argument("spec")
        s.add_argument("-o", "--out", default="build")
        if name != "build":
            s.add_argument("--dry-run", action="store_true", help="print the script instead of running it")
        if name == "apply":
            s.add_argument("--layout", action="store_true", help="also replace panels with the theme's layout")
        s.set_defaults(fn=fn)

    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except (ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
