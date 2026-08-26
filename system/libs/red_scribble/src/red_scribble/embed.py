"""The one-line opt-in: the snippet an app emits to get Red Scribble.

An app joins Red Scribble by rendering :func:`script_tag` into its own HTML. When Red Scribble is
off, or not installed, the helper returns the empty string and the app's page is byte-for-byte
what it was.

**Why this emits a bootstrap rather than a plain ``<script src>``.** Building Red Scribble's URL
needs two facts that live on opposite sides of the wire:

- the **origin label** (``red-scribble-9eidj5it``) is deliberately unguessable -- a security
  property, see ``system/scripts/forward_port.py`` -- so only the *server* can look it up, from
  the service registry.
- the **workspace coordinate** (``host-<hex>.localhost:8421``) is only known to the *browser*.
  The workspace forwarder rewrites ``Host`` to the backend's own address (``localhost:8080``) and
  forwards no ``X-Forwarded-Host`` or ``X-Forwarded-Proto``, so the app genuinely cannot learn
  the address the browser used. Worse, the coordinate the browser uses is not the one the
  container knows about, so there is nothing on disk to fall back to either.

So the server contributes the label and the browser contributes the coordinate, deriving the
origin by the same rule the workspace UI uses in ``frontend/src/origin.ts``: prefix the label
onto the ``host-<hex>`` coordinate found in ``location.hostname``. Scheme and port come from
``location`` too, so https/http and any forwarder port are handled without being told.

Nothing here raises, and the bootstrap is a no-op on any page that is not served from a
workspace service origin. A problem inside Red Scribble must never break the app embedding it.
"""

import json
import logging
import re
from pathlib import Path
from typing import Final

from flask import Flask
from markupsafe import Markup

from red_scribble.config import DEFAULT_CONFIG_PATH
from red_scribble.config import load_config
from red_scribble.origins import RED_SCRIBBLE_SERVICE_NAME
from red_scribble.origins import apps_registry_path
from red_scribble.origins import read_service_labels

_LOG = logging.getLogger(__name__)

# A registered service's origin label, as minted by ``forward_port.py``. Validated before being
# interpolated into the bootstrap: the registry is workspace-local and trusted, but a value that
# reaches a page's <script> element earns a check regardless of where it came from.
_SAFE_LABEL: Final = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$", re.IGNORECASE)

# Derives Red Scribble's origin in the browser and loads the plug-in from it. Mirrors
# ``deriveServiceOrigin``/``workspaceHostCoordinate`` in the workspace UI's
# ``frontend/src/origin.ts`` -- the authoritative statement of how a service origin is built.
# Silent no-op off a workspace origin (a plain localhost dev run, a page saved to disk), because
# there is no coordinate to anchor to and a wrong guess would only yield a console error.
_BOOTSTRAP: Final = """\
<script>(function(){var label=%s;\
var labels=location.hostname.split(".");var at=-1;\
for(var i=0;i<labels.length;i++){if(/^(?:host|agent)-[a-f0-9]+$/i.test(labels[i])){at=i;break;}}\
if(at<0)return;\
var coordinate=labels.slice(at).join(".")+(location.port?":"+location.port:"");\
var s=document.createElement("script");\
s.src=location.protocol+"//"+label+"."+coordinate+"/plugin.js";s.defer=true;\
(document.head||document.documentElement).appendChild(s);})();</script>"""


def script_tag(config_path: Path = DEFAULT_CONFIG_PATH, always_on: bool = False) -> str:
    """The snippet that loads Red Scribble, or ``""`` when it is off or not installed.

    ``always_on`` emits it even when Red Scribble is globally off. It is for surfaces whose whole
    purpose is to exercise Red Scribble -- without it, the app under test goes dark exactly when
    someone is debugging Red Scribble itself. The plug-in copes with no target chat being set:
    its long-press menu lists the workspace's chats so one can be chosen there. Ordinary apps
    should leave this False and follow the global switch.
    """
    if not always_on and not load_config(config_path).enabled:
        _LOG.info("red-scribble: no tag emitted -- Red Scribble is off")
        return ""
    label = read_service_labels(apps_registry_path()).get(RED_SCRIBBLE_SERVICE_NAME)
    if label is None:
        # The ways this fails look identical to someone staring at a page with no floating logo,
        # so name which one it was. Silence here is what made "the button isn't there"
        # unanswerable without reading the source.
        _LOG.info(
            "red-scribble: no tag emitted -- %r is not in the service registry",
            RED_SCRIBBLE_SERVICE_NAME,
        )
        return ""
    if not _SAFE_LABEL.match(label):
        _LOG.warning("red-scribble: no tag emitted -- registry label %r is not a hostname label", label)
        return ""
    _LOG.info("red-scribble: bootstrap emitted for label %r", label)
    return _BOOTSTRAP % json.dumps(label)


def register_jinja_helper(app: Flask, config_path: Path = DEFAULT_CONFIG_PATH, always_on: bool = False) -> None:
    """Expose ``{{ red_scribble_tag() }}`` to a Flask app's templates.

    The whole opt-in for a Jinja-rendered app: call this once at startup, then put
    ``{{ red_scribble_tag() }}`` in the template's ``<head>``. The result is marked safe so
    Jinja's autoescaping renders it as markup rather than as escaped text.

    Pass ``always_on=True`` only for a surface that exists to exercise Red Scribble itself; see
    :func:`script_tag`.
    """

    def red_scribble_tag() -> Markup:
        return Markup(script_tag(config_path, always_on))

    app.jinja_env.globals["red_scribble_tag"] = red_scribble_tag
