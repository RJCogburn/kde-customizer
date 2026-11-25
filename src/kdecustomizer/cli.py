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
    if a.path.endswith(".toml") or "/" in a.path:
        path = Path(a.path)
        name = a.name or path.stem.replace("-", " ").title()
    else:                                   # a theme name: its own folder in the themes folder
        name = a.name or a.path
        path = spec.default_path(spec.Theme(name=name))
    if path.exists() and not a.force:
        print(f"{path} exists (use --force)", file=sys.stderr)
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    t = spec.Theme(name=name, id=spec.id_for(name))
    spec.save(t, path)
    print(f"wrote {path}")
    return 0


def cmd_snapshot(a) -> int:
    from . import snapshot
    path = Path(a.path)
    if path.exists() and not a.force:
        print(f"{path} exists (use --force)", file=sys.stderr)
        return 1
    name = a.name or path.stem.replace("-", " ").replace("_", " ").title()
    t = snapshot.take(name)
    spec.save(t, path)
    print(f"wrote {path}")
    print(snapshot.summary(t))
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


def cmd_icons(a) -> int:
    """Make signature icons for a theme (and switch on its generated icon set)."""
    from . import ai, signature
    theme = spec.load(a.spec)
    if a.list_models:
        try:
            b = signature.imagegen.detect(a.image_url, a.performance, "auto")
        except signature.imagegen.ImageGenError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        names = b.models()
        print(f"{b.name}: {len(names)} checkpoints (default: {b.default_model() or '?'}; auto: "
              f"{signature.imagegen.pick_model(names) or 'default'})")
        for n in names:
            print(n)
        return 0
    if a.prompts:
        print(signature.prompts_text(theme))
        return 0
    sig = Path(theme.iconset.signature_dir) if theme.iconset.signature_dir else signature.default_dir(theme, a.spec)
    only = [x.strip() for x in a.only.split(",")] if a.only else None
    if only and (bad := [x for x in only if x not in signature.SLOTS]):
        print(f"error: unknown icon(s): {', '.join(bad)}. Known: {', '.join(signature.SLOTS)}", file=sys.stderr)
        return 1
    if a.style:
        theme.iconset.style = a.style
    log = lambda s: print(f"… {s}", file=sys.stderr)  # noqa: E731
    try:
        if a.recut:
            print(f"… background removal: {signature.imagegen.cutout_method()}", file=sys.stderr)
            done = signature.recut(sig, only, log=log)
            mode = "image"
        elif a.import_dir:
            done = signature.import_images(theme, sig, a.import_dir)
            mode = "image"
        elif a.mode == "image":
            done = signature.generate_images(theme, sig, a.image_url, performance=a.performance, only=only,
                                             model=a.image_model, log=log)
            mode = "image"
        else:
            prov = replace(ai.PRESETS[a.provider])
            prov.model = a.model or prov.model
            prov.base_url = a.base_url or prov.base_url
            done = signature.generate_svg(theme, sig, prov, references=a.ref, only=only, log=log)
            mode = "svg"
    except (ai.AIError, signature.imagegen.ImageGenError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if not done:
        print("no icons were made (for --import, name files after the icons, e.g. folder.png; --recut needs "
              "raw renders, kept since v0.1.17)", file=sys.stderr)
        return 1
    # Record it in the spec: generated icon set on, pointing at the signature folder (relative path).
    saved = spec.load(a.spec)
    saved.iconset.generate = True
    saved.iconset.signature = mode
    saved.iconset.style = theme.iconset.style
    try:
        saved.iconset.signature_dir = str(sig.resolve().relative_to(Path(a.spec).resolve().parent))
    except ValueError:
        saved.iconset.signature_dir = str(sig.resolve())
    if saved.wallpaper:
        try:
            saved.wallpaper = str(Path(saved.wallpaper).relative_to(Path(a.spec).resolve().parent))
        except ValueError:
            pass
    spec.save(saved, a.spec)
    print(f"made {len(done)} icon(s) in {sig}: {', '.join(done)}")
    print(f"updated {a.spec} — `kdec apply {a.spec}` installs them")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kdec", description="Build and apply KDE Plasma themes")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("new", help="create a starter theme spec (a name -> its own folder in the themes folder)")
    s.add_argument("path", help='a name ("Neon Night") or a .toml path')
    s.add_argument("--name")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_new)

    s = sub.add_parser("snapshot", help="save the current desktop (colors, styles, fonts, panels, wallpaper) as a spec")
    s.add_argument("path")
    s.add_argument("--name", help="theme name (default: from the file name)")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_snapshot)

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

    s = sub.add_parser("icons", help="make signature icons (AI-drawn SVG, local image AI, or imported images)")
    s.add_argument("spec")
    s.add_argument("--mode", choices=["svg", "image"], default="svg",
                   help="svg: an AI draws vector icons (default); image: your local image AI renders them")
    s.add_argument("--style", help='icon look, e.g. "brushed gold metal, dark glass" (saved in the spec)')
    s.add_argument("--only", metavar="NAMES", help="comma-separated icons to (re)make, e.g. folder,user-home")
    s.add_argument("--ref", action="append", default=[], metavar="FILE", help="reference to match (svg mode)")
    s.add_argument("--provider", choices=sorted(PRESETS), default="claude-code", help="AI for svg mode")
    s.add_argument("--model")
    s.add_argument("--base-url")
    s.add_argument("--image-url", default="http://127.0.0.1:7865",
                   help="local image AI (Fooocus, ComfyUI or A1111/Forge); default Fooocus' port")
    s.add_argument("--performance", default="", help="Fooocus performance preset, e.g. Speed, Quality, Lightning")
    s.add_argument("--image-model", default="", metavar="NAME",
                   help='checkpoint for image mode: a name your image AI lists, "auto" (best fit for icons) or '
                        "empty (its default); --list-models shows them")
    s.add_argument("--list-models", action="store_true", help="list the image AI's checkpoints and exit")
    s.add_argument("--prompts", action="store_true", help="print prompts to make the icons in any image app")
    s.add_argument("--import", dest="import_dir", metavar="DIR", help="import <icon-name>.png/.svg files from DIR")
    s.add_argument("--recut", action="store_true",
                   help="cut the backgrounds out of the kept raw renders again (no image AI needed)")
    s.set_defaults(fn=cmd_icons)

    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except (ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
