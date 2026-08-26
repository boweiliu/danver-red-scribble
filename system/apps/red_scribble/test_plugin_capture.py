"""End-to-end capture through a real browser: draw on a scrolled page, check what is recorded.

This is the one property no unit test can reach. Everything the plug-in draws with is in
*viewport* coordinates, but the screenshot it sends alongside is of the whole *document*, so a
scribble drawn on a scrolled page is recorded at the wrong place unless
``plugin.js::toDocumentSpace`` converts it. The failure is silent -- the marks simply land on the
wrong lines -- which is exactly why it belongs in the suite rather than in someone's memory of
having checked it once.

The scenario is the one that was verified by hand: a page scrolled 200px, a stroke drawn at
viewport y=300, recorded at document y=500.

It runs against the real service (``create_app``) from a real second origin, so the CORS
boundary, the cookie-free simple-request POST, and origin-derived provenance are all exercised
for real rather than simulated. Both origins are ``*.localhost`` names, which Chromium resolves to
loopback, so the browser sees two genuinely different workspace origins on one machine. The
browser, the two servers, and the registry that makes them siblings are assembled by the
``scribbling_page`` fixture in this app's ``conftest.py``.
"""

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page

from imbue.mngr.utils.polling import poll_for_value
from red_scribble_service.testing import FORTRESS_CHROMIUM_PATH
from red_scribble_service.testing import Deliveries

_SCROLL_Y = 200
_DRAW_VIEWPORT_Y = 300
_EXPECTED_DOCUMENT_Y = _SCROLL_Y + _DRAW_VIEWPORT_Y

pytestmark = pytest.mark.skipif(
    not FORTRESS_CHROMIUM_PATH.exists(),
    reason="the workspace Chromium is not installed",
)


def _draw_horizontal_stroke(page: Page, viewport_y: int) -> None:
    """One freehand stroke across the capture overlay, as a pointing device would make it."""
    page.mouse.move(200, viewport_y)
    page.mouse.down()
    for x in (240, 280, 320):
        page.mouse.move(x, viewport_y)
    page.mouse.up()


@pytest.mark.timeout(180)
def test_a_stroke_on_a_scrolled_page_is_recorded_in_document_space(
    scribbling_page: Page, storage_dir: Path
) -> None:
    """Drawn at viewport y=300 on a page scrolled 200px, it must be recorded at document y=500.

    Recorded as viewport coordinates it would read 300, and every mark would sit 200px above what
    the accompanying full-document screenshot shows.
    """
    page = scribbling_page
    page.evaluate(f"window.scrollTo(0, {_SCROLL_Y})")
    page.wait_for_function(f"() => window.scrollY === {_SCROLL_Y}")
    page.click("div[title='Red Scribble']")

    _draw_horizontal_stroke(page, _DRAW_VIEWPORT_Y)
    packets = _wait_for_packets(storage_dir)

    stroke = next(packet for packet in packets if packet["kind"] == "stroke")
    recorded_ys = {point["y"] for point in stroke["strokes"][0]}
    assert recorded_ys == {_EXPECTED_DOCUMENT_Y}
    assert stroke["point"]["y"] == _EXPECTED_DOCUMENT_Y
    assert stroke["device_pixel_ratio"] >= 1


@pytest.mark.timeout(180)
def test_the_horizontal_axis_is_converted_by_the_same_rule(
    scribbling_page: Page, storage_dir: Path
) -> None:
    """An unscrolled axis must be left alone, or the fix would trade one offset for another."""
    page = scribbling_page
    page.evaluate(f"window.scrollTo(0, {_SCROLL_Y})")
    page.wait_for_function(f"() => window.scrollY === {_SCROLL_Y}")
    page.click("div[title='Red Scribble']")

    _draw_horizontal_stroke(page, _DRAW_VIEWPORT_Y)
    packets = _wait_for_packets(storage_dir)

    stroke = next(packet for packet in packets if packet["kind"] == "stroke")
    assert [point["x"] for point in stroke["strokes"][0]] == [200, 240, 280, 320]


@pytest.mark.timeout(180)
def test_the_stroke_reaches_the_target_chat_credited_to_the_app_it_was_drawn_on(
    scribbling_page: Page, storage_dir: Path, deliveries: Deliveries
) -> None:
    """The whole delivery path from a real cross-origin browser, not just the arithmetic.

    The POST is a CORS "simple request" from a different origin than the service, and the app name
    is resolved from that origin through the registry -- so a green result here means the trust
    boundary admits a genuine sibling and the packet is credited without the page claiming it.
    """
    page = scribbling_page
    page.click("div[title='Red Scribble']")

    _draw_horizontal_stroke(page, _DRAW_VIEWPORT_Y)
    agent_id, message = _wait_for_delivery(deliveries)

    assert agent_id == "agent-1"
    assert 'app="scribble-box"' in message


def _wait_for_packets(storage_dir: Path, timeout_seconds: float = 30.0) -> list[dict[str, object]]:
    """Every packet the service has persisted, once at least one has landed.

    Live mode gathers for a couple of seconds before sending, and the send captures a screenshot
    first, so the wait is for the file to appear rather than for a fixed delay.
    """
    packets_dir = storage_dir / "packets"

    def persisted() -> list[dict[str, object]] | None:
        files = sorted(packets_dir.glob("*.json")) if packets_dir.is_dir() else []
        return [json.loads(path.read_text()) for path in files] if files else None

    packets, _, _ = poll_for_value(persisted, timeout=timeout_seconds, poll_interval=0.2)
    assert packets is not None, f"no feedback packet was persisted under {packets_dir} in {timeout_seconds}s"
    return packets


def _wait_for_delivery(deliveries: Deliveries, timeout_seconds: float = 30.0) -> tuple[str, str]:
    """The first ``(agent id, message)`` the service hands a chat.

    Waiting on the persisted packet instead would be waiting on the wrong thing: the dispatcher
    saves every packet before it calls ``deliver``, and the handler runs on the server's own
    thread, so the file can exist while nothing has been delivered yet.
    """
    delivered, _, _ = poll_for_value(
        lambda: deliveries.sent[0] if deliveries.sent else None,
        timeout=timeout_seconds,
        poll_interval=0.2,
    )
    assert delivered is not None, f"nothing was delivered to a chat in {timeout_seconds}s"
    return delivered
