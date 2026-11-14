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
import socket
import struct
import time
import urllib.error
import urllib.parse
import urllib.request


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

    def __init__(self, url: str):
        self.url = url.rstrip("/")

    def generate(self, prompt: str, negative: str, seed: int) -> bytes:
        raise NotImplementedError


class A1111(Backend):
    """AUTOMATIC1111 / Forge / reForge / SD.Next (`--api`)."""
    name = "A1111/Forge"

    def generate(self, prompt, negative, seed):
        try:
            r = _post_json(f"{self.url}/sdapi/v1/txt2img", {
                "prompt": prompt, "negative_prompt": negative, "seed": seed, "width": 1024, "height": 1024,
                "steps": 25, "cfg_scale": 6, "batch_size": 1, "n_iter": 1})
        except urllib.error.HTTPError as e:
            raise ImageGenError(f"{self.name}: HTTP {e.code}: {e.read()[:200]!r}") from None
        return base64.b64decode(r["images"][0])


class ComfyUI(Backend):
    name = "ComfyUI"

    def _checkpoint(self) -> str:
        info = json.loads(_get(f"{self.url}/object_info/CheckpointLoaderSimple"))
        names = info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
        if not names:
            raise ImageGenError("ComfyUI has no checkpoints installed")
        return next((n for n in names if "xl" in n.lower()), names[0])

    def generate(self, prompt, negative, seed):
        ckpt = self._checkpoint()
        graph = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["1", 1]}},
            "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
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
        if label == "Aspect Ratios":
            choices = [ch[0] if isinstance(ch, (list, tuple)) else ch for ch in p.get("choices", [])]
            return next((ch for ch in choices if ch.startswith("1024×1024")), p.get("value"))
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


def detect(url: str, performance: str = "") -> Backend:
    """Return the backend serving `url`, or raise ImageGenError with a helpful message."""
    url = url.rstrip("/")
    if _ok(f"{url}/sdapi/v1/options") is not None:
        return A1111(url)
    if _ok(f"{url}/system_stats") is not None:
        return ComfyUI(url)
    cfg = _ok(f"{url}/config")
    if cfg and b"Fooocus" in cfg:
        return Fooocus(url, performance)
    if cfg is None and _ok(url) is None:
        raise ImageGenError(f"nothing is answering at {url} — start your image AI (e.g. from Stability Matrix)")
    raise ImageGenError(f"{url} isn't a supported image AI. Supported: Fooocus, ComfyUI, "
                        "A1111/Forge (started with --api)")


# --- post-processing ------------------------------------------------------------------------

def _components(fg: bytearray, w: int, h: int) -> bytearray:
    """Keep only the largest 4-connected foreground region (drops specks, stray reflections)."""
    from collections import deque
    label = bytearray(w * h)
    best: list[int] = []
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
        if len(region) > len(best):
            best = region
    keep = bytearray(w * h)
    for i in best:
        keep[i] = 1
    return keep


def to_icon(data: bytes, size: int = 512, bright: int = 140, gray: int = 48) -> "Image.Image":
    """Cut the subject out of a render on a light, plain-ish background (gradients, floor reflections
    and soft shadows included): background = bright, low-saturation pixels connected to the image edge.
    Keep the largest remaining object, crop, pad to a square with a small margin, scale to `size`."""
    from collections import deque

    from PIL import Image, ImageFilter
    try:  # a proper segmentation model does better than heuristics — use it when the user has it
        from rembg import remove as _rembg
    except ImportError:
        _rembg = None
    if _rembg is not None:
        with Image.open(io.BytesIO(_rembg(data))) as cut:
            rgba = cut.convert("RGBA")
        rgba.thumbnail((size, size))
        return _square(rgba, size)
    with Image.open(io.BytesIO(data)) as src:
        im = src.convert("RGB")
    im.thumbnail((size, size))
    w, h = im.size
    hsv = im.convert("HSV").tobytes()
    border = [*range(w), *range((h - 1) * w, h * w), *range(0, h * w, w), *range(w - 1, h * w, w)]
    vb = sorted(hsv[3 * i + 2] for i in border)[len(border) // 2]  # background tone from the edges
    if vb >= bright:   # light backdrop (incl. gradients, reflections, soft shadows)
        cand = bytearray(1 if hsv[3 * i + 2] > bright and hsv[3 * i + 1] < gray else 0 for i in range(w * h))
    else:              # dark/mid backdrop: pixels close to the edge tone
        cand = bytearray(1 if abs(hsv[3 * i + 2] - vb) < 34 and hsv[3 * i + 1] < gray else 0 for i in range(w * h))
    bg = bytearray(w * h)
    q = deque(i for i in border if cand[i])
    for i in q:
        bg[i] = 1
    while q:
        i = q.popleft()
        x, y = i % w, i // w
        for j in (i - 1 if x else -1, i + 1 if x < w - 1 else -1, i - w if y else -1, i + w if y < h - 1 else -1):
            if j >= 0 and cand[j] and not bg[j]:
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
