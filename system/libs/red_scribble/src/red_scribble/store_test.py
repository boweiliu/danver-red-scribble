"""Unit tests for the scribble registry."""

from pathlib import Path

from red_scribble.store import close
from red_scribble.store import list_scribbles
from red_scribble.store import register


def test_register_creates_open_scribble(tmp_path: Path) -> None:
    scribble = register(tmp_path, "fbk-1", "stroke", app="interview-bot", page_url="http://x/")
    assert scribble.status == "open"
    stored = list_scribbles(tmp_path)
    assert [a.id for a in stored] == ["fbk-1"]
    assert stored[0].kind == "stroke"
    assert stored[0].app == "interview-bot"


def test_register_is_idempotent_on_id(tmp_path: Path) -> None:
    register(tmp_path, "fbk-1", "stroke")
    register(tmp_path, "fbk-1", "stroke")
    assert len(list_scribbles(tmp_path)) == 1


def test_close_marks_closed_and_returns_ids(tmp_path: Path) -> None:
    register(tmp_path, "fbk-1", "stroke")
    register(tmp_path, "fbk-2", "text")
    closed = close(tmp_path, ["fbk-1"])
    assert closed == ["fbk-1"]
    by_id = {a.id: a for a in list_scribbles(tmp_path)}
    assert by_id["fbk-1"].status == "closed"
    assert by_id["fbk-1"].closed_at is not None
    assert by_id["fbk-2"].status == "open"


def test_close_is_idempotent(tmp_path: Path) -> None:
    register(tmp_path, "fbk-1", "stroke")
    assert close(tmp_path, ["fbk-1"]) == ["fbk-1"]
    assert close(tmp_path, ["fbk-1"]) == []   # already closed -> nothing newly closed


def test_close_unknown_id_is_noop(tmp_path: Path) -> None:
    register(tmp_path, "fbk-1", "stroke")
    assert close(tmp_path, ["nope"]) == []


def test_missing_store_is_empty(tmp_path: Path) -> None:
    assert list_scribbles(tmp_path / "nowhere") == []


def test_corrupt_store_is_empty(tmp_path: Path) -> None:
    (tmp_path / "scribbles.json").write_text("{not json")
    assert list_scribbles(tmp_path) == []
