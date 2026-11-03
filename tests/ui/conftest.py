"""Playwright fixtures for the console (marker `ui`): the fixture server on a free localhost port with a
throwaway data dir, and one headless Chromium. Confirm and sign are submitted only here, as playwright-test."""

import os
import shutil
import socket
import threading
import time

import pytest
import uvicorn
from fake_api import ROOT, make_app
from playwright.sync_api import sync_playwright

from zerostate.config import load_thresholds


@pytest.fixture(scope="session")
def ui_server(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("zs-ui-test")
    data, config = tmp / "data", tmp / "config"
    data.mkdir()
    for plant in ("p1_grfics", "p2_gasline"):
        (config / plant).mkdir(parents=True)
        shutil.copy(ROOT / "plants" / plant / "plant_map.yaml", config / plant)
    saved = {k: os.environ.get(k) for k in ("MODEL_API_KEY", "ZS_CREDITS")}
    os.environ["MODEL_API_KEY"] = "fake-key-for-tests"  # pragma: allowlist secret
    os.environ["ZS_CREDITS"] = str(tmp / "credits.jsonl")
    app = make_app(data, config, load_thresholds(ROOT / "plants/p2_gasline/thresholds.yaml"))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", data
    srv.should_exit = True
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser, ui_server):
    ctx = browser.new_context()
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    yield pg
    ctx.close()
    assert not errors, errors
