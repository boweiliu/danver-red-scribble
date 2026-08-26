"""The Red Scribble scribble registry: the live index of user scribbles and their open/closed
status, kept separate from the durable raw packets (see :mod:`red_scribble.dispatch`).

A *scribble* is one user-entered feedback item -- a freehand stroke group, a text entry, or a
voice note. Every scribble is registered here with its stable packet id when it lands. After the
agent acts on a scribble it *closes* it (via the close endpoint or the ``red-scribble close``
CLI); the plug-in polls this registry and stops rendering closed scribbles. That is what makes
"draw an X on a button -> the agent deletes it and the X disappears" work.

The file is written atomically. An in-process lock guards the server's request threads; a separate
process (the CLI) is last-writer-wins, which is acceptable for this small live index.
"""

import json
import threading
from datetime import datetime
from datetime import timezone
from pathlib import Path

from imbue.imbue_common.frozen_model import FrozenModel
from pydantic import Field
from pydantic import ValidationError

from red_scribble.config import DEFAULT_STORAGE_DIR

SCRIBBLES_FILENAME = "scribbles.json"

_lock = threading.Lock()


class Scribble(FrozenModel):
    """One registered user scribble and whether it still renders."""

    id: str = Field(description="Stable id (the feedback packet id)")
    kind: str = Field(description="stroke | text | voice")
    app: str = Field(default="", description="The app the scribble came from")
    page_url: str = Field(default="")
    created_at: str = Field(default="")
    status: str = Field(default="open", description="open | closed")
    closed_at: str | None = Field(default=None)


def _scribbles_path(storage_dir: Path) -> Path:
    return storage_dir / SCRIBBLES_FILENAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(storage_dir: Path) -> list[Scribble]:
    path = _scribbles_path(storage_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError, ValueError):
        return []
    items = data.get("scribbles") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    result: list[Scribble] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            result.append(Scribble.model_validate(item))
        except ValidationError:
            continue  # skip a malformed row rather than fail the whole read
    return result


def _write(storage_dir: Path, scribbles: list[Scribble]) -> None:
    path = _scribbles_path(storage_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps({"scribbles": [s.model_dump() for s in scribbles]}, indent=2))
    tmp_path.replace(path)


def register(
    storage_dir: Path,
    scribble_id: str,
    kind: str,
    app: str = "",
    page_url: str = "",
) -> Scribble:
    """Record a new open scribble (idempotent on id) and persist."""
    with _lock:
        scribbles = [s for s in _read(storage_dir) if s.id != scribble_id]
        scribble = Scribble(id=scribble_id, kind=kind, app=app, page_url=page_url, created_at=_now())
        scribbles.append(scribble)
        _write(storage_dir, scribbles)
        return scribble


def close(storage_dir: Path, ids: list[str]) -> list[str]:
    """Mark the given scribble ids closed; return the ids actually closed (were open)."""
    id_set = set(ids)
    closed: list[str] = []
    with _lock:
        scribbles = _read(storage_dir)
        updated: list[Scribble] = []
        for scribble in scribbles:
            if scribble.id in id_set and scribble.status != "closed":
                updated.append(scribble.model_copy(update={"status": "closed", "closed_at": _now()}))
                closed.append(scribble.id)
            else:
                updated.append(scribble)
        if closed:
            _write(storage_dir, updated)
    return closed


def list_scribbles(storage_dir: Path = DEFAULT_STORAGE_DIR) -> list[Scribble]:
    """Every scribble, oldest first, with its current status."""
    with _lock:
        return _read(storage_dir)
