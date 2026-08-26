"""Which cross-origin callers Red Scribble answers, and with what headers.

Red Scribble sits on its own origin, so every request from an app that embedded it is
cross-origin. The feedback endpoint hands a message to the user's chat, so this is a real
trust boundary, not a formality:

- an ``Origin`` is allowed only when it is a **service registered in this workspace**, sitting at
  its own origin label on a coordinate-shaped host -- never ``*``, and nothing hardcoded;
- anything else gets no CORS headers at all, and (for everything but the public assets) no
  answer either, so a page outside the workspace cannot message the user's agent even with a
  request shape that skips pre-flight.

**Why the registry rather than a comparison against our own host.** The obvious test -- "is the
caller in the same origin family as *me*?" -- cannot work here: the workspace forwarder rewrites
``Host`` to the backend's own address (``localhost:8082``), so this service does not know its own
public origin and every such comparison refused every legitimate sibling. The registry test needs
no self-knowledge: origin labels are unguessable by design (see
``system/scripts/forward_port.py``) and are minted per workspace, so presenting one *is* the
proof of membership.

That is also the limit of it. Because we cannot recognise our own coordinate, the host behind the
label is only checked for the ``host-<hex>`` *shape*, not for being ours -- a caller who owns a
domain can serve from ``<label>.host-<anything>.theirs.example`` and get past that part. The label
is the secret this boundary rests on; treat leaking one as the breach.
"""

from pathlib import Path
from typing import Final

from red_scribble.origins import service_name_for_origin

# Only what the plug-in actually sends. Credentials are allowed because the plug-in's requests
# must carry the workspace's domain-scoped session cookie.
_ALLOWED_METHODS: Final[str] = "GET, POST, OPTIONS"
_ALLOWED_HEADERS: Final[str] = "Content-Type"
_PREFLIGHT_MAX_AGE_SECONDS: Final[str] = "600"


def is_allowed_origin(origin: str | None, registry_path: Path) -> bool:
    """Whether a request's ``Origin`` is a service registered in this workspace.

    Same lookup that resolves a feedback packet's provenance, used here as the authorization
    test: an origin no registered service owns is not part of this workspace.
    """
    if not origin:
        return False
    return service_name_for_origin(origin, registry_path) is not None


def cors_headers(origin: str) -> dict[str, str]:
    """The response headers that let one allowed workspace origin talk to Red Scribble.

    ``Vary: Origin`` because the answer differs per origin and must not be cached across them.
    """
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": _ALLOWED_METHODS,
        "Access-Control-Allow-Headers": _ALLOWED_HEADERS,
        "Access-Control-Max-Age": _PREFLIGHT_MAX_AGE_SECONDS,
        "Vary": "Origin",
    }
