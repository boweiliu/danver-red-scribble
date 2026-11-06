"""Reading the service registry: which services exist, and which origin belongs to which.

Red Scribble runs as an ordinary workspace service on its own origin, so every app that embeds it
talks to it *cross-origin*. Both questions that raises are answered from one fact -- the service
registry (``data/.state/apps.toml``), which maps each service name to its **unguessable origin
label** (a security property; see the comment block in ``system/scripts/forward_port.py``):

- **Where is Red Scribble?** Only the label is looked up here. The origin is assembled in the
  *browser*, by :mod:`red_scribble.embed`'s bootstrap, because the workspace coordinate is
  something only the browser knows: the forwarder rewrites ``Host`` to the backend's own address
  and forwards nothing, so no server-side derivation can be right.
- **Who may call it?** :func:`service_name_for_origin` -- an origin is part of this workspace
  exactly when it has the shape ``<registered label>.<coordinate-shaped label>.…``. Presenting an
  unguessable, per-workspace label *is* the proof of membership, and it is the *only* proof: the
  coordinate behind it is checked for shape, never against our own, because the forwarder rewrites
  ``Host`` and this service never learns its own public origin. So the shape check bars the naive
  ``<registered label>.attacker.example`` and nothing more -- a caller who owns a domain can add a
  ``host-<hex>`` label of their own and get past it. Keep the label the secret.

Nothing here raises: a Red Scribble lookup that fails must never break the app asking.
"""

import os
import re
import tomllib
from pathlib import Path
from typing import Final

from imbue.imbue_common.pure import pure

# The service registry every workspace component reads: service name -> backend URL + the
# unguessable origin label. Relative to the repo root, which is the cwd of every supervisord
# service; the env override exists for tests and for callers running from elsewhere.
DEFAULT_APPS_FILE: Final[str] = "data/.state/apps.toml"
ENV_APPS_FILE: Final[str] = "MINDS_APPS_FILE"

# The service name Red Scribble registers under (``forward_port.py --name red-scribble``).
RED_SCRIBBLE_SERVICE_NAME: Final[str] = "red-scribble"

# An ``Origin`` header value, parsed strictly rather than by partitioning. Origin is
# attacker-influenced, so the authority is pinned to hostname characters and an optional numeric
# port: a lenient parse lets ``http://<label>.<coordinate>:8421@attacker.example`` present a
# workspace host to us and resolve to the attacker's in the browser.
_ORIGIN: Final = re.compile(r"^https?://(?P<host>[a-z0-9_.-]+)(?::[0-9]+)?$", re.IGNORECASE)

# The *shape* of a workspace host-coordinate label -- the same rule the browser applies in
# ``embed.py``'s bootstrap and the workspace UI's ``frontend/src/origin.ts`` (``agent-`` is the
# legacy spelling). ``forward_port.py`` reserves both prefixes, so a service label can never
# collide with one. This says nothing about *which* workspace: our own coordinate is not knowable
# here, so any hex passes.
_WORKSPACE_COORDINATE_LABEL: Final = re.compile(r"^(?:host|agent)-[a-f0-9]+$", re.IGNORECASE)


def _repo_root() -> Path:
    """Walk up from cwd to the workspace root, falling back to cwd.

    ``system/supervisord.conf`` is the marker: it is the config the workspace's
    programs all run under, so the root it finds is the one every program --
    ``forward_port.py``, which writes the registry this module reads, included --
    runs from. (A script was the marker before; ``system/scripts/layout.py`` went
    when the desktop shell replaced it with the ``workspace-layout`` package, at
    which point every walk fell through to the cwd fallback silently.)
    """
    here = Path.cwd()
    for candidate in (here, *here.parents):
        if (candidate / "system" / "supervisord.conf").exists():
            return candidate
    return here


def apps_registry_path() -> Path:
    """The service registry's path, honoring the ``MINDS_APPS_FILE`` override."""
    registry = Path(os.environ.get(ENV_APPS_FILE, DEFAULT_APPS_FILE))
    if registry.is_absolute():
        return registry
    return _repo_root() / registry


def read_service_labels(registry_path: Path) -> dict[str, str]:
    """Every registered service as ``name -> origin label``, empty when the registry is unusable.

    A missing, unreadable, or malformed registry reads as "nothing is registered" rather than an
    error: the callers are an embedding app's page render and a CORS check, neither of which may
    fail because Red Scribble is unavailable.
    """
    try:
        raw = tomllib.loads(registry_path.read_text())
    except (OSError, tomllib.TOMLDecodeError, ValueError):
        return {}
    apps = raw.get("apps")
    if not isinstance(apps, list):
        return {}
    label_by_name: dict[str, str] = {}
    for app in apps:
        if not isinstance(app, dict):
            continue
        name = app.get("name")
        label = app.get("label")
        if isinstance(name, str) and isinstance(label, str) and name and label:
            label_by_name[name] = label
    return label_by_name


@pure
def service_label_of_origin(origin: str) -> str | None:
    """The service origin label ``origin`` presents, or None when it is not a service origin.

    A workspace service origin is exactly ``<label>.<coordinate>`` -- one label deep onto the
    ``host-<hex>`` coordinate -- so both positions are checked:

    - **nothing may precede the label**, because the forwarder routes deeper labels back to the
      owning service, so a sub-origin is that service's own space rather than a service in its own
      right;
    - **a coordinate-shaped label must follow it**, which rules out a registered label prefixed
      straight onto a domain the caller owns (``scribble-box-3nbi4bp5.attacker.example``).

    That second check is a *shape* check and stops there. Whether the coordinate is **ours** is
    not knowable here -- the forwarder rewrites ``Host``, which is the reason this module exists --
    so ``scribble-box-3nbi4bp5.host-a1b2.attacker.example`` passes with any hex the caller likes.
    What actually keeps a stranger out is the label: unguessable, minted per workspace, and looked
    up in the registry by :func:`service_name_for_origin`.
    """
    match = _ORIGIN.match(origin.strip())
    if match is None:
        return None
    labels = match.group("host").lower().split(".")
    if len(labels) < 2 or not labels[0]:
        return None
    if _WORKSPACE_COORDINATE_LABEL.match(labels[1]) is None:
        return None
    return labels[0]


def service_name_for_origin(origin: str, registry_path: Path) -> str | None:
    """The registered service name behind ``origin``, resolved through the registry.

    This is the *authoritative* provenance for a feedback packet: the browser sets ``Origin``
    itself and a page cannot forge it, and the label -> name mapping is the registry's, not the
    caller's. Returns None for an origin no registered service owns.
    """
    label = service_label_of_origin(origin)
    if label is None:
        return None
    for name, registered_label in read_service_labels(registry_path).items():
        if registered_label.lower() == label:
            return name
    return None
