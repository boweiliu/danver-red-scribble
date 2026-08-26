"""The agent-writable Red Scribble setting: which chat's agent receives feedback, and how it is
delivered.

There is exactly one fact here -- the target agent -- and one policy knob -- the delivery mode.
"Red Scribble is on" is not stored; it is *derived* (:attr:`RedScribbleConfig.enabled`) from
whether a target agent is set, so the two can never disagree. The agent turns Red Scribble on by
recording *its own* agent id as the target (via :func:`enable`) when the user asks to iterate on
UI, and off (via :func:`disable`) when done. It is a tiny JSON file, trivially inspectable.
"""

import json
from pathlib import Path
from typing import Literal

from imbue.imbue_common.frozen_model import FrozenModel
from pydantic import Field

CONFIG_FILENAME = "config.json"
DEFAULT_STORAGE_DIR = Path("data/.apps/red_scribble")
DEFAULT_CONFIG_PATH = DEFAULT_STORAGE_DIR / CONFIG_FILENAME

DeliveryMode = Literal["live", "batch"]


class RedScribbleConfig(FrozenModel):
    """Who feedback routes to, and how. ``enabled`` is derived, never stored."""

    target_agent_id: str | None = Field(
        default=None,
        description="The mngr agent id feedback routes to; None means Red Scribble is off",
    )
    mode: DeliveryMode = Field(
        default="batch",
        description="'live' auto-sends each gather window; 'batch' waits for an explicit send",
    )

    @property
    def enabled(self) -> bool:
        """Red Scribble is on exactly when a target agent is set -- a conclusion, not a stored flag."""
        return self.target_agent_id is not None


_OFF = RedScribbleConfig()


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> RedScribbleConfig:
    """Load the config, returning the off default when the file is missing or unreadable.

    A corrupt or partial file must never make every proxied app fail to render, so an unreadable
    file is treated as 'off' rather than raising.
    """
    if not path.exists():
        return _OFF
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError, ValueError):
        return _OFF
    if not isinstance(data, dict):
        return _OFF
    return RedScribbleConfig.model_validate(data)


def save_config(config: RedScribbleConfig, path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Persist the config atomically so a concurrent reader never sees a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(config.model_dump_json(indent=2))
    tmp_path.replace(path)


def enable(
    target_agent_id: str,
    mode: DeliveryMode = "batch",
    path: Path = DEFAULT_CONFIG_PATH,
) -> RedScribbleConfig:
    """Turn Red Scribble on, routing feedback to ``target_agent_id`` in ``mode``, and persist."""
    config = RedScribbleConfig(target_agent_id=target_agent_id, mode=mode)
    save_config(config, path)
    return config


def disable(path: Path = DEFAULT_CONFIG_PATH) -> RedScribbleConfig:
    """Turn Red Scribble off by clearing the target agent, and persist.

    Re-enabling always names a target afresh (it comes from the chat that turns it back on), so
    there is no stale target to carry across an off period.
    """
    config = load_config(path).model_copy(update={"target_agent_id": None})
    save_config(config, path)
    return config
