"""Framework-neutral routing for Red Scribble's HTTP endpoints.

The host -- ``system/apps/red_scribble/``, a thin Flask adapter -- calls :func:`route` with the
request's sub-path (``plugin.js``, ``config``, ``feedback``, ...), the HTTP method, the raw body,
and the app the request came from. The parts only the host can do -- messaging an agent, listing
agents, and deciding which origins may call at all -- are injected as callbacks or handled by the
host (:class:`RedScribbleDeps`), so this module has no dependency on mngr or on any web framework
and is unit-testable with fakes. Its own config file lives under ``storage_dir`` and is
read/written directly.

Routes:
- ``GET config``     -> the plug-in's live config (enabled/target/mode) plus the agent list for
  the long-press menu.
- ``GET <asset>``    -> a served front-end asset (the plug-in and its voice modules), allowlisted.
- ``POST feedback``  -> ingest one send operation's envelope of scribbles: persist each raw packet
  durably, then hand ONE distilled, mode-aware message (covering every scribble in the envelope)
  to the target agent in a single ``deliver`` call.

Terminology: a *scribble* is one user-entered feedback item -- a freehand stroke group, a text
entry, or a voice note (``kind``: ``stroke | text | voice``).
"""

import base64
import json
from collections.abc import Callable
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import Final
from typing import NamedTuple
from xml.sax.saxutils import escape
from xml.sax.saxutils import quoteattr

from imbue.imbue_common.frozen_model import FrozenModel
from imbue.imbue_common.ids import RandomId

from red_scribble import store
from red_scribble.config import CONFIG_FILENAME
from red_scribble.config import RedScribbleConfig
from red_scribble.config import load_config
from red_scribble.config import save_config

_JSON = "application/json"
# The charset is explicit because a served asset may be vendored third-party code with
# non-ASCII bytes in it; without it, the browser would fall back to the embedding page's
# charset and could corrupt them.
_JS = "application/javascript; charset=utf-8"


class PacketId(RandomId):
    """Unique identifier for a stored feedback packet."""

    PREFIX = "fbk"


class AgentSummary(NamedTuple):
    """One agent as shown in the plug-in's target-agent menu."""

    id: str
    name: str
    state: str


class RedScribbleDeps(NamedTuple):
    """The host boundary: where files live, plus the two things only the host can do."""

    assets_dir: Path
    storage_dir: Path
    list_agents: Callable[[], tuple[AgentSummary, ...]]
    deliver: Callable[[str, str], bool]


def _config_path(deps: RedScribbleDeps) -> Path:
    return deps.storage_dir / CONFIG_FILENAME


class HandlerResponse(FrozenModel):
    """A framework-neutral HTTP response the host adapts to its own Response type."""

    status_code: int
    content_type: str
    body: bytes


def _json_response(payload: dict[str, Any], status_code: int = 200) -> HandlerResponse:
    return HandlerResponse(
        status_code=status_code,
        content_type=_JSON,
        body=json.dumps(payload).encode(),
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _handle_config(deps: RedScribbleDeps) -> HandlerResponse:
    cfg = load_config(_config_path(deps))
    agents = [{"id": a.id, "name": a.name, "state": a.state} for a in deps.list_agents()]
    return _json_response(
        {
            "enabled": cfg.enabled,
            "target_agent_id": cfg.target_agent_id,
            "mode": cfg.mode,
            "agents": agents,
        }
    )


def _handle_config_update(deps: RedScribbleDeps, body: bytes) -> HandlerResponse:
    """Apply a partial config change from the plug-in's menu (delivery mode and/or target agent)."""
    try:
        patch = json.loads(body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return _json_response({"detail": "Invalid JSON in config body"}, status_code=400)
    if not isinstance(patch, dict):
        return _json_response({"detail": "Config body must be a JSON object"}, status_code=400)

    updates: dict[str, Any] = {}
    mode = patch.get("mode")
    if mode in ("live", "batch"):
        updates["mode"] = mode
    if "target_agent_id" in patch:
        target = patch["target_agent_id"]
        if target is None or isinstance(target, str):
            updates["target_agent_id"] = target

    path = _config_path(deps)
    updated = load_config(path).model_copy(update=updates)
    save_config(updated, path)
    return _handle_config(deps)


# The front-end assets the dispatcher will serve. An allowlist (rather than serving anything
# under assets_dir) keeps the route from becoming a file-read surface into the package.
# html2canvas is vendored rather than pulled from a public CDN, so an adopted template has no
# network dependency at adoption time. Public: these are exactly the requests a host answers
# without an Origin, because a classic ``<script src>`` sends none.
SERVED_ASSETS: Final[frozenset[str]] = frozenset(
    {"plugin.js", "voice_session.js", "voice_capture.js", "html2canvas.js"}
)


def _handle_asset(deps: RedScribbleDeps, name: str) -> HandlerResponse:
    if name not in SERVED_ASSETS:
        return _json_response({"detail": f"Unknown asset: {name}"}, status_code=404)
    asset_path = deps.assets_dir / name
    if not asset_path.is_file():
        return _json_response({"detail": f"{name} not found"}, status_code=404)
    return HandlerResponse(status_code=200, content_type=_JS, body=asset_path.read_bytes())


def _externalize_binary(
    record: dict[str, Any],
    packets_dir: Path,
    packet_id: PacketId,
    field: str,
    ext: str,
    ref_field: str,
) -> None:
    """Move a base64 attachment out of the packet JSON into a sibling file, stored once.

    ``record[field]`` may be a single base64 string or a list of them. Each is decoded to
    ``<id>.<ext>`` (or ``<id>-<n>.<ext>`` for a list) -- the raw bytes in their native format -- and
    ``record[ref_field]`` is set to the filename(s). Anything that fails to decode is kept as its
    base64 under the original field, so nothing is ever discarded.
    """
    value = record.pop(field, None)
    if isinstance(value, str):
        items: list[Any] = [value]
    elif isinstance(value, list):
        items = value
    else:
        if value is not None:
            record[field] = value  # unexpected shape: leave it untouched
        return

    refs: list[str] = []
    kept: list[str] = []
    for idx, b64 in enumerate(items):
        if not isinstance(b64, str) or not b64:
            continue
        filename = f"{packet_id}.{ext}" if len(items) == 1 else f"{packet_id}-{idx}.{ext}"
        try:
            (packets_dir / filename).write_bytes(base64.b64decode(b64))
            refs.append(filename)
        except (ValueError, OSError):
            kept.append(b64)
    if refs:
        record[ref_field] = refs[0] if len(refs) == 1 else refs
    if kept:
        record[field] = kept[0] if len(kept) == 1 else kept


def save_packet(storage_dir: Path, app_name: str, packet: dict[str, Any]) -> tuple[PacketId, Path]:
    """Persist one feedback packet under ``storage_dir/packets/`` and return its id and path.

    Base64 binary attachments (a screenshot, voice WAV audio) are decoded to sibling files in their
    native format and replaced in the JSON by filename references, so each blob is stored once and
    the JSON stays small. Undecodable data is kept inline, so nothing is ever discarded.
    """
    packet_id = PacketId.generate()
    packets_dir = storage_dir / "packets"
    packets_dir.mkdir(parents=True, exist_ok=True)

    record = {"id": str(packet_id), "app": app_name, "received_at": _now().isoformat(), **packet}
    _externalize_binary(record, packets_dir, packet_id, "screenshot_png_base64", "png", "screenshot")
    _externalize_binary(record, packets_dir, packet_id, "audio_wav_base64", "wav", "audio")

    packet_file = packets_dir / f"{packet_id}.json"
    tmp_file = packet_file.with_suffix(".json.tmp")
    tmp_file.write_text(json.dumps(record, indent=2))
    tmp_file.replace(packet_file)
    return packet_id, packet_file


class SavedScribble(NamedTuple):
    """One persisted scribble: its raw packet, stable id, and raw-packet path."""

    packet: dict[str, Any]
    packet_id: PacketId
    raw_path: Path


def _scribble_tag(saved: SavedScribble) -> str:
    """One ``<scribble .../>`` element: metadata as attributes, the note text as content."""
    packet = saved.packet
    attrs: list[tuple[str, str]] = [("id", str(saved.packet_id))]
    kind = packet.get("kind")
    if kind:
        attrs.append(("kind", str(kind)))
    point = packet.get("point")
    if isinstance(point, dict) and "x" in point and "y" in point:
        attrs.append(("point", f"{point['x']},{point['y']}"))
    anchor = packet.get("anchor")
    if anchor:
        attrs.append(("anchor", str(anchor)))
    strokes = packet.get("strokes")
    if isinstance(strokes, list) and strokes:
        attrs.append(("strokes", str(len(strokes))))
    page_url = packet.get("page_url")
    if page_url:
        attrs.append(("page", str(page_url)))
    attrs.append(("raw", str(saved.raw_path)))

    attr_text = " ".join(f"{name}={quoteattr(value)}" for name, value in attrs)
    note = packet.get("text") or packet.get("transcript") or ""
    if note:
        return f"<scribble {attr_text}>{escape(str(note))}</scribble>"
    return f"<scribble {attr_text}/>"


def build_feedback_message(
    saved_scribbles: list[SavedScribble],
    config: RedScribbleConfig,
    app_name: str,
    screenshot_path: Path | None = None,
) -> str:
    """ONE tagged message enveloping every scribble in a send operation.

    A send operation (the live-mode debounce firing, or the user clicking Send Pending Scribbles) gathers one
    or more scribbles; they arrive as a single envelope and leave as this single
    ``<red-scribble-feedback>`` document, so the agent gets one turn's worth of context and
    ``deliver`` is called once per send. The tagged shape is a contract with the chat view's
    detector (which renders it as a batch card of scribble tiles) and stays legible to the agent:
    metadata rides in attributes, spoken/typed notes in element content. The full playbook -- how
    to act, when to WAIT on an unclear stroke, the live-mode branch workflow, and closing
    scribbles -- lives in the ``red-scribble-feedback`` skill.
    """
    root_attrs = [("mode", config.mode), ("app", app_name), ("count", str(len(saved_scribbles)))]
    if screenshot_path is not None:
        root_attrs.append(("screenshot", str(screenshot_path)))
    attr_text = " ".join(f"{name}={quoteattr(value)}" for name, value in root_attrs)
    lines = [
        f"<red-scribble-feedback {attr_text}>",
        "Act per the /red-scribble-feedback skill. Distill intent from the fields below"
        + (" before reaching for the shared screenshot (it is slow)." if screenshot_path else "."),
    ]
    lines.extend(_scribble_tag(saved) for saved in saved_scribbles)
    lines.append("</red-scribble-feedback>")
    return "\n".join(lines)


def _handle_feedback(deps: RedScribbleDeps, app_name: str, body: bytes) -> HandlerResponse:
    """Ingest one send operation's envelope: ``{"scribbles": [<packet>, ...]}``.

    Every scribble is persisted and registered individually (stable ids, closeable one by one),
    but the whole envelope becomes ONE message and ONE ``deliver`` call -- message delivery has
    real per-call latency, and the receiving agent does better with one gathered turn of context
    than a burst of fragments.
    """
    try:
        envelope = json.loads(body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return _json_response({"detail": "Invalid JSON in feedback body"}, status_code=400)
    packets = envelope.get("scribbles") if isinstance(envelope, dict) else None
    if not isinstance(packets, list) or not packets or not all(isinstance(p, dict) for p in packets):
        return _json_response(
            {"detail": "Feedback body must be {'scribbles': [<packet>, ...]} with at least one packet"},
            status_code=400,
        )

    # The envelope carries at most ONE screenshot (capturing is slow, so the plug-in takes one per
    # send). It rides in the first packet's record, whose save externalizes it to a single .png.
    envelope_screenshot = envelope.get("screenshot_png_base64")
    if isinstance(envelope_screenshot, str) and envelope_screenshot:
        packets[0] = {**packets[0], "screenshot_png_base64": envelope_screenshot}

    saved_scribbles: list[SavedScribble] = []
    for packet in packets:
        packet_id, raw_path = save_packet(deps.storage_dir, app_name, packet)
        store.register(
            deps.storage_dir,
            str(packet_id),
            str(packet.get("kind") or ""),
            app_name,
            str(packet.get("page_url") or ""),
        )
        saved_scribbles.append(SavedScribble(packet=packet, packet_id=packet_id, raw_path=raw_path))

    first = saved_scribbles[0]
    screenshot_file = first.raw_path.parent / f"{first.packet_id}.png"
    screenshot_path = screenshot_file if screenshot_file.is_file() else None

    cfg = load_config(_config_path(deps))
    delivered = False
    if cfg.target_agent_id:
        message = build_feedback_message(saved_scribbles, cfg, app_name, screenshot_path)
        delivered = deps.deliver(cfg.target_agent_id, message)

    return _json_response(
        {
            "status": "ok",
            "packet_ids": [str(saved.packet_id) for saved in saved_scribbles],
            "delivered": delivered,
        }
    )


def _handle_scribbles(deps: RedScribbleDeps) -> HandlerResponse:
    scribbles = store.list_scribbles(deps.storage_dir)
    return _json_response({"scribbles": [s.model_dump() for s in scribbles]})


def _handle_close(deps: RedScribbleDeps, body: bytes) -> HandlerResponse:
    """Close scribbles by id (the agent calls this after acting on them, so they stop rendering)."""
    try:
        payload = json.loads(body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return _json_response({"detail": "Invalid JSON in close body"}, status_code=400)
    ids = payload.get("ids") if isinstance(payload, dict) else None
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return _json_response({"detail": "'ids' must be a list of strings"}, status_code=400)
    return _json_response({"closed": store.close(deps.storage_dir, ids)})


def route(method: str, subpath: str, body: bytes, app_name: str, deps: RedScribbleDeps) -> HandlerResponse:
    """Route one Red Scribble request to its handler.

    ``subpath`` is the request path with its leading slash dropped (e.g. ``"config"``);
    ``app_name`` is the app the request came from, which the host resolves from the request's
    ``Origin`` -- provenance for the feedback packet that the page itself cannot forge.
    """
    if subpath == "config" and method == "GET":
        return _handle_config(deps)
    if subpath == "config" and method == "POST":
        return _handle_config_update(deps, body)
    if method == "GET" and subpath in SERVED_ASSETS:
        return _handle_asset(deps, subpath)
    if subpath == "feedback" and method == "POST":
        return _handle_feedback(deps, app_name, body)
    if subpath == "scribbles" and method == "GET":
        return _handle_scribbles(deps)
    if subpath == "close" and method == "POST":
        return _handle_close(deps, body)
    return _json_response({"detail": f"Unknown Red Scribble route: {method} {subpath}"}, status_code=404)
