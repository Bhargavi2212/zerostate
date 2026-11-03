"""Fetches one frame from the frame service (zs-frames, 172.30.0.3:8080 on the internal network). The
service serves frames only, never plant data. No proxy: the opener ignores the environment's proxy settings."""

import os
import time
import urllib.parse
import urllib.request

DEFAULT_URL = "http://172.30.0.3:8080"


def fetch_frame(view: str, base: str | None = None, timeout: float = 10.0, opener=None) -> tuple[bytes, float]:
    """(JPEG bytes, capture time in epoch s). The capture time is the service's X-Capture-Time header (same
    Docker VM clock as ZeroState's own timestamps); the fetch time if the header is missing."""
    base = (base or os.environ.get("ZS_FRAMES_URL") or DEFAULT_URL).rstrip("/")
    url = f"{base}/frame?{urllib.parse.urlencode({'view': view})}"
    op = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
    t = time.time()
    with op.open(url, timeout=timeout) as r:
        data = r.read()
        try:
            t = float(r.headers.get("X-Capture-Time") or t)
        except ValueError:
            pass
    return data, t
