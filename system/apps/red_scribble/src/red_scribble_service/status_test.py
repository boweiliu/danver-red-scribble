"""Unit tests for the status page's view of the scribble registry."""

import json
from pathlib import Path

from red_scribble import store
from red_scribble_service.status import build_status_view
from red_scribble_service.status import build_stroke_thumbnail


def test_a_scribble_is_drawn_back_from_the_vectors_that_were_captured() -> None:
    thumbnail = build_stroke_thumbnail([[(10.0, 20.0), (30.0, 60.0)], [(15.0, 25.0), (18.0, 22.0)]])

    assert thumbnail.path == "M 10.0 20.0 L 30.0 60.0 M 15.0 25.0 L 18.0 22.0"
    # The box fits the strokes with a little air, in the strokes' own coordinate space.
    assert thumbnail.viewbox == "6.8 16.8 26.4 46.4"
    assert float(thumbnail.width) > 0


def test_a_perfectly_straight_stroke_still_gets_a_usable_box() -> None:
    thumbnail = build_stroke_thumbnail([[(10.0, 20.0), (60.0, 20.0)]])

    _x, _y, width, height = (float(part) for part in thumbnail.viewbox.split())
    assert width > 0
    assert height > 0


def test_there_is_nothing_to_draw_for_a_note() -> None:
    assert build_stroke_thumbnail([]).path == ""


def test_every_scribble_links_to_the_raw_packet_it_came_from(tmp_path: Path) -> None:
    packets_dir = tmp_path / "packets"
    packets_dir.mkdir()
    (packets_dir / "fbk-abc123.json").write_text(json.dumps({"kind": "text", "text": "bigger"}))
    (packets_dir / "fbk-abc123.png").write_bytes(b"not really a png")
    (packets_dir / "fbk-abc123-0.json").write_text("{}")
    store.register(tmp_path, "fbk-abc123", "text", "scribble-box", "http://x/")

    view = build_status_view(tmp_path, "agent-1", "my chat", "batch")

    assert view.is_on
    assert view.open_count == 1
    row = view.scribbles[0]
    assert row.text == "bigger"
    assert row.raw_href == "/raw/fbk-abc123.json"
    assert row.screenshot_href == ""


def test_a_scribble_whose_packet_is_unreadable_still_lists(tmp_path: Path) -> None:
    """The registry is the index; a missing or corrupt packet must not blank the whole page."""
    (tmp_path / "packets").mkdir()
    (tmp_path / "packets" / "fbk-broken1.json").write_text("{not json")
    store.register(tmp_path, "fbk-broken1", "stroke", "scribble-box", "http://x/")

    view = build_status_view(tmp_path, None, "", "batch")

    assert not view.is_on
    assert [row.id for row in view.scribbles] == ["fbk-broken1"]
    assert view.scribbles[0].text == ""


def test_closed_scribbles_are_listed_but_not_counted_as_open(tmp_path: Path) -> None:
    (tmp_path / "packets").mkdir()
    store.register(tmp_path, "fbk-one1", "text", "scribble-box", "http://x/")
    store.register(tmp_path, "fbk-two2", "text", "scribble-box", "http://x/")
    store.close(tmp_path, ["fbk-one1"])

    view = build_status_view(tmp_path, "agent-1", "my chat", "batch")

    assert view.total_count == 2
    assert view.open_count == 1
    assert {row.id: row.is_closed for row in view.scribbles} == {"fbk-one1": True, "fbk-two2": False}
