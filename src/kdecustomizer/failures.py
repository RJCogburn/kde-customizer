"""Why an install.sh run failed, in plain words: the common causes matched in its output, each with what to do.
Used by the GUI's Apply window (and `kdec apply`) after a non-zero exit."""
from __future__ import annotations

import re

# tool -> what provides it (for "command not found")
TOOLS = {
    "kwriteconfig6": "KDE Frameworks 6 (KConfig: package kconfig, or libkf6config-bin on Debian/Ubuntu)",
    "kreadconfig6": "KDE Frameworks 6 (KConfig: package kconfig, or libkf6config-bin on Debian/Ubuntu)",
    "kpackagetool6": "KDE Frameworks 6 (KPackage: package kpackage, or kpackagetool6 on Debian/Ubuntu)",
    "qdbus6": "Qt 6 tools (qt6-tools, or qdbus-qt6 on Debian/Ubuntu)",
    "plasma-apply-lookandfeel": "the Plasma 6 desktop (plasma-workspace)",
    "plasma-apply-colorscheme": "the Plasma 6 desktop (plasma-workspace)",
    "plasma-apply-desktoptheme": "the Plasma 6 desktop (plasma-workspace)",
    "plasma-apply-cursortheme": "the Plasma 6 desktop (plasma-workspace)",
    "plasma-apply-wallpaperimage": "the Plasma 6 desktop (plasma-workspace)",
    "pkexec": "polkit (pkexec)",
}

# (pattern, explanation) — checked in order, each reported once
PATTERNS: list[tuple[str, str]] = [
    (r"No space left on device",
     "The disk is full. Free some space (Filelight shows what takes it), then Apply again."),
    (r"Read-only file system",
     "Part of your home folder is read-only right now, so the theme files couldn't be written."),
    (r"Permission denied",
     "Some files in your home folder can't be changed by you — usually ones created with sudo. "
     "Look at the Details for the path, then give it back to yourself: sudo chown -R $USER <path>"),
    (r"(Could not connect to D-Bus|Cannot connect to the D-Bus|ServiceUnknown|org\.kde\.plasmashell.*not "
     r"(found|available)|Could not find the Plasma shell)",
     "Plasma isn't reachable from here (no desktop session on D-Bus). Apply from inside a running Plasma "
     "session, not over SSH or from a text console."),
    (r"(Not authorized|Request dismissed|Error executing command as another user)",
     "The admin password prompt was cancelled or refused, so the login screen / boot splash weren't updated. "
     "Apply again to retry, or untick them in the Apply window."),
    (r"(kpackagetool6.*(Error|error)|Could not install|Installation of .* failed|is not a valid)",
     "The global theme package couldn't be installed. Removing the old copy in Installed themes… and applying "
     "again usually fixes it."),
    (r"(mkinitcpio|dracut|update-initramfs).*(error|failed|ERROR)",
     "Rebuilding the boot image (for the boot splash) failed. The rest of the theme is applied; untick Boot "
     "splash next time, or fix the boot image tool's error shown in Details."),
]


def explain(output: str, code: int) -> list[str]:
    """What probably went wrong, newest cause first in the output order; [] when nothing known matched."""
    if code == 0:
        return []
    out: list[str] = []
    missing = []
    for m in re.finditer(r"(?:^|[\s:])([\w.-]+): (?:command )?not found", output):
        tool = m.group(1)
        if tool not in missing:
            missing.append(tool)
    for tool in missing:
        where = TOOLS.get(tool)
        out.append(f"“{tool}” isn't installed" + (f": it comes with {where}." if where else ".")
                   + " Setup check on the start page lists what's missing.")
    for pattern, text in PATTERNS:
        if re.search(pattern, output) and text not in out:
            out.append(text)
    return out


def last_error(output: str) -> str:
    """The last line that looks like an error, for when nothing known matched."""
    for line in reversed(output.strip().splitlines()):
        if re.search(r"(?i)\b(error|failed|cannot|could not|no such)\b", line):
            return line.strip()
    return ""
