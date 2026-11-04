"""zs-frames: the camera for P1. Headless Chromium (Playwright) keeps the simulator's 3D page open and
serves one thing only:

    GET /frame?view=<name>   -> JPEG (quality 70, Gaussian noise sigma 3 grey levels), X-Capture-Time header

<name> must be a key of views.yaml; any other path, query or view is 404. No free URL, no plant data.

On P1 the page renders the simulator's true state, so this is an idealised camera, and it is labelled so.
For eval only, when /truth exists (the zs-frames-truth volume, which ZeroState never mounts), every capture
also writes a truth sidecar fetched from the simulator at the same moment: /truth/<capture id>.json.
"""

import io
import json
import os
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import yaml
from PIL import Image, ImageChops

HERE = Path(__file__).parent
SIM = os.environ.get("ZS_SIM_URL", "http://simulation")
TRUTH_DIR = Path(os.environ.get("ZS_TRUTH_DIR", "/truth"))
JPEG_QUALITY, NOISE_SIGMA = 70, 3


def load_views(path: Path = HERE / "views.yaml") -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def route(path: str, views: dict) -> str | None:
    """The view name for an allowed request, else None (-> 404). Only /frame?view=<views.yaml key>."""
    u = urllib.parse.urlsplit(path)
    q = urllib.parse.parse_qs(u.query, keep_blank_values=True)
    if u.path != "/frame" or set(q) != {"view"} or len(q["view"]) != 1:
        return None
    name = q["view"][0]
    return name if name in views else None


def add_noise(img: Image.Image, sigma: float = NOISE_SIGMA) -> Image.Image:
    """Independent Gaussian noise per channel (Pillow only): effect_noise is centred on 128."""
    rgb = img.convert("RGB")
    noise = [Image.effect_noise(rgb.size, sigma) for _ in range(3)]
    return ImageChops.add(rgb, Image.merge("RGB", noise), scale=1.0, offset=-128)


def encode(png: bytes) -> bytes:
    buf = io.BytesIO()
    add_noise(Image.open(io.BytesIO(png))).save(buf, "JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()


class Camera:
    """One persistent page per view. Playwright's sync API is bound to the thread that started it, so the server
    is single-threaded and captures are serialised."""

    def __init__(self, views: dict):
        from playwright.sync_api import sync_playwright  # only in the container image

        self.views, self.pages = views, {}
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])

    def _page(self, name: str):
        if name not in self.pages:
            v = self.views[name]
            w, h = v.get("viewport", [1280, 720])
            page = self.browser.new_page(viewport={"width": w, "height": h})
            page.goto(v.get("url", f"{SIM}/"))
            page.wait_for_timeout(int(v.get("load_wait_s", 20) * 1000))
            for act in v.get("actions", []):  # scripted key/mouse sequence that frames the displays
                if "press" in act:
                    page.keyboard.press(act["press"], delay=act.get("hold_ms", 0))
                elif "click" in act:
                    page.mouse.click(*act["click"])
                elif "drag" in act:
                    (x1, y1), (x2, y2) = act["drag"]
                    page.mouse.move(x1, y1)
                    page.mouse.down()
                    page.mouse.move(x2, y2, steps=10)
                    page.mouse.up()
                if "wait_ms" in act:
                    page.wait_for_timeout(act["wait_ms"])
            self.pages[name] = page
        return self.pages[name]

    def capture(self, name: str) -> tuple[bytes, float, str]:
        t0 = time.time()
        png = self._page(name).screenshot(type="png")
        t = (t0 + time.time()) / 2  # the screenshot takes a moment under software GL: stamp its middle
        cid = f"{t:.3f}-{name}"
        if TRUTH_DIR.is_dir():  # eval only: the volume ZeroState never mounts
            write_sidecar(cid, name, t)
        return encode(png), t, cid


def write_sidecar(cid: str, view: str, t: float) -> None:
    try:
        with urllib.request.urlopen(f"{SIM}/data/index.php", timeout=2) as r:
            truth, err = json.loads(r.read()), None
    except Exception as e:  # noqa: BLE001 - a missing label is recorded, the frame is still served
        truth, err = None, f"{type(e).__name__}: {e}"
    (TRUTH_DIR / f"{cid}.json").write_text(json.dumps({"capture_id": cid, "view": view, "capture_time": t,
                                                       "truth_time": time.time(), "truth": truth, "error": err}))


def main() -> None:
    views = load_views()
    cam = Camera(views)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            name = route(self.path, views)
            if name is None:
                self.send_error(404)
                return
            body, t, cid = cam.capture(name)
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Capture-Time", f"{t:.3f}")
            self.send_header("X-Capture-Id", cid)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # quiet: one line per frame is noise
            pass

    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()


if __name__ == "__main__":
    main()
