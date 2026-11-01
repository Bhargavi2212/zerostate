"""Eval only: read P1 ground truth from the GRFICS web API on the host (GET has no delay)."""

import json
import urllib.request

URL = "http://localhost/data/index.php"


def read(timeout: float = 3.0) -> dict:
    with urllib.request.urlopen(URL, timeout=timeout) as r:
        return json.loads(r.read())
