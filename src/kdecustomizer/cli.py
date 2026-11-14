"""kdec — command-line front end."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import replace
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


def cmd_export(a) -> int:
    dest = builder.export(spec.load(a.spec), a.dest, a.out)
    print(f"exported {dest}\nshare it; recipient runs: tar xzf {dest.name} && ./{dest.name.removesuffix('.tar.gz')}/install.sh")
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


def cmd_check(a) -> int:
    from . import ai
    problems = ai.check(spec.load(a.spec))
    for p in problems:
        print(f"warning: {p}")
    print("ok" if not problems else f"{len(problems)} issue(s)")
    return 1 if problems else 0


def cmd_ai_guide(a) -> int:
    from . import ai
    print(ai.reference())
    return 0


def cmd_ai(a) -> int:
    from . import ai
    current = spec.load(a.base) if a.base else None
    if a.prompt_only:
        print(ai.prompt_text(a.request, current, a.ref))
        return 0
    prov = replace(ai.PRESETS[a.provider])
    prov.model = a.model or prov.model
    prov.base_url = a.base_url or prov.base_url
    try:
        theme, note, problems = ai.generate(a.request, current, prov, use_wallpaper=not a.no_wallpaper, references=a.ref,
                                            log=lambda s: print(f"… {s}", file=sys.stderr))
    except ai.AIError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    out = Path(a.output or (a.base if a.base else f"{theme.slug.lower()}.toml"))
    if out.exists() and not (a.force or (a.base and out == Path(a.base))):
        print(f"{out} exists (use --force or -o)", file=sys.stderr)
        return 1
    spec.save(theme, out)
    if note:
        print(note)
    for p in problems:
        print(f"warning: {p}")
    print(f"wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kdec", description="Build and apply KDE Plasma themes")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("new", help="create a starter theme spec")
    s.add_argument("path")
    s.add_argument("--name")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_new)

    for name, fn, hlp in [("build", cmd_build, "generate theme files into build/"),
                          ("export", cmd_export, "build and pack a shareable .tar.gz (includes wallpaper)"),
                          ("apply", cmd_apply, "build, install and apply a theme"),
                          ("layout", cmd_layout, "apply only the panel/wallpaper layout live")]:
        s = sub.add_parser(name, help=hlp)
        s.add_argument("spec")
        s.add_argument("-o", "--out", default="build")
        if name == "export":
            s.add_argument("dest", nargs="?", help="output file (default: ./<Name>.tar.gz)")
        elif name != "build":
            s.add_argument("--dry-run", action="store_true", help="print the script instead of running it")
        if name == "apply":
            s.add_argument("--layout", action="store_true", help="also replace panels with the theme's layout")
        s.set_defaults(fn=fn)

    s = sub.add_parser("check", help="warn about unreadable colors and themes that aren't installed")
    s.add_argument("spec")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("ai-guide", help="print the theme-spec guide for an AI or coding agent")
    s.set_defaults(fn=cmd_ai_guide)

    from .ai import PRESETS
    s = sub.add_parser("ai", help="design or refine a theme with an AI")
    s.add_argument("request", help='e.g. "warm autumn theme, dock at the bottom"')
    s.add_argument("--from", dest="base", metavar="SPEC", help="refine this theme (its wallpaper is shown to the AI)")
    s.add_argument("-o", "--output", help="where to write (default: overwrite --from, else <name>.toml)")
    s.add_argument("--force", action="store_true")
    s.add_argument("--provider", choices=sorted(PRESETS), default="claude-code")
    s.add_argument("--model", help="model name (required for non-Claude providers)")
    s.add_argument("--base-url", help="override the provider's API URL")
    s.add_argument("--no-wallpaper", action="store_true", help="don't send the wallpaper image")
    s.add_argument("--ref", action="append", default=[], metavar="FILE",
                   help="image, PDF, .docx, text file or http(s) URL to build the theme from (repeatable)")
    s.add_argument("--prompt-only", action="store_true", help="print a prompt to paste into any chat AI instead")
    s.set_defaults(fn=cmd_ai)

    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except (ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
