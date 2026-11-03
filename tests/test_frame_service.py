"""Frame service, pure parts (no browser): only /frame?view=<views.yaml name> is served; noise keeps the frame."""

import importlib.util
import io
from pathlib import Path

from PIL import Image, ImageStat

FS = Path(__file__).parents[1] / "plants" / "frame_service"
spec = importlib.util.spec_from_file_location("frame_server", FS / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def test_only_named_views_are_served():
    views = server.load_views(FS / "views.yaml")
    assert "default" in views
    assert server.route("/frame?view=default", views) == "default"
    for bad in ("/frame?view=nope", "/frame", "/frame?view=default&url=http://x", "/frame?view=default&view=default",
                "/data/index.php", "/frame/../data?view=default", "/?view=default", "/frame?url=http://simulation/"):
        assert server.route(bad, views) is None, bad


def test_noise_keeps_size_and_format_and_stays_light():
    img = Image.new("RGB", (320, 200), (120, 60, 200))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    out = Image.open(io.BytesIO(server.encode(buf.getvalue())))
    assert out.format == "JPEG" and out.size == (320, 200) and out.mode == "RGB"
    diff = [abs(a - b) for a, b in zip(ImageStat.Stat(out).mean, (120, 60, 200), strict=True)]
    assert max(diff) < 3  # zero-mean noise
    sd = ImageStat.Stat(server.add_noise(img)).stddev  # before JPEG, which smooths part of it away
    assert all(2.5 < s < 3.5 for s in sd)  # sigma 3 grey levels per channel
