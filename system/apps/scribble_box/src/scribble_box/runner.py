"""A scratchpad page for testing Red Scribble feedback (demo-only; Red Scribble changes here are never committed).

REMINDER (Red Scribble demo surface): the Scribble Box exists to test Red
Scribble. Changes made to any Scribble Box file as the result of Red Scribble
feedback are for demo purposes only and are NEVER committed. Any such changes
MUST be reverted before any other commit is made. See the
red-scribble-feedback skill.

Services run from /home/user/workspace (the repo root). Conventions:

- Persistent state (anything written and read across runs -- cursors,
  caches, snapshots, user records): read and write it under ``DATA_DIR``
  (defined below), never a hardcoded ``data/.apps/scribble-box/`` at the
  call site. ``DATA_DIR`` defaults to ``data/.apps/scribble-box/`` but
  honors the ``SCRIBBLE_BOX_DATA_DIR`` env var, so an editing agent can point a
  throwaway instance at a *copy* of the data instead of the live store
  (see the update-app skill). Do NOT use ``Path(__file__)``-based
  paths for state -- the bug to avoid is one process writing to
  ``/home/user/workspace/data/.apps/...`` while another reads from
  ``/home/user/workspace/system/apps/<pkg>/data/...``.
- Static assets shipped alongside this file (templates, default
  configs, bundled JSON): ``Path(__file__).parent / "assets/..."`` is
  fine and is the right pattern.
- Listen port: bind ``PORT`` (defined below), which defaults to this
  app's assigned port but honors the ``SCRIBBLE_BOX_PORT`` env var, so
  an editing agent can boot a throwaway instance on a *spare* port
  alongside the live one (see the update-app skill). Never hardcode
  the port at the ``run_simple`` call.

This is a synchronous Flask app served by the threaded Werkzeug server.
The system_interface proxy at ``/service/scribble-box/`` rewrites absolute
paths in served HTML and installs a scoped service worker that prepends
the prefix to the page's own fetches, so the app can serve at ``/`` and
still work behind the proxy. Use ``flask_sock`` if you need WebSockets.
"""

import logging
import os
from pathlib import Path

from flask import Flask, Response, render_template_string
from werkzeug.serving import run_simple

from red_scribble.embed import register_jinja_helper

# Persistent state for this app lives under DATA_DIR. It defaults to
# ``data/.apps/scribble-box/`` but is overridable via the ``SCRIBBLE_BOX_DATA_DIR`` env var
# so a throwaway instance can run against a *copy* of the data while editing --
# see the update-app skill. Always read/write state through DATA_DIR;
# never hardcode ``data/.apps/scribble-box/`` at a call site, or the override is
# bypassed. A writing call site should ``DATA_DIR.mkdir(parents=True,
# exist_ok=True)`` before writing.
DATA_DIR = Path(os.environ.get("SCRIBBLE_BOX_DATA_DIR", "data/.apps/scribble-box"))

# Listen port. Defaults to this app's assigned port but is overridable via
# the ``SCRIBBLE_BOX_PORT`` env var so an editing agent can boot a throwaway
# instance on a spare port next to the live one (see the update-app skill).
# Never hardcode the port at the ``run_simple`` call, or the override is bypassed.
PORT = int(os.environ.get("SCRIBBLE_BOX_PORT", "8080"))

app = Flask("scribble_box", static_folder=None)

# The Red Scribble opt-in: this makes ``{{ red_scribble_tag() }}`` available to the page below,
# which is the whole of it. ``always_on`` because the Scribble Box exists *only* to exercise Red
# Scribble -- following the global switch would blank the test surface exactly when someone is
# debugging Red Scribble. Ordinary apps omit it and follow the switch. The tag is still empty when
# Red Scribble is not installed at all.
register_jinja_helper(app, always_on=True)


_PAGE_PATH = Path(__file__).parent / "assets" / "scribble_box.html"


@app.route("/")
def index() -> Response:
    return Response(render_template_string(_PAGE_PATH.read_text()), mimetype="text/html")


@app.route("/health")
def health() -> Response:
    return Response('{"status": "ok"}', mimetype="application/json")


def main() -> None:
    # Werkzeug configures only its own access logger, so INFO from this app and from
    # ``red_scribble.embed`` -- which is where "why is there no floating logo" is answered --
    # would otherwise be dropped before it reaches the service log.
    logging.basicConfig(level=logging.INFO)
    run_simple(
        "127.0.0.1", PORT, app, threaded=True, use_reloader=False, use_debugger=False
    )


if __name__ == "__main__":
    main()
