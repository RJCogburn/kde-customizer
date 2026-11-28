"""Icon names: what KDE asks an icon theme for, and what each name is used for.

An icon theme is a folder of files named after these names (`folder-music.svg`, `user-trash.png`…). Apps ask for a
name, not a file; the theme that has a file with that name wins, otherwise the theme it inherits from is asked.
`CATALOG` = the names people most often want to change, with what they are for (freedesktop Icon Naming
Specification + the names KDE Plasma and its apps use). `theme_index()` lists every name an installed theme has,
so any name can be looked up. `custom_icons()` reads a folder of the user's own icons (`[iconset] custom_dir`).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# icon-spec Context of each category (index.theme needs one per directory)
CONTEXTS = {
    "Folders and places": "Places", "Apps": "Applications", "App menu categories": "Categories",
    "Devices and drives": "Devices", "File types": "MimeTypes", "Actions": "Actions", "Status": "Status",
    "Emblems": "Emblems",
}

NOTES = {
    "Folders and places": "Dolphin, file dialogs, the Places panel and the desktop.",
    "Apps": "App launcher, task manager, window title bars and Alt+Tab. An app's .desktop file says which name it "
            "uses (Icon=…). Every app installed here is listed under “Apps on this computer”.",
    "App menu categories": "The sections of the application launcher.",
    "Devices and drives": "Dolphin's Places panel, the Disks & Devices popup, file dialogs.",
    "File types": "Files in Dolphin and file dialogs. The name is the file's MIME type with / replaced by -.",
    "Actions": "Toolbar buttons and menu entries in apps. Most apps use the -symbolic variants at small sizes, "
               "which KDE recolors to match the color scheme.",
    "Status": "Notifications, dialogs and app status. Plasma's panel draws most tray icons (volume, network, "
              "battery) from the Plasma style instead, so changing these mostly shows up in apps.",
    "Emblems": "Small badges drawn over file icons (link, locked, shared…).",
}

# (name, category, what it's for)
CATALOG: list[tuple[str, str, str]] = [
    # folders and places
    ("folder", "Folders and places", "Any folder"),
    ("folder-open", "Folders and places", "A folder that is open (tree views)"),
    ("folder-documents", "Folders and places", "Documents folder"),
    ("folder-download", "Folders and places", "Downloads folder"),
    ("folder-music", "Folders and places", "Music folder"),
    ("folder-pictures", "Folders and places", "Pictures folder"),
    ("folder-videos", "Folders and places", "Videos folder"),
    ("folder-templates", "Folders and places", "Templates folder"),
    ("folder-publicshare", "Folders and places", "Public (shared) folder"),
    ("folder-cloud", "Folders and places", "Cloud storage folder (Nextcloud, Dropbox…)"),
    ("folder-remote", "Folders and places", "A folder on another computer"),
    ("folder-network", "Folders and places", "Network places"),
    ("folder-root", "Folders and places", "The root folder ( / )"),
    ("folder-temp", "Folders and places", "Temporary files folder"),
    ("folder-git", "Folders and places", "A folder under git version control (Dolphin)"),
    ("user-home", "Folders and places", "Your home folder"),
    ("user-desktop", "Folders and places", "Desktop folder"),
    ("user-trash", "Folders and places", "Trash, empty"),
    ("user-trash-full", "Folders and places", "Trash with files in it"),
    ("user-bookmarks", "Folders and places", "Bookmarks"),
    ("inode-directory", "Folders and places", "A folder shown as a file type (some file dialogs)"),
    ("network-workgroup", "Folders and places", "Network / Samba shares"),
    ("network-server", "Folders and places", "A server on the network"),
    ("start-here-kde-plasma", "Folders and places", "Application launcher button in the panel (Plasma 6)"),
    ("start-here-kde", "Folders and places", "Application launcher button (older name, still used)"),
    ("start-here", "Folders and places", "Application launcher (desktop-neutral name)"),
    ("recent-documents", "Folders and places", "Recent files"),
    # apps (KDE's own and common ones; the names their .desktop files ask for)
    ("org.kde.dolphin", "Apps", "Dolphin file manager"),
    ("system-file-manager", "Apps", "File manager (generic; other file managers)"),
    ("utilities-terminal", "Apps", "Konsole and other terminals"),
    ("internet-web-browser", "Apps", "Web browser (generic)"),
    ("firefox", "Apps", "Firefox"),
    ("chromium", "Apps", "Chromium"),
    ("google-chrome", "Apps", "Google Chrome"),
    ("preferences-system", "Apps", "System Settings"),
    ("plasmadiscover", "Apps", "Discover (software center)"),
    ("kate", "Apps", "Kate text editor"),
    ("kwrite", "Apps", "KWrite text editor"),
    ("accessories-text-editor", "Apps", "Text editor (generic)"),
    ("okular", "Apps", "Okular document viewer"),
    ("gwenview", "Apps", "Gwenview image viewer"),
    ("spectacle", "Apps", "Spectacle screenshots"),
    ("ark", "Apps", "Ark archive manager"),
    ("elisa", "Apps", "Elisa music player"),
    ("accessories-calculator", "Apps", "KCalc and other calculators"),
    ("utilities-system-monitor", "Apps", "System Monitor"),
    ("hwinfo", "Apps", "Info Center"),
    ("help-browser", "Apps", "Help Center / help"),
    ("partitionmanager", "Apps", "KDE Partition Manager"),
    ("filelight", "Apps", "Filelight disk usage"),
    ("krita", "Apps", "Krita"),
    ("kdenlive", "Apps", "Kdenlive video editor"),
    ("thunderbird", "Apps", "Thunderbird mail"),
    ("internet-mail", "Apps", "Mail app (generic)"),
    ("code", "Apps", "Visual Studio Code"),
    ("steam", "Apps", "Steam"),
    ("vlc", "Apps", "VLC media player"),
    ("libreoffice-writer", "Apps", "LibreOffice Writer"),
    ("libreoffice-calc", "Apps", "LibreOffice Calc"),
    ("libreoffice-impress", "Apps", "LibreOffice Impress"),
    ("gimp", "Apps", "GIMP"),
    ("inkscape", "Apps", "Inkscape"),
    ("obs", "Apps", "OBS Studio"),
    ("discord", "Apps", "Discord"),
    ("spotify-client", "Apps", "Spotify"),
    ("system-software-update", "Apps", "Software updates"),
    ("system-users", "Apps", "Users settings"),
    # launcher categories
    ("applications-all", "App menu categories", "All applications"),
    ("applications-accessories", "App menu categories", "Utilities / accessories"),
    ("applications-development", "App menu categories", "Development"),
    ("applications-education", "App menu categories", "Education"),
    ("applications-games", "App menu categories", "Games"),
    ("applications-graphics", "App menu categories", "Graphics"),
    ("applications-internet", "App menu categories", "Internet"),
    ("applications-multimedia", "App menu categories", "Multimedia"),
    ("applications-office", "App menu categories", "Office"),
    ("applications-science", "App menu categories", "Science"),
    ("applications-system", "App menu categories", "System"),
    ("applications-utilities", "App menu categories", "Utilities"),
    ("applications-other", "App menu categories", "Lost & found / other"),
    ("preferences-desktop", "App menu categories", "Settings"),
    ("favorites", "App menu categories", "Favorites"),
    ("system-help", "App menu categories", "Help"),
    # devices
    ("computer", "Devices and drives", "This computer"),
    ("computer-laptop", "Devices and drives", "A laptop"),
    ("drive-harddisk", "Devices and drives", "Internal hard disk / partition"),
    ("drive-harddisk-solidstate", "Devices and drives", "SSD / NVMe drive"),
    ("drive-removable-media", "Devices and drives", "Removable drive (generic)"),
    ("drive-removable-media-usb", "Devices and drives", "USB stick"),
    ("drive-optical", "Devices and drives", "CD/DVD drive"),
    ("media-flash", "Devices and drives", "Memory card"),
    ("media-optical", "Devices and drives", "A CD or DVD"),
    ("phone", "Devices and drives", "A phone (KDE Connect, MTP)"),
    ("smartphone", "Devices and drives", "A smartphone (KDE Connect)"),
    ("printer", "Devices and drives", "Printer"),
    ("scanner", "Devices and drives", "Scanner"),
    ("camera-photo", "Devices and drives", "Camera"),
    ("camera-web", "Devices and drives", "Webcam"),
    ("input-keyboard", "Devices and drives", "Keyboard"),
    ("input-mouse", "Devices and drives", "Mouse"),
    ("input-touchpad", "Devices and drives", "Touchpad"),
    ("input-gaming", "Devices and drives", "Game controller"),
    ("input-tablet", "Devices and drives", "Drawing tablet"),
    ("audio-card", "Devices and drives", "Sound card"),
    ("audio-headphones", "Devices and drives", "Headphones"),
    ("audio-headset", "Devices and drives", "Headset"),
    ("audio-speakers", "Devices and drives", "Speakers"),
    ("audio-input-microphone", "Devices and drives", "Microphone"),
    ("video-display", "Devices and drives", "Monitor / display"),
    ("network-wired", "Devices and drives", "Wired network"),
    ("network-wireless", "Devices and drives", "Wi-Fi"),
    ("bluetooth", "Devices and drives", "Bluetooth"),
    ("battery", "Devices and drives", "Battery"),
    # file types
    ("text-plain", "File types", "Plain text files (.txt)"),
    ("text-x-generic", "File types", "Text file (generic fallback)"),
    ("text-html", "File types", "Web pages (.html)"),
    ("text-markdown", "File types", "Markdown (.md)"),
    ("text-x-python", "File types", "Python scripts (.py)"),
    ("text-x-script", "File types", "Scripts (generic)"),
    ("application-x-shellscript", "File types", "Shell scripts (.sh)"),
    ("application-json", "File types", "JSON files"),
    ("application-pdf", "File types", "PDF documents"),
    ("image-x-generic", "File types", "Images (generic fallback)"),
    ("image-png", "File types", "PNG images"),
    ("image-jpeg", "File types", "JPEG photos"),
    ("image-svg+xml", "File types", "SVG drawings"),
    ("audio-x-generic", "File types", "Audio files (generic fallback)"),
    ("audio-mpeg", "File types", "MP3 audio"),
    ("audio-flac", "File types", "FLAC audio"),
    ("video-x-generic", "File types", "Video files (generic fallback)"),
    ("video-mp4", "File types", "MP4 video"),
    ("video-x-matroska", "File types", "MKV video"),
    ("package-x-generic", "File types", "Archives and packages (generic)"),
    ("application-zip", "File types", "ZIP archives"),
    ("application-x-compressed-tar", "File types", ".tar.gz archives"),
    ("application-x-iso9660-image", "File types", "Disk images (.iso)"),
    ("application-x-executable", "File types", "Programs"),
    ("application-x-desktop", "File types", "App launchers (.desktop)"),
    ("application-x-sharedlib", "File types", "Libraries (.so)"),
    ("x-office-document", "File types", "Word processor documents (generic)"),
    ("x-office-spreadsheet", "File types", "Spreadsheets (generic)"),
    ("x-office-presentation", "File types", "Presentations (generic)"),
    ("font-x-generic", "File types", "Fonts"),
    ("unknown", "File types", "Files of unknown type"),
    # actions
    ("document-new", "Actions", "New"),
    ("document-open", "Actions", "Open"),
    ("document-save", "Actions", "Save"),
    ("document-save-as", "Actions", "Save As"),
    ("document-print", "Actions", "Print"),
    ("edit-copy", "Actions", "Copy"),
    ("edit-cut", "Actions", "Cut"),
    ("edit-paste", "Actions", "Paste"),
    ("edit-delete", "Actions", "Delete"),
    ("edit-undo", "Actions", "Undo"),
    ("edit-redo", "Actions", "Redo"),
    ("edit-find", "Actions", "Find"),
    ("edit-rename", "Actions", "Rename"),
    ("view-refresh", "Actions", "Reload / refresh"),
    ("go-home", "Actions", "Go to home"),
    ("go-previous", "Actions", "Back"),
    ("go-next", "Actions", "Forward"),
    ("go-up", "Actions", "Up one level"),
    ("list-add", "Actions", "Add"),
    ("list-remove", "Actions", "Remove"),
    ("configure", "Actions", "Configure… (KDE)"),
    ("system-search", "Actions", "Search"),
    ("window-close", "Actions", "Close"),
    ("zoom-in", "Actions", "Zoom in"),
    ("zoom-out", "Actions", "Zoom out"),
    ("application-exit", "Actions", "Quit"),
    ("system-lock-screen", "Actions", "Lock screen (launcher, power menu)"),
    ("system-log-out", "Actions", "Log out"),
    ("system-reboot", "Actions", "Restart"),
    ("system-shutdown", "Actions", "Shut down"),
    ("system-suspend", "Actions", "Sleep"),
    ("media-playback-start", "Actions", "Play"),
    ("media-playback-pause", "Actions", "Pause"),
    ("media-playback-stop", "Actions", "Stop"),
    ("media-skip-forward", "Actions", "Next track"),
    ("media-skip-backward", "Actions", "Previous track"),
    # status
    ("dialog-information", "Status", "Information messages"),
    ("dialog-warning", "Status", "Warnings"),
    ("dialog-error", "Status", "Errors"),
    ("dialog-question", "Status", "Questions"),
    ("dialog-password", "Status", "Password prompts"),
    ("security-high", "Status", "Secure (padlock, KDE Wallet)"),
    ("security-low", "Status", "Not secure"),
    ("audio-volume-high", "Status", "Volume: loud"),
    ("audio-volume-medium", "Status", "Volume: medium"),
    ("audio-volume-low", "Status", "Volume: quiet"),
    ("audio-volume-muted", "Status", "Volume: muted"),
    ("network-wireless-signal-excellent", "Status", "Wi-Fi: strong signal"),
    ("network-offline", "Status", "No network"),
    ("battery-full", "Status", "Battery full"),
    ("battery-low", "Status", "Battery low"),
    ("battery-full-charging", "Status", "Battery charging"),
    ("appointment-soon", "Status", "Upcoming event"),
    ("mail-unread", "Status", "Unread mail"),
    ("update-high", "Status", "Important updates available"),
    ("image-missing", "Status", "Shown where an icon can't be found"),
    # emblems
    ("emblem-symbolic-link", "Emblems", "The file is a link"),
    ("emblem-locked", "Emblems", "You can't change this file"),
    ("emblem-shared", "Emblems", "Shared on the network"),
    ("emblem-favorite", "Emblems", "Favorite"),
    ("emblem-important", "Emblems", "Important"),
    ("emblem-mounted", "Emblems", "Mounted drive"),
    ("emblem-unmounted", "Emblems", "Not mounted"),
    ("emblem-checked", "Emblems", "Synced / OK (cloud folders)"),
]

PURPOSE = {name: purpose for name, _c, purpose in CATALOG}
CATEGORY = {name: cat for name, cat, _p in CATALOG}
EXTENSIONS = (".svg", ".png")


def context(name: str) -> str:
    """index.theme Context for an icon name (Applications when we don't know it)."""
    if name in CATEGORY:
        return CONTEXTS[CATEGORY[name]]
    for prefix, ctx in [("folder", "Places"), ("user-", "Places"), ("drive-", "Devices"), ("media-", "Devices"),
                        ("input-", "Devices"), ("emblem-", "Emblems"), ("dialog-", "Status"), ("applications-",
                        "Categories"), ("text-", "MimeTypes"), ("image-", "MimeTypes"), ("audio-x", "MimeTypes"),
                        ("video-x", "MimeTypes"), ("application-", "MimeTypes"), ("x-office-", "MimeTypes")]:
        if name.startswith(prefix):
            return ctx
    return "Applications"


# --- what an installed theme has --------------------------------------------------------------------

@dataclass
class Entry:
    path: Path          # the file shown for it (scalable, else the biggest size)
    context: str


_index_cache: dict[tuple, dict[str, Entry]] = {}


def theme_index(base: str, refresh: bool = False) -> dict[str, Entry]:
    """Every icon name the theme (and what it inherits, down to hicolor) answers to -> the file shown for it.
    Cached per theme and data dirs (a big theme has 100k+ files)."""
    from .appicons import _data_dirs, _index, _theme_dirs, theme_chain
    key = (base, tuple(map(str, _data_dirs())), str(Path.home()))
    if key in _index_cache and not refresh:
        return _index_cache[key]
    out: dict[str, Entry] = {}
    for theme in theme_chain(base):
        tdirs = _theme_dirs(theme)
        cp = next((c for c in map(_index, tdirs) if c.has_section("Icon Theme")), None)
        if cp is None:
            continue
        sec = cp["Icon Theme"]
        dirs = []
        for d in (sec.get("Directories", "") + "," + sec.get("ScaledDirectories", "")).split(","):
            d = d.strip()
            if d and cp.has_section(d):
                size = int(cp[d].get("Size", "0") or 0) * int(cp[d].get("Scale", "1") or 1)
                dirs.append(("symbolic" in d, cp[d].get("Type", "Threshold") != "Scalable", -size, d,
                             cp[d].get("Context", "")))
        dirs.sort()
        found: dict[str, Entry] = {}
        for tdir in tdirs:
            for *_k, d, ctx in dirs:
                try:
                    entries = os.scandir(tdir / d)
                except OSError:
                    continue
                with entries:
                    for e in entries:
                        stem, ext = os.path.splitext(e.name)
                        if ext in EXTENSIONS and stem not in found:
                            found[stem] = Entry(Path(e.path), ctx)
        for k, v in found.items():
            out.setdefault(k, v)            # the first theme in the chain wins, like the lookup does
    _index_cache[key] = out
    return out


def installed_apps(refresh: bool = False) -> dict[str, str]:
    """icon name -> app name, for every app in the menu (one cached scan, shared with appicons)."""
    from .appicons import installed_apps as apps
    return apps(refresh)


# --- the user's own icons ---------------------------------------------------------------------------

def custom_icons(folder: str | Path | None) -> dict[str, Path]:
    """name -> file in a folder of the user's icons (<name>.svg or <name>.png; SVG wins). Subfolders are
    searched too, so a folder laid out like an icon theme (scalable/apps/…) works as well."""
    out: dict[str, Path] = {}
    if not folder:
        return out
    root = Path(folder).expanduser()
    if not root.is_dir():
        return out
    for f in sorted(root.rglob("*"), key=lambda p: (len(p.parts), p.suffix != ".svg", str(p))):
        if f.suffix.lower() in EXTENSIONS and f.is_file() and not f.name.startswith("."):
            out.setdefault(f.stem, f)
    return out


def unknown_names(names, base: str) -> list[str]:
    """Names in the user's folder that nothing asks for here — usually a typo in the file name."""
    known = set(PURPOSE) | set(theme_index(base)) | set(installed_apps())
    return sorted(n for n in names if n not in known)


def png_size(data: bytes) -> tuple[int, int]:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError("not a PNG file")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def png_as_svg(data: bytes) -> str:
    """A PNG inside a square SVG (centered), so one scalable file serves every size, like the app icons."""
    import base64
    w, h = png_size(data)
    s = max(w, h)
    b64 = base64.b64encode(data).decode()
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{s}" '
            f'height="{s}" viewBox="0 0 {s} {s}"><image x="{(s - w) / 2:g}" y="{(s - h) / 2:g}" width="{w}" '
            f'height="{h}" xlink:href="data:image/png;base64,{b64}"/></svg>')


def add_custom(folder: str | Path, name: str, source: str | Path) -> Path:
    """Copy a file into the custom folder as <name>.<ext> (replacing that name's other file)."""
    import shutil
    src = Path(source)
    ext = src.suffix.lower()
    if ext not in EXTENSIONS:
        raise ValueError("icons must be .svg or .png files")
    data = src.read_bytes()
    if ext == ".png":
        png_size(data)
    elif b"<svg" not in data[:4096]:
        raise ValueError(f"{src.name} is not an SVG file")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    remove_custom(folder, name)
    dest = folder / f"{name}{ext}"
    shutil.copyfile(src, dest)
    return dest


def remove_custom(folder: str | Path, name: str) -> None:
    """Delete every file for this name (both kinds, in any subfolder)."""
    root = Path(folder)
    if root.is_dir():
        for ext in EXTENSIONS:
            for f in root.rglob(f"{name}{ext}"):
                f.unlink(missing_ok=True)
