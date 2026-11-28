"""Setup check (`kdec doctor`, GUI "Setup check"): which optional parts can work on this machine, and for each one
that can't, the command that installs it on this distribution. Nothing here changes the system."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import system

# distribution family -> install command
INSTALL = {"arch": "sudo pacman -S --needed {}", "debian": "sudo apt install {}", "fedora": "sudo dnf install {}",
           "suse": "sudo zypper install {}"}
_FAMILIES = {
    "arch": {"arch", "cachyos", "manjaro", "endeavouros", "garuda", "artix"},
    "debian": {"debian", "ubuntu", "kubuntu", "neon", "linuxmint", "pop", "elementary", "zorin"},
    "fedora": {"fedora", "rhel", "centos", "nobara", "ultramarine", "almalinux", "rocky"},
    "suse": {"opensuse", "opensuse-tumbleweed", "opensuse-leap", "suse", "sles"},
}
# package names per family (one string = the same everywhere)
PACKAGES = {
    "kvantum": {"arch": "kvantum", "debian": "qt6-style-kvantum", "fedora": "kvantum", "suse": "kvantum-qt6"},
    "plymouth": "plymouth",
    "sddm": "sddm",
    "pkexec": {"arch": "polkit", "debian": "pkexec", "fedora": "polkit", "suse": "polkit"},
    "flatpak": "flatpak",
    "papirus": "papirus-icon-theme",
}
PLASMA_TOOLS = ["kwriteconfig6", "kreadconfig6", "kpackagetool6", "plasma-apply-lookandfeel",
                "plasma-apply-colorscheme", "qdbus6"]
IMAGE_AI_URLS = ["http://127.0.0.1:7865", "http://127.0.0.1:8188", "http://127.0.0.1:7860"]  # Fooocus, ComfyUI, A1111


@dataclass
class Check:
    key: str
    label: str
    purpose: str            # what it's for
    ok: bool
    detail: str = ""        # what was found, or what happens without it
    fix: str = ""           # how to get it (a command where we know one)
    required: bool = False


def distro(os_release: str | Path = "/etc/os-release") -> tuple[str, str | None]:
    """(pretty name, family) — family is a key of INSTALL, or None for one we don't know."""
    info: dict[str, str] = {}
    try:
        for line in Path(os_release).read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep:
                info[k.strip()] = v.strip().strip('"')
    except OSError:
        return "unknown", None
    ids = [info.get("ID", "").lower(), *info.get("ID_LIKE", "").lower().split()]
    family = next((fam for i in ids for fam, names in _FAMILIES.items() if i in names or i.startswith(fam)), None)
    return info.get("PRETTY_NAME") or info.get("NAME") or "unknown", family


def install_command(package: str, family: str | None) -> str:
    spec = PACKAGES[package]
    name = spec if isinstance(spec, str) else spec.get(family or "", "")
    if not family or not name:
        return f"install “{spec if isinstance(spec, str) else package}” with your package manager"
    return INSTALL[family].format(name)


def _image_ai(urls: list[str]) -> tuple[bool, str]:
    from . import imagegen
    for url in urls:
        try:
            b = imagegen.detect(url)
        except Exception:
            continue
        return True, f"{type(b).__name__} at {url}"
    return False, ""


def _rembg() -> tuple[bool, str]:
    try:
        import rembg  # noqa: F401
        return True, "rembg is importable here"
    except ImportError:
        pass
    from . import imagegen
    py = os.environ.get("KDEC_REMBG_PYTHON", "")
    try:
        py = py or imagegen._rembg_cache().read_text().strip()
    except OSError:
        pass
    if py and os.path.isfile(py):
        return True, f"via {py}"
    return False, ""


def run(image_urls: list[str] | None = None, os_release: str | Path = "/etc/os-release") -> list[Check]:
    _, fam = distro(os_release)
    missing = [t for t in PLASMA_TOOLS if not shutil.which(t)]
    checks = [Check("plasma", "Plasma 6 tools", "installing and applying any theme", not missing,
                    "all there" if not missing else "missing: " + ", ".join(missing),
                    "" if not missing else "these come with the Plasma 6 desktop (plasma-workspace, KConfig, "
                                           "KPackage, Qt tools)", required=True)]

    def add(key, label, purpose, ok, found, without, package=None, fix=""):
        checks.append(Check(key, label, purpose, ok, found if ok else without,
                            "" if ok else (fix or (install_command(package, fam) if package else ""))))

    add("kvantum", "Kvantum", "app style ([widgets] generate)", system.kvantum_installed(), "installed",
        "apps keep the fallback style (Breeze)", "kvantum")
    add("greeter", "Login screen manager", "login screen ([login_screen] generate)",
        system.login_manager_installed(), "Plasma Login Manager or SDDM is set up",
        "the login screen can't be themed", "sddm")
    add("pkexec", "pkexec (polkit)", "login screen and boot splash (they ask for the admin password)",
        bool(shutil.which("pkexec")), "installed", "the login screen and boot splash can't be installed", "pkexec")
    add("plymouth", "Plymouth", "boot splash ([boot_splash] generate)",
        bool(shutil.which("plymouth-set-default-theme")), "installed", "the boot splash can't be installed",
        "plymouth")
    add("flatpak", "Flatpak", "GTK colors in Flatpak apps ([gtk] flatpak)", bool(shutil.which("flatpak")),
        "installed", "only needed if you use Flatpak apps", "flatpak")
    has_papirus = any(n.lower().startswith("papirus") for n in system.icon_themes())
    add("papirus", "Papirus icons", "a good base for generated icon sets", has_papirus, "installed",
        "generated icon sets use another base (Breeze works too)", "papirus")
    add("claude", "Claude Code", "Design with AI, with your Claude login (the default AI provider)",
        bool(shutil.which("claude")), "installed",
        "pick another AI provider in the AI settings, or copy the prompt into any chat AI",
        fix="npm install -g @anthropic-ai/claude-code")
    ok, found = _image_ai(image_urls or IMAGE_AI_URLS)
    add("imageai", "Local image AI", "AI wallpapers and image icons (Fooocus, ComfyUI or A1111/Forge)", ok, found,
        "nothing answering at " + ", ".join(image_urls or IMAGE_AI_URLS) + " (only needed for those features)",
        fix="start Fooocus, ComfyUI or A1111/Forge (with --api), e.g. from Stability Matrix")
    ok, found = _rembg()
    add("rembg", "rembg", "clean cut-outs for image icons", ok, found,
        "a simpler built-in cut-out is used; your image AI's own rembg is found while it runs",
        fix="pip install rembg onnxruntime (or set KDEC_REMBG_PYTHON to a Python that has it)")
    return checks


def report(checks: list[Check]) -> str:
    lines = []
    for c in checks:
        mark = "✓" if c.ok else ("✗" if c.required else "–")
        lines.append(f"{mark} {c.label}: {c.detail}  [{c.purpose}]")
        if c.fix:
            lines.append(f"    {c.fix}")
    return "\n".join(lines)


def commands(checks: list[Check]) -> list[str]:
    """The fix commands that are real commands (for a "copy" button)."""
    return [c.fix for c in checks if not c.ok and c.fix and c.fix.split()[0] in ("sudo", "npm", "pip")]
