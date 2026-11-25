"""Local image-AI backends for signature icons: Fooocus, ComfyUI, and A1111/Forge/SD.Next.

`detect(url)` figures out which one is listening; `Backend.generate(prompt, negative, seed)` returns
PNG/JPEG bytes. Stdlib only (urllib + a tiny websocket client for Fooocus' Gradio queue).
`to_icon(bytes)` turns a render on a plain background into a transparent, square 512px icon master.
"""
from __future__ import annotations

import base64
import io
import json
import os
import random
import re
import subprocess
import socket
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class ImageGenError(RuntimeError):
    pass


def _get(url: str, timeout: float = 10) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "kde-customizer"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _post_json(url: str, body: dict, timeout: float = 600) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "kde-customizer"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _ok(url: str) -> bytes | None:
    try:
        return _get(url, timeout=4)
    except (urllib.error.URLError, OSError, ValueError):
        return None


# --- backends ---------------------------------------------------------------------------

class Backend:
    name = "?"
    model = ""            # checkpoint to render with ("" = the image AI's own default; "auto" = pick_model())
    size = (1024, 1024)   # render size (SDXL is trained near 1 megapixel: wallpapers use 1344x768 and upscale)

    def __init__(self, url: str):
        self.url = url.rstrip("/")

    def generate(self, prompt: str, negative: str, seed: int) -> bytes:
        raise NotImplementedError

    def models(self) -> list[str]:
        """Checkpoints the image AI can use (empty if it can't say)."""
        return []

    def default_model(self) -> str:
        return ""

    def chosen_model(self) -> str:
        """The checkpoint generate() will ask for, or "" for the image AI's default."""
        names = self.models()
        if self.model == "auto":
            return pick_model(names) or ""
        return self.model if self.model in names else ""


# Words in checkpoint names: general SDXL models that render clean objects well vs ones that don't fit icons
# (inpainting/refiner models, Pony/anime fine-tunes, few-step Lightning/Turbo models needing other settings).
_GOOD = ("juggernaut", "realvis", "dreamshaper", "zavychroma", "copax", "proteus", "albedo", "crystalclear",
         "nightvision", "leosam", "dynavision", "sdxl_base", "sd_xl_base", "base_1.0")
_BAD = ("inpaint", "refiner", "pony", "anime", "animagine", "illustrious", "noob", "hentai", "nsfw", "lightning",
        "turbo", "hyper", "lcm", "sd15", "sd1.5", "v1-5", "1.5")


def closest_ratio(choices: list[str], size: tuple[int, int]) -> str | None:
    """Fooocus' aspect-ratio choice ("1344×768 <span>…") nearest to `size`'s shape (exact size first)."""
    want = size[0] / size[1]
    best = None
    for ch in choices:
        m = re.match(r"\s*(\d+)\s*[×x*]\s*(\d+)", ch)
        if not m:
            continue
        w, h = int(m[1]), int(m[2])
        key = ((w, h) != tuple(size), abs(w / h - want), -w * h)
        if best is None or key < best[0]:
            best = (key, ch)
    return best[1] if best else None


def pick_model(names: list[str]) -> str | None:
    """Best checkpoint for clean, object-on-white icon renders, by name; None if nothing fits."""
    best, score = None, 0
    for n in names:
        low = n.lower()
        if any(b in low for b in _BAD):
            continue
        s = next((len(_GOOD) - i for i, g in enumerate(_GOOD) if g in low), 0)
        if s > score:
            best, score = n, s
    return best


class A1111(Backend):
    """AUTOMATIC1111 / Forge / reForge / SD.Next (`--api`)."""
    name = "A1111/Forge"

    def models(self) -> list[str]:
        try:
            return [m["title"] for m in json.loads(_get(f"{self.url}/sdapi/v1/sd-models"))]
        except (OSError, ValueError, KeyError):
            return []

    def generate(self, prompt, negative, seed):
        body = {"prompt": prompt, "negative_prompt": negative, "seed": seed, "width": self.size[0], "height": self.size[1],
                "steps": 25, "cfg_scale": 6, "batch_size": 1, "n_iter": 1}
        if (m := self.chosen_model()):
            body["override_settings"] = {"sd_model_checkpoint": m}       # just for this request
            body["override_settings_restore_afterwards"] = True
        try:
            r = _post_json(f"{self.url}/sdapi/v1/txt2img", body)
        except urllib.error.HTTPError as e:
            raise ImageGenError(f"{self.name}: HTTP {e.code}: {e.read()[:200]!r}") from None
        return base64.b64decode(r["images"][0])


class ComfyUI(Backend):
    name = "ComfyUI"

    def models(self) -> list[str]:
        try:
            info = json.loads(_get(f"{self.url}/object_info/CheckpointLoaderSimple"))
            return list(info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0])
        except (OSError, ValueError, KeyError, IndexError):
            return []

    def _checkpoint(self) -> str:
        names = self.models()
        if not names:
            raise ImageGenError("ComfyUI has no checkpoints installed")
        return self.chosen_model() or next((n for n in names if "xl" in n.lower()), names[0])

    def generate(self, prompt, negative, seed):
        ckpt = self._checkpoint()
        graph = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["1", 1]}},
            "4": {"class_type": "EmptyLatentImage", "inputs": {"width": self.size[0], "height": self.size[1],
                                                                     "batch_size": 1}},
            "5": {"class_type": "KSampler", "inputs": {
                "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0],
                "seed": seed, "steps": 25, "cfg": 6.0, "sampler_name": "dpmpp_2m", "scheduler": "karras",
                "denoise": 1.0}},
            "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
            "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "kdec-icon"}},
        }
        pid = _post_json(f"{self.url}/prompt", {"prompt": graph, "client_id": "kde-customizer"})["prompt_id"]
        deadline = time.time() + 600
        while time.time() < deadline:
            hist = json.loads(_get(f"{self.url}/history/{pid}"))
            if pid in hist:
                for out in hist[pid]["outputs"].values():
                    for img in out.get("images", []):
                        q = urllib.parse.urlencode({k: img[k] for k in ("filename", "subfolder", "type")})
                        return _get(f"{self.url}/view?{q}")
                raise ImageGenError("ComfyUI finished without an image")
            time.sleep(1)
        raise ImageGenError("ComfyUI took longer than 10 minutes")


class _WS:
    """Minimal RFC 6455 client: text frames, client masking, ping/pong. Enough for Gradio's queue."""

    def __init__(self, url: str, timeout: float = 600):
        u = urllib.parse.urlparse(url)
        self.sock = socket.create_connection((u.hostname, u.port or 80), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {u.path or '/'} HTTP/1.1\r\nHost: {u.hostname}:{u.port or 80}\r\n"
                           f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                           f"Sec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(1)
            if not chunk:
                raise ImageGenError("websocket handshake failed")
            head += chunk
        status = head.split(b"\r\n")[0]
        if b" 101 " not in status:  # (no backslashes inside f-strings: Python 3.11 rejects them)
            raise ImageGenError("websocket refused: " + status.decode(errors="replace"))

    def _read(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ImageGenError("connection closed by the image AI")
            buf += chunk
        return buf

    def send(self, obj) -> None:
        data = json.dumps(obj).encode()
        mask = os.urandom(4)
        n = len(data)
        hdr = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else
                               bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536 else
                               bytes([0x80 | 127]) + struct.pack(">Q", n))
        self.sock.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self) -> dict:
        payload = b""
        while True:
            b1, b2 = self._read(2)
            op, n = b1 & 0x0F, b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            data = self._read(n)
            if op == 0x9:  # ping
                self.sock.sendall(bytes([0x8A, 0x80]) + os.urandom(4))
                continue
            if op == 0x8:
                raise ImageGenError("the image AI closed the connection")
            payload += data
            if b1 & 0x80:
                return json.loads(payload)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


BASE_MODEL = "Base Model (SDXL only)"     # Fooocus' checkpoint dropdown


class Fooocus(Backend):
    """Fooocus (incl. mashb1t's 1-Up Edition) through its Gradio 3 queue — the same calls its Generate
    button makes: get_task(all settings) then generate_clicked(task). Settings are matched by label, so
    reordered or added controls in newer Fooocus versions don't break it."""
    name = "Fooocus"

    def __init__(self, url: str, performance: str = ""):
        super().__init__(url)
        self.performance = performance
        cfg = json.loads(_get(f"{self.url}/config"))
        self.comps = {c["id"]: c for c in cfg["components"]}
        deps = cfg["dependencies"]
        self.task_fn = max(range(len(deps)), key=lambda i: len(deps[i]["inputs"]))
        state_id = deps[self.task_fn]["outputs"][0]
        self.gen_fn = next((i for i, d in enumerate(deps) if d["inputs"] == [state_id] and len(d["outputs"]) >= 3),
                           None)
        if self.gen_fn is None or len(deps[self.task_fn]["inputs"]) < 50:
            raise ImageGenError("this Fooocus version's interface isn't recognised")
        self.inputs = deps[self.task_fn]["inputs"]

    def _base_model(self) -> dict:
        return next((c.get("props", {}) for c in self.comps.values()
                     if c.get("props", {}).get("label") == BASE_MODEL), {})

    def models(self) -> list[str]:
        return [ch[0] if isinstance(ch, (list, tuple)) else ch for ch in self._base_model().get("choices", [])]

    def default_model(self) -> str:
        return self._base_model().get("value") or ""

    def _value(self, cid: int, prompt: str, negative: str, seed: int):
        c = self.comps[cid]
        p = c.get("props", {})
        label, elem = p.get("label"), p.get("elem_id")
        if c["type"] == "state":
            return None
        if elem == "positive_prompt":
            return prompt
        if elem == "negative_prompt":
            return negative
        if label == "Selected Styles":
            return []  # Fooocus V2 prompt expansion adds clutter; icons need literal prompts
        if label == "Image Number":
            return 1
        if label == "Seed":
            return str(seed)
        if label == "Output Format":
            return "png"
        if label == "Disable Preview":
            return True
        if label == "Performance" and self.performance:
            return self.performance
        if label == BASE_MODEL and (m := self.chosen_model()):
            return m
        if label == "Aspect Ratios":
            choices = [ch[0] if isinstance(ch, (list, tuple)) else ch for ch in p.get("choices", [])]
            return closest_ratio(choices, self.size) or p.get("value")
        return p.get("value")

    def _run(self, fn: int, data: list, session: str) -> dict:
        ws = _WS(self.url.replace("http", "ws", 1) + "/queue/join")
        try:
            while True:
                msg = ws.recv()
                kind = msg.get("msg")
                if kind == "send_hash":
                    ws.send({"fn_index": fn, "session_hash": session})
                elif kind == "send_data":
                    ws.send({"data": data, "event_data": None, "fn_index": fn, "session_hash": session})
                elif kind == "process_completed":
                    if not msg.get("success", False):
                        raise ImageGenError(f"Fooocus error: {str(msg.get('output'))[:300]}")
                    return msg.get("output") or {}
                elif kind == "queue_full":
                    raise ImageGenError("Fooocus queue is full — try again shortly")
        finally:
            ws.close()

    def generate(self, prompt, negative, seed):
        session = base64.b32encode(os.urandom(10)).decode().lower()
        self._run(self.task_fn, [self._value(c, prompt, negative, seed) for c in self.inputs], session)
        out = self._run(self.gen_fn, [None], session)
        files: list[str] = []

        def walk(x):
            if isinstance(x, dict):
                name = x.get("name") or x.get("path")
                if isinstance(name, str) and name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    files.append(name)
                for v in x.values():
                    walk(v)
            elif isinstance(x, (list, tuple)):
                for v in x:
                    walk(v)
            elif isinstance(x, str) and x.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) and "/" in x:
                files.append(x)
        walk(out.get("data"))
        if not files:
            raise ImageGenError("Fooocus finished but returned no image")
        return _get(f"{self.url}/file={urllib.parse.quote(files[-1])}", timeout=60)


def detect(url: str, performance: str = "", model: str = "") -> Backend:
    """Return the backend serving `url`, or raise ImageGenError with a helpful message.

    `model`: checkpoint to render with — a name the image AI lists, "auto" (pick_model) or "" (its default)."""
    url = url.rstrip("/")
    if _ok(f"{url}/sdapi/v1/options") is not None:
        b: Backend = A1111(url)
    elif _ok(f"{url}/system_stats") is not None:
        b = ComfyUI(url)
    else:
        cfg = _ok(f"{url}/config")
        if cfg and b"Fooocus" in cfg:
            b = Fooocus(url, performance)
        elif cfg is None and _ok(url) is None:
            raise ImageGenError(f"nothing is answering at {url} — start your image AI (e.g. from Stability Matrix)")
        else:
            raise ImageGenError(f"{url} isn't a supported image AI. Supported: Fooocus, ComfyUI, "
                                "A1111/Forge (started with --api)")
    b.model = model.strip()
    return b


# --- post-processing ------------------------------------------------------------------------

# --- background removal -------------------------------------------------------------------------------
# A segmentation model (rembg: u2net / isnet) is far better than any heuristic on metal, glass and soft edges.
# It's used when importable here, or through another Python that has it — usually the image AI's own env
# (Fooocus / ComfyUI / A1111 ship rembg for their mask tools), found from its running process. Only when
# neither is available does the built-in edge flood fill below run.

def _rembg_cache() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "kdecustomizer" / "rembg-python"


_found_python: list = []          # [path or None] once looked up in this process
_AI_PROCESS = re.compile(r"(launch\.py|entry_with_update\.py|webui\.py|fooocus|comfyui|stable-diffusion-webui|forge)",
                         re.I)


def _clean_env() -> dict[str, str]:
    """Environment for another Python: nothing from our own runtime (AppImage/venv paths, Qt plugins)."""
    drop = ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "LD_LIBRARY_PATH", "LD_PRELOAD", "VIRTUAL_ENV")
    return {k: v for k, v in os.environ.items() if k not in drop and not k.startswith("QT_")}


def _has_rembg(python: str) -> bool:
    try:
        return subprocess.run([python, "-c", "import rembg, onnxruntime"], capture_output=True,
                              timeout=60, env=_clean_env()).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _ai_pythons() -> list[str]:
    """Pythons of running image-AI processes (venv interpreters as launched, not the resolved binary)."""
    out = []
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            argv = (proc / "cmdline").read_bytes().split(b"\0")
            cwd = os.readlink(proc / "cwd")
        except OSError:
            continue
        args = [a.decode(errors="replace") for a in argv if a]
        if not args or "python" not in Path(args[0]).name or not _AI_PROCESS.search(" ".join(args[1:]) + " " + cwd):
            continue
        py = args[0] if os.path.isabs(args[0]) else os.path.join(cwd, args[0])
        if os.path.isfile(py) and py not in out:
            out.append(py)
    return out


def rembg_python() -> str | None:
    """A Python that can run rembg: $KDEC_REMBG_PYTHON, the last one found, or a running image AI's."""
    if _found_python:
        return _found_python[0]
    candidates = [os.environ.get("KDEC_REMBG_PYTHON", "")]
    try:
        candidates.append(_rembg_cache().read_text().strip())
    except OSError:
        pass
    candidates += _ai_pythons()
    found = next((c for c in candidates if c and os.path.isfile(c) and _has_rembg(c)), None)
    if found:
        try:
            _rembg_cache().parent.mkdir(parents=True, exist_ok=True)
            _rembg_cache().write_text(found)
        except OSError:
            pass
    _found_python.append(found)
    return found


def _rembg_model() -> str:
    """The best model already downloaded (no surprise 170 MB download), else u2net."""
    home = Path(os.environ.get("U2NET_HOME") or Path.home() / ".u2net")
    for model in ("isnet-general-use", "u2net"):
        if (home / f"{model}.onnx").is_file():
            return model
    return "u2net"


def remove_background(data: bytes) -> tuple[bytes | None, str]:
    """(RGBA PNG bytes, how) via rembg — in this Python or another one; (None, reason) when unavailable."""
    model = _rembg_model()
    try:
        from rembg import new_session, remove
        return remove(data, session=new_session(model)), f"rembg ({model})"
    except ImportError:
        pass
    py = rembg_python()
    if py is None:
        return None, "no rembg found"
    code = ("import sys; from rembg import remove, new_session; "
            f"sys.stdout.buffer.write(remove(sys.stdin.buffer.read(), session=new_session({model!r})))")
    try:
        r = subprocess.run([py, "-c", code], input=data, capture_output=True, timeout=300, env=_clean_env())
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"rembg via {py} failed: {e}"
    if r.returncode != 0 or not r.stdout.startswith(b"\x89PNG"):
        return None, f"rembg via {py} failed: {r.stderr.decode(errors='replace')[-200:]}"
    return r.stdout, f"rembg ({model}) via {py}"


def cutout_method() -> str:
    """What to_icon() will use, for the GUI/CLI to show."""
    try:
        import rembg  # noqa: F401
        return f"rembg ({_rembg_model()})"
    except ImportError:
        py = rembg_python()
        return f"rembg ({_rembg_model()}) via {py}" if py else "built-in (no rembg found)"


def _components(fg: bytearray, w: int, h: int, keep_ratio: float = 0.01) -> bytearray:
    """Keep every 4-connected foreground region at least keep_ratio of the largest (drops specks only)."""
    from collections import deque
    label = bytearray(w * h)
    regions: list[list[int]] = []
    for start in range(w * h):
        if not fg[start] or label[start]:
            continue
        region, q = [start], deque([start])
        label[start] = 1
        while q:
            i = q.popleft()
            x, y = i % w, i // w
            for j in (i - 1 if x else -1, i + 1 if x < w - 1 else -1, i - w if y else -1, i + w if y < h - 1 else -1):
                if j >= 0 and fg[j] and not label[j]:
                    label[j] = 1
                    region.append(j)
                    q.append(j)
        regions.append(region)
    keep = bytearray(w * h)
    if not regions:
        return keep
    biggest = max(map(len, regions))
    for region in regions:
        if len(region) >= biggest * keep_ratio:
            for i in region:
                keep[i] = 1
    return keep


def to_icon(data: bytes, size: int = 512, log=lambda s: None) -> "Image.Image":
    """Cut the subject out of a render on a plain-ish backdrop, crop, pad to a square, scale to `size`.

    A segmentation model (see remove_background) when one is reachable; else a flood fill from the image edge
    that only spreads through backdrop-colored pixels or smooth steps away from them (gradients, soft shadows),
    so light-gray metal behind a crisp edge stays part of the icon. Every sizable piece is kept."""
    from collections import deque

    from PIL import Image, ImageFilter
    cut, how = remove_background(data)
    if cut is not None:
        log(f"background removed with {how}")
        with Image.open(io.BytesIO(cut)) as im:
            rgba = im.convert("RGBA")
        rgba.thumbnail((size, size))
        return _square(rgba, size)
    log(f"background removed with the built-in cutter ({how}; install rembg for cleaner results)")
    with Image.open(io.BytesIO(data)) as src:
        im = src.convert("RGB")
    im.thumbnail((size, size))
    w, h = im.size
    px = im.tobytes()
    border = [*range(w), *range((h - 1) * w, h * w), *range(0, h * w, w), *range(w - 1, h * w, w)]
    edge = sorted((px[3 * i], px[3 * i + 1], px[3 * i + 2]) for i in border)
    bgc = tuple(sorted(c[k] for c in edge)[len(edge) // 2] for k in range(3))     # backdrop color

    def dist_bg(i):
        return abs(px[3 * i] - bgc[0]) + abs(px[3 * i + 1] - bgc[1]) + abs(px[3 * i + 2] - bgc[2])

    def step(i, j):
        return abs(px[3 * i] - px[3 * j]) + abs(px[3 * i + 1] - px[3 * j + 1]) + abs(px[3 * i + 2] - px[3 * j + 2])

    near, far, smooth = 36, 150, 9        # summed RGB differences
    bg = bytearray(w * h)
    q = deque(i for i in border if dist_bg(i) < near)
    for i in q:
        bg[i] = 1
    while q:
        i = q.popleft()
        x, y = i % w, i // w
        for j in (i - 1 if x else -1, i + 1 if x < w - 1 else -1, i - w if y else -1, i + w if y < h - 1 else -1):
            if j < 0 or bg[j]:
                continue
            d = dist_bg(j)
            if d < near or (d < far and step(i, j) < smooth):
                bg[j] = 1
                q.append(j)
    fg = _components(bytearray(0 if b else 1 for b in bg), w, h)
    mask = Image.frombytes("L", (w, h), bytes(255 if v else 0 for v in fg)).filter(ImageFilter.GaussianBlur(0.8))
    rgba = im.convert("RGBA")
    rgba.putalpha(mask)
    return _square(rgba, size)


def _square(rgba, size: int):
    """Crop to the visible subject, pad to a square with a small margin, scale to `size`."""
    from PIL import Image
    box = rgba.getchannel("A").point(lambda v: 255 if v > 32 else 0).getbbox()
    if box:
        rgba = rgba.crop(box)
    side = int(max(rgba.size) * 1.08)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(rgba, ((side - rgba.size[0]) // 2, (side - rgba.size[1]) // 2), rgba)
    return canvas.resize((size, size), Image.LANCZOS)


def random_seed() -> int:
    return random.randint(1, 2**31 - 1)
