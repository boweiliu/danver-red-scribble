"""The status page's view of the scribble registry, including each scribble's raw packet.

The page exists so the raw record is never out of reach: every scribble links to the exact JSON
packet that was delivered, plus the screenshot and voice audio stored beside it. The stroke
thumbnail is that same raw vector data, drawn back at thumbnail size -- a derived view that
cannot drift from what was captured, because it *is* what was captured.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from typing import Final

from pydantic import Field

from imbue.imbue_common.frozen_model import FrozenModel
from imbue.imbue_common.pure import pure

from red_scribble import store

# Only the most recent scribbles are rendered: the page is a glance at what feedback is
# outstanding, and every packet stays on disk regardless.
MAX_RENDERED_SCRIBBLES: Final[int] = 50

# The thumbnail is drawn in the stroke's own coordinate space, so the pen must scale with the
# scribble: a thin fraction of its longest side, floored so a tiny flick is still visible.
_STROKE_WIDTH_FRACTION: Final[float] = 0.03
_MIN_STROKE_WIDTH: Final[float] = 1.5
_THUMBNAIL_PADDING_FRACTION: Final[float] = 0.08

# Raw attachment filenames are ``<packet id>.<ext>`` or ``<packet id>-<n>.<ext>``; the viewer
# route accepts nothing else, so the packets directory cannot be walked out of.
RAW_FILENAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^fbk-[a-z0-9]+(-\d+)?\.(json|png|wav)$")


class ScribbleRow(FrozenModel):
    """One scribble as the status page renders it."""

    id: str = Field(description="The stable packet id")
    kind: str = Field(description="stroke | text | voice")
    app: str = Field(description="The app the scribble was drawn on")
    created_at: str = Field(description="When it landed, as a short UTC stamp")
    is_closed: bool = Field(description="Whether the agent has closed it")
    text: str = Field(description="The typed note or voice transcript, empty for a stroke")
    stroke_path: str = Field(description="SVG path data for the thumbnail, empty for a note")
    stroke_viewbox: str = Field(description="The thumbnail's viewBox in the stroke's own space")
    stroke_width: str = Field(description="Pen width in the stroke's own coordinate space")
    raw_href: str = Field(description="Link to the raw packet JSON, empty when it is missing")
    screenshot_href: str = Field(description="Link to the send's screenshot, empty when there is none")
    audio_hrefs: tuple[str, ...] = Field(description="Links to any captured voice audio")


class StatusView(FrozenModel):
    """Everything the status page shows."""

    is_on: bool = Field(description="Whether feedback currently has somewhere to go")
    target_name: str = Field(description="The chat feedback routes to, by name where known")
    mode: str = Field(description="live | batch")
    open_count: int = Field(description="Scribbles the agent has not closed yet")
    total_count: int = Field(description="Every scribble ever registered")
    scribbles: tuple[ScribbleRow, ...] = Field(description="The most recent scribbles, newest first")


@pure
def _short_timestamp(raw_timestamp: str) -> str:
    try:
        parsed = datetime.fromisoformat(raw_timestamp)
    except ValueError:
        return raw_timestamp
    return parsed.strftime("%Y-%m-%d %H:%M")


def _read_packet(packets_dir: Path, packet_id: str) -> dict[str, Any]:
    packet_file = packets_dir / f"{packet_id}.json"
    try:
        record = json.loads(packet_file.read_text())
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


@pure
def _stroke_points(packet: dict[str, Any]) -> list[list[tuple[float, float]]]:
    """Every stroke in a packet as lists of (x, y), skipping anything malformed."""
    raw_strokes = packet.get("strokes")
    if not isinstance(raw_strokes, list):
        return []
    strokes: list[list[tuple[float, float]]] = []
    for raw_stroke in raw_strokes:
        if not isinstance(raw_stroke, list):
            continue
        points = [
            (float(point["x"]), float(point["y"]))
            for point in raw_stroke
            if isinstance(point, dict) and isinstance(point.get("x"), (int, float)) and isinstance(point.get("y"), (int, float))
        ]
        if len(points) > 1:
            strokes.append(points)
    return strokes


class StrokeThumbnail(FrozenModel):
    """A scribble's stroke data, ready to drop into an inline SVG."""

    path: str = Field(description="SVG path data, empty when there is nothing to draw")
    viewbox: str = Field(description="The box that fits the strokes, with a little air")
    width: str = Field(description="Pen width in the same coordinate space")


@pure
def build_stroke_thumbnail(strokes: list[list[tuple[float, float]]]) -> StrokeThumbnail:
    """Draw the captured vectors at whatever size the page gives them."""
    if not strokes:
        return StrokeThumbnail(path="", viewbox="0 0 1 1", width="1")

    all_x = [x for stroke in strokes for x, _y in stroke]
    all_y = [y for stroke in strokes for _x, y in stroke]
    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)
    # A perfectly straight stroke has zero extent on one axis; give it a sliver so the viewBox
    # stays valid and the line still lands inside it.
    span = max(max_x - min_x, max_y - min_y, 1.0)
    padding = span * _THUMBNAIL_PADDING_FRACTION
    box_x = min_x - padding
    box_y = min_y - padding
    box_width = max(max_x - min_x, 1.0) + padding * 2
    box_height = max(max_y - min_y, 1.0) + padding * 2

    segments = [
        "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in stroke)
        for stroke in strokes
    ]
    pen_width = max(span * _STROKE_WIDTH_FRACTION, _MIN_STROKE_WIDTH)
    return StrokeThumbnail(
        path=" ".join(segments),
        viewbox=f"{box_x:.1f} {box_y:.1f} {box_width:.1f} {box_height:.1f}",
        width=f"{pen_width:.1f}",
    )


@pure
def _attachment_names(packet: dict[str, Any], field: str) -> tuple[str, ...]:
    value = packet.get(field)
    if isinstance(value, str) and value:
        return (value,)
    if isinstance(value, list):
        return tuple(name for name in value if isinstance(name, str) and name)
    return ()


def _row(scribble: store.Scribble, packets_dir: Path) -> ScribbleRow:
    packet = _read_packet(packets_dir, scribble.id)
    thumbnail = build_stroke_thumbnail(_stroke_points(packet))
    note = packet.get("text") or packet.get("transcript") or ""
    screenshots = _attachment_names(packet, "screenshot")
    raw_file = packets_dir / f"{scribble.id}.json"
    return ScribbleRow(
        id=scribble.id,
        kind=scribble.kind or "scribble",
        app=scribble.app,
        created_at=_short_timestamp(scribble.created_at),
        is_closed=scribble.status == "closed",
        text=str(note),
        stroke_path=thumbnail.path,
        stroke_viewbox=thumbnail.viewbox,
        stroke_width=thumbnail.width,
        raw_href=f"/raw/{scribble.id}.json" if raw_file.is_file() else "",
        screenshot_href=f"/raw/{screenshots[0]}" if screenshots else "",
        audio_hrefs=tuple(f"/raw/{name}" for name in _attachment_names(packet, "audio")),
    )


def build_status_view(storage_dir: Path, target_agent_id: str | None, target_name: str, mode: str) -> StatusView:
    """Assemble the status page's data from the config and the scribble registry."""
    scribbles = store.list_scribbles(storage_dir)
    packets_dir = storage_dir / "packets"
    newest_first = list(reversed(scribbles))[:MAX_RENDERED_SCRIBBLES]
    return StatusView(
        is_on=target_agent_id is not None,
        target_name=target_name,
        mode=mode,
        open_count=sum(1 for scribble in scribbles if scribble.status != "closed"),
        total_count=len(scribbles),
        scribbles=tuple(_row(scribble, packets_dir) for scribble in newest_first),
    )
