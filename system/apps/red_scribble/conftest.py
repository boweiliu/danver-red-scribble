"""Fixtures for this app's tests: a delivery recorder, throwaway storage, and a scribbling browser.

The pieces they assemble -- the two workspace origins, the registry that makes them siblings, the
delivery recorder, and the loopback server -- live in ``red_scribble_service.testing``.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Page
from playwright.sync_api import sync_playwright

from red_scribble.config import RedScribbleConfig
from red_scribble.config import save_config
from red_scribble.dispatch import AgentSummary
from red_scribble.dispatch import RedScribbleDeps
from red_scribble.origins import ENV_APPS_FILE
from red_scribble_service.runner import ASSETS_DIR
from red_scribble_service.runner import create_app
from red_scribble_service.testing import APP_LABEL
from red_scribble_service.testing import FORTRESS_CHROMIUM_PATH
from red_scribble_service.testing import SERVICE_LABEL
from red_scribble_service.testing import WORKSPACE_REGISTRY
from red_scribble_service.testing import Deliveries
from red_scribble_service.testing import Server
from red_scribble_service.testing import StartResponse

# The page the browser tests scribble on: tall enough that 200px of scroll is real, and blank
# enough that html2canvas finishes fast. It embeds Red Scribble the way an opted-in app does.
_PAGE = """<!doctype html>
<html><head><title>Scroll target</title></head>
<body style="margin:0">
<div id="ruler" style="height:3000px;background:linear-gradient(#fff,#eee)"></div>
<script src="%s/plugin.js"></script>
</body></html>
"""


@pytest.fixture(name="deliveries")
def fixture_deliveries() -> Deliveries:
    return Deliveries()


@pytest.fixture(name="storage_dir")
def fixture_storage_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Throwaway storage plus a registry naming both origins the browser tests serve from."""
    registry_path = tmp_path / "apps.toml"
    registry_path.write_text(WORKSPACE_REGISTRY)
    monkeypatch.setenv(ENV_APPS_FILE, str(registry_path))
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    # Live mode so a drawn stroke sends itself, rather than needing the long-press menu driven.
    save_config(RedScribbleConfig(target_agent_id="agent-1", mode="live"), storage_dir / "config.json")
    return storage_dir


@pytest.fixture(name="scribbling_page")
def fixture_scribbling_page(storage_dir: Path, deliveries: Deliveries) -> Iterator[Page]:
    """A browser on an app page that has embedded the real Red Scribble service, cross-origin."""
    deps = RedScribbleDeps(
        assets_dir=ASSETS_DIR,
        storage_dir=storage_dir,
        list_agents=lambda: (AgentSummary("agent-1", "chat", "running"),),
        deliver=deliveries.deliver,
    )
    service = Server(create_app(deps))
    service_origin = service.origin(SERVICE_LABEL)
    page_body = (_PAGE % service_origin).encode()

    def app_page(environ: dict[str, object], start_response: StartResponse) -> list[bytes]:
        headers = [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(page_body)))]
        start_response("200 OK", headers)
        return [page_body]

    app = Server(app_page)
    # Both servers are already listening, so every path out of here -- including the plug-in
    # failing to load, which is the failure this test exists to catch -- has to take them down.
    # Browser first, then the page server, then the service it was talking to.
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=str(FORTRESS_CHROMIUM_PATH), args=["--no-sandbox"]
            )
            try:
                page = browser.new_page(viewport={"width": 1000, "height": 800})
                page.goto(app.origin(APP_LABEL) + "/")
                page.wait_for_function("() => window.__RED_SCRIBBLE_LOADED__ === true")
                yield page
            finally:
                browser.close()
    finally:
        app.shutdown()
        service.shutdown()
