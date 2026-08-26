"""Unit tests for the red-scribble CLI."""

from pathlib import Path

import pytest

from red_scribble import config
from red_scribble import store
from red_scribble.cli import main


def test_on_sets_config_and_off_clears_it(tmp_path: Path) -> None:
    assert main(["--storage-dir", str(tmp_path), "on", "--agent", "agent-1", "--mode", "live"]) == 0
    cfg = config.load_config(tmp_path / config.CONFIG_FILENAME)
    assert cfg.enabled is True
    assert cfg.target_agent_id == "agent-1"
    assert cfg.mode == "live"

    assert main(["--storage-dir", str(tmp_path), "off"]) == 0
    assert config.load_config(tmp_path / config.CONFIG_FILENAME).enabled is False


def test_close_marks_scribble_closed(tmp_path: Path) -> None:
    store.register(tmp_path, "fbk-1", "stroke")
    assert main(["--storage-dir", str(tmp_path), "close", "fbk-1"]) == 0
    assert {a.id: a.status for a in store.list_scribbles(tmp_path)}["fbk-1"] == "closed"


def test_list_open_only_hides_closed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store.register(tmp_path, "fbk-1", "stroke")
    store.register(tmp_path, "fbk-2", "text")
    store.close(tmp_path, ["fbk-2"])
    assert main(["--storage-dir", str(tmp_path), "list", "--open"]) == 0
    out = capsys.readouterr().out
    assert "fbk-1" in out
    assert "fbk-2" not in out
