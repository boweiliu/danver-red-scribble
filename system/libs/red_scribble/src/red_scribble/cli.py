"""The ``red-scribble`` command: control Red Scribble and manage scribbles.

All subcommands honour ``--storage-dir`` (default ``data/.apps/red_scribble``), where Red Scribble
keeps its config and its scribble registry:

  red-scribble on --agent <id> [--mode batch|live]   enable, routing feedback to <agent>
  red-scribble off                                          disable (clears the target agent)
  red-scribble status                                       show the current config
  red-scribble list [--open]                                list scribbles (all, or only open)
  red-scribble close <id> [<id> ...]                        close scribbles so they stop rendering

The agent uses ``red-scribble close <id>`` after acting on a scribble so it stops rendering on
the user's screen (see the feedback messages built in :mod:`red_scribble.dispatch`).
"""

import argparse
from pathlib import Path

from imbue.mngr.cli.output_helpers import write_human_line

from red_scribble import config as rs_config
from red_scribble import store


def _config_path(storage_dir: Path) -> Path:
    return storage_dir / rs_config.CONFIG_FILENAME


def _cmd_on(storage_dir: Path, agent: str, mode: str) -> int:
    cfg = rs_config.enable(agent, mode=mode, path=_config_path(storage_dir))
    write_human_line(f"Red Scribble ON -> agent {cfg.target_agent_id} ({cfg.mode} mode)")
    return 0


def _cmd_off(storage_dir: Path) -> int:
    rs_config.disable(path=_config_path(storage_dir))
    write_human_line("Red Scribble OFF")
    return 0


def _cmd_status(storage_dir: Path) -> int:
    cfg = rs_config.load_config(_config_path(storage_dir))
    write_human_line(
        f"Red Scribble is {'on' if cfg.enabled else 'off'}; "
        f"target agent: {cfg.target_agent_id or '(none)'}; mode: {cfg.mode}"
    )
    return 0


def _cmd_list(storage_dir: Path, open_only: bool) -> int:
    for scribble in store.list_scribbles(storage_dir):
        if open_only and scribble.status != "open":
            continue
        write_human_line(
            f"{scribble.id}\t{scribble.status}\t{scribble.kind}\t{scribble.app}\t{scribble.page_url}"
        )
    return 0


def _cmd_close(storage_dir: Path, ids: list[str]) -> int:
    closed = store.close(storage_dir, ids)
    write_human_line("Closed: " + (", ".join(closed) if closed else "(none)"))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="red-scribble", description="Control Red Scribble.")
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=rs_config.DEFAULT_STORAGE_DIR,
        help="Where Red Scribble keeps its config and scribbles (default data/.apps/red_scribble)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    on = sub.add_parser("on", help="Enable Red Scribble, routing feedback to an agent")
    on.add_argument("--agent", required=True, help="Target agent id feedback routes to")
    on.add_argument("--mode", choices=("batch", "live"), default="batch")

    sub.add_parser("off", help="Disable Red Scribble")
    sub.add_parser("status", help="Show the current Red Scribble config")

    listing = sub.add_parser("list", help="List scribbles")
    listing.add_argument("--open", action="store_true", dest="open_only", help="Only open scribbles")

    closing = sub.add_parser("close", help="Close scribbles by id so they stop rendering")
    closing.add_argument("ids", nargs="+", help="Scribble ids to close")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    storage_dir: Path = args.storage_dir
    if args.command == "on":
        return _cmd_on(storage_dir, args.agent, args.mode)
    if args.command == "off":
        return _cmd_off(storage_dir)
    if args.command == "status":
        return _cmd_status(storage_dir)
    if args.command == "list":
        return _cmd_list(storage_dir, args.open_only)
    if args.command == "close":
        return _cmd_close(storage_dir, args.ids)
    return 1
