"""Firefox / LibreWolf / Thunderbird: our CSS imported from each profile's userChrome.css (install.sh snippet run
against fake profiles). The colors themselves were checked against a real Firefox 160 window (nested KWin)."""
import re
import subprocess

import pytest

from kdecustomizer import build
from kdecustomizer.generators import mozilla


def snippet(theme, tmp_path, key="b"):
    out = build.build(theme, tmp_path / key)
    sh = (out / "install.sh").read_text()
    i = sh.index("moz_profiles() {")
    j = sh.index("\n", sh.rindex("done < <(moz_profiles"))
    return out, sh[i:j]


def run(snip, out, home):
    subprocess.run(["bash", "-c", "set -euo pipefail\n" + snip], check=True, capture_output=True,
                   env={"PATH": "/usr/bin:/bin", "HOME": str(home), "CONF": str(home / ".config"), "DIR": str(out)})


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    ff = h / ".config/mozilla/firefox"
    (ff / "abc.default-release").mkdir(parents=True)
    (tmp_path / "elsewhere").mkdir()
    (ff / "profiles.ini").write_text("[Profile0]\nName=default-release\nIsRelative=1\nPath=abc.default-release\n\n"
                                     f"[Profile1]\nName=abs\nIsRelative=0\nPath={tmp_path / 'elsewhere'}\n\n"
                                     "[Profile2]\nName=gone\nIsRelative=1\nPath=missing.profile\n")
    tb = h / ".thunderbird" / "q.default"
    tb.mkdir(parents=True)
    (h / ".thunderbird/profiles.ini").write_text("[Profile0]\nPath=q.default\nIsRelative=1\n")
    return h


def test_css_sets_current_and_older_variable_names(midnight):
    css = mozilla.firefox_css(midnight)
    for var in ("--toolbar-background-color", "--toolbar-bgcolor", "--toolbox-background-color",
                "--lwt-accent-color", "--tab-background-color-selected", "--toolbar-field-background-color",
                "--panel-background-color", "--arrowpanel-background"):
        assert re.search(rf"^\s*{var}: #[0-9a-f]{{6}} !important;$", css, re.M), var
    assert "--layout-background-0" in mozilla.thunderbird_css(midnight)


def test_install_imports_into_every_profile(midnight, tmp_path, home):
    out, snip = snippet(midnight, tmp_path)
    p = home / ".config/mozilla/firefox/abc.default-release"
    (p / "chrome").mkdir()
    (p / "chrome/userChrome.css").write_text('@import "mine.css";\n#nav-bar { opacity: 1 }\n')
    run(snip, out, home)
    run(snip, out, home)                                                  # twice: nothing doubled
    uc = (p / "chrome/userChrome.css").read_text()
    assert uc == f'@import "mine.css";\n{mozilla.IMPORT}\n#nav-bar {{ opacity: 1 }}\n'
    assert (p / "chrome" / mozilla.FILE).read_text() == mozilla.firefox_css(midnight)
    assert (p / "user.js").read_text().count("legacyUserProfileCustomizations") == 1
    other = tmp_path / "elsewhere"                                        # absolute Path= too
    assert (other / "chrome/userChrome.css").read_text() == mozilla.IMPORT + "\n"
    tb = home / ".thunderbird/q.default"
    assert (tb / "chrome" / mozilla.FILE).read_text() == mozilla.thunderbird_css(midnight)


def test_switched_off_removes_ours_only(midnight, tmp_path, home):
    out, snip = snippet(midnight, tmp_path, "on")
    run(snip, out, home)
    midnight.apps.firefox = False
    out, snip = snippet(midnight, tmp_path, "off")
    run(snip, out, home)
    p = home / ".config/mozilla/firefox/abc.default-release/chrome"
    assert not (p / mozilla.FILE).exists() and mozilla.IMPORT not in (p / "userChrome.css").read_text()
    assert (home / ".thunderbird/q.default/chrome" / mozilla.FILE).exists()      # Thunderbird still on


def test_no_profiles_no_changes(midnight, tmp_path):
    out, snip = snippet(midnight, tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    run(snip, out, empty)
    assert list(empty.iterdir()) == []
