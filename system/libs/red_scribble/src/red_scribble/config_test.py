"""Unit tests for the Red Scribble config."""

from pathlib import Path

from red_scribble.config import RedScribbleConfig
from red_scribble.config import disable
from red_scribble.config import enable
from red_scribble.config import load_config
from red_scribble.config import save_config


def test_enabled_is_derived_from_target() -> None:
    assert RedScribbleConfig().enabled is False
    assert RedScribbleConfig(target_agent_id="a1").enabled is True


def test_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = RedScribbleConfig(target_agent_id="agent-123", mode="live")
    save_config(config, path)
    assert load_config(path) == config


def test_enable_persists_target_and_mode(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = enable("agent-abc", mode="live", path=path)
    assert config.enabled is True
    assert config.target_agent_id == "agent-abc"
    assert config.mode == "live"
    assert load_config(path) == config


def test_disable_clears_target(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    enable("agent-abc", mode="batch", path=path)
    disabled = disable(path)
    # No stored flag to contradict: off means the target is gone.
    assert disabled.enabled is False
    assert disabled.target_agent_id is None


def test_missing_file_is_off_default(tmp_path: Path) -> None:
    config = load_config(tmp_path / "does_not_exist.json")
    assert config.enabled is False
    assert config.target_agent_id is None


def test_corrupt_file_is_off_default(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{not valid json")
    assert load_config(path).enabled is False


def test_non_object_json_is_off_default(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("[1, 2, 3]")
    assert load_config(path).enabled is False
