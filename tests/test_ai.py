"""AI layer without a real provider: parsing, checks, and generate() against a local fake OpenAI server."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from kdecustomizer import ai, spec

GOOD = """Here you go:
```toml
name = "Forest"
id = "org.kdecustomizer.forest"
wallpaper = "/somewhere/else.png"
author = "Guessed Name"

[palette]
background = "#102018"
surface = "#18302a"
foreground = "#e8f0e8"
accent = "#4caf50"
```
A calm green theme."""

LOW_CONTRAST = GOOD.replace('foreground = "#e8f0e8"', 'foreground = "#203028"')


def test_parse_reply_takes_the_toml_and_keeps_users_fields():
    current = spec.Theme(wallpaper="/my/wall.png", author="Me")
    t = ai.parse_reply(GOOD, current)
    assert t.name == "Forest" and t.palette.accent == "#4caf50"
    assert t.wallpaper == "/my/wall.png" and t.author == "Me"


@pytest.mark.parametrize("bad", ["no toml here = = =", "```toml\n[palette]\naccent = \"#zzzzzz\"\n```",
                                 "```toml\nbogus_key = 1\n```"])
def test_parse_reply_rejects(bad):
    with pytest.raises(ValueError):
        ai.parse_reply(bad)


def test_check_flags_contrast_and_missing_themes():
    t = ai.parse_reply(LOW_CONTRAST)
    t.icons = "NotInstalled"
    problems = ai.check(t, {"icons": ["breeze", "Papirus"], "cursors": [], "plasma_style": [], "widget_style": []})
    assert any("foreground on background" in p for p in problems)
    assert any("NotInstalled" in p for p in problems)
    assert ai.check(ai.parse_reply(GOOD), {}) == []


def test_reference_guide_mentions_every_section():
    guide = ai.reference({"icons": ["breeze"], "cursors": [], "plasma_style": [], "widget_style": []})
    for section in ("[palette]", "[plasma]", "[iconset]", "[cursorset]", "[widgets]", "[decoration]",
                    "[splash_screen]", "[login_screen]", "[fonts]", "[[panels]]"):
        assert section in guide, section


class FakeOpenAI(BaseHTTPRequestHandler):
    replies: list[str] = []
    requests: list[dict] = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOpenAI.requests.append(body)
        reply = FakeOpenAI.replies.pop(0)
        data = json.dumps({"choices": [{"message": {"content": reply}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture
def fake_server():
    srv = HTTPServer(("127.0.0.1", 0), FakeOpenAI)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    FakeOpenAI.requests = []
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


def test_generate_fixes_problems_in_a_second_round(fake_server):
    FakeOpenAI.replies = ["not a theme at all ```toml\n= broken\n```", GOOD]
    prov = ai.Provider("Fake", "openai", fake_server, model="fake-model")
    theme, note, problems = ai.generate("a calm forest theme", None, prov, use_wallpaper=False)
    assert theme.name == "Forest"
    assert len(FakeOpenAI.requests) == 2
    second = FakeOpenAI.requests[1]["messages"]
    assert second[-1]["role"] == "user" and "Fix these problems" in second[-1]["content"]
    assert FakeOpenAI.requests[0]["model"] == "fake-model"


def test_generate_reports_unreachable_provider():
    prov = ai.Provider("Nowhere", "openai", "http://127.0.0.1:9/v1", model="m")
    with pytest.raises(ai.AIError, match="could not connect"):
        ai.generate("x", None, prov, use_wallpaper=False)
