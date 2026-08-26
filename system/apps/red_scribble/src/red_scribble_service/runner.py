"""Serves the Red Scribble plug-in, config, and feedback endpoints on their own workspace origin.

Red Scribble is an ordinary workspace app: it registers a port like any other service and owns
the origin ``red-scribble-<rand>.<workspace-domain>``. Apps opt in with one line
(:func:`red_scribble.embed.script_tag`), which points a ``<script>`` at ``/plugin.js`` here; the
plug-in then talks back to this origin, carrying the workspace's domain-scoped session cookie.

This module is a thin Flask adapter. All of the behaviour lives in
:func:`red_scribble.dispatch.route`, which is framework-neutral -- this supplies the host
boundary (where files live, how to list chats, how to message one), the CORS policy, and the
provenance of a feedback packet.

Services run from /home/user/workspace (the repo root). Conventions:

- Persistent state (the config, the scribble registry, raw feedback packets): read and write it
  under ``DATA_DIR`` (defined below), never a hardcoded ``data/.apps/red_scribble/`` at the call
  site. ``DATA_DIR`` defaults to ``data/.apps/red_scribble`` but honors the
  ``RED_SCRIBBLE_SERVICE_DATA_DIR`` env var, so an editing agent can point a throwaway instance
  at a *copy* of the data instead of the live store (see the update-app skill). Do NOT use
  ``Path(__file__)``-based paths for state.
- Static assets shipped with the library (the plug-in, the voice modules, html2canvas): they
  live in the ``red_scribble`` package, so they are addressed relative to that package's file.
- Listen port: bind ``PORT`` (defined below), which defaults to this app's assigned port but
  honors the ``RED_SCRIBBLE_SERVICE_PORT`` env var. Never hardcode the port at the
  ``run_simple`` call.
"""

import os
from pathlib import Path
from typing import Final

from flask import Flask
from flask import Response
from flask import render_template_string
from flask import request
from markupsafe import Markup
from werkzeug.serving import run_simple

import red_scribble
from red_scribble.config import CONFIG_FILENAME
from red_scribble.config import load_config
from red_scribble.dispatch import SERVED_ASSETS
from red_scribble.dispatch import RedScribbleDeps
from red_scribble.dispatch import route
from red_scribble.origins import apps_registry_path
from red_scribble.origins import service_name_for_origin
from red_scribble_service.agents import CachedAgentList
from red_scribble_service.agents import deliver_to_agent
from red_scribble_service.cors import cors_headers
from red_scribble_service.cors import is_allowed_origin
from red_scribble_service.status import RAW_FILENAME_PATTERN
from red_scribble_service.status import build_status_view

# Persistent state for this app lives under DATA_DIR: the target-chat config, the scribble
# registry, and every raw feedback packet (with its screenshot and voice audio alongside). It
# defaults to ``data/.apps/red_scribble`` but is overridable via the
# ``RED_SCRIBBLE_SERVICE_DATA_DIR`` env var so a throwaway instance can run against a *copy* of
# the data while editing -- see the update-app skill.
DATA_DIR = Path(os.environ.get("RED_SCRIBBLE_SERVICE_DATA_DIR", "data/.apps/red_scribble"))

# Listen port. Defaults to this app's assigned port but is overridable via the
# ``RED_SCRIBBLE_SERVICE_PORT`` env var so an editing agent can boot a throwaway instance on a
# spare port next to the live one (see the update-app skill).
PORT = int(os.environ.get("RED_SCRIBBLE_SERVICE_PORT", "8082"))

# The plug-in and its front-end modules ship inside the red_scribble library, next to the
# dispatcher that serves them. The status page's template belongs to this app instead.
ASSETS_DIR = Path(red_scribble.__file__).parent / "assets"
_STATUS_PAGE_PATH = Path(__file__).parent / "assets" / "index.html"
_LOGO_PATH = ASSETS_DIR / "logo-circle.svg"

# Content types for the raw attachments stored beside a feedback packet, so each opens in its
# own native form rather than as text.
_RAW_CONTENT_TYPES: Final[dict[str, str]] = {
    ".json": "application/json",
    ".png": "image/png",
    ".wav": "audio/wav",
}

# Requests that only fetch front-end code are answered whatever the caller's origin: a classic
# ``<script src>`` sends no Origin header at all, so requiring one would break the very tag that
# loads the plug-in. Every other route touches the user's config, scribbles, or chat and is
# refused outright unless the caller's origin belongs to a service registered in this workspace.
# This is the dispatcher's own asset allowlist rather than a second copy of it: a copy that fell
# behind would refuse a newly-served asset to the only callers that ever ask for one.
_PUBLIC_SUBPATHS: Final[frozenset[str]] = SERVED_ASSETS

# Provenance for a feedback packet when the caller's origin matches no registered service. The
# app name is derived server-side from the Origin header, never taken from the request body, so
# a page cannot claim to be some other app.
_UNKNOWN_APP: Final[str] = "unknown"


def create_app(deps: RedScribbleDeps) -> Flask:
    """Build the service around one host boundary, so tests can hand it fakes."""
    app = Flask("red_scribble_service", static_folder=None)

    def app_name_for_origin(origin: str | None) -> str:
        """Which app a feedback packet came from, resolved from its origin through the registry.

        Server-side and unforgeable: the browser sets Origin, and the label -> name mapping is
        the registry's.
        """
        if origin is None:
            return _UNKNOWN_APP
        return service_name_for_origin(origin, apps_registry_path()) or _UNKNOWN_APP

    def refused() -> Response:
        """The answer to a caller outside this workspace: no answer, and no CORS headers."""
        return Response(
            '{"detail": "Origin is not part of this workspace"}',
            status=403,
            mimetype="application/json",
        )

    def target_chat_name(target_agent_id: str | None) -> str:
        """The target chat's own name, falling back to its id when the chat list is unavailable."""
        if target_agent_id is None:
            return ""
        for agent in deps.list_agents():
            if agent.id == target_agent_id:
                return agent.name
        return target_agent_id

    @app.route("/<subpath>", methods=["GET", "POST", "OPTIONS"])
    def red_scribble_route(subpath: str) -> Response:
        """The plug-in's own endpoints: its code, its config, its scribbles, and its feedback."""
        origin = request.headers.get("Origin")
        # Authorized against the service registry, not against this service's own host: the
        # forwarder rewrites Host to ``localhost:8082``, so we cannot recognise our own siblings
        # by comparing origin families.
        is_allowed = is_allowed_origin(origin, apps_registry_path())

        # Pre-flight: answer for an allowed origin, refuse anything else outright.
        if request.method == "OPTIONS":
            if not is_allowed or origin is None:
                return refused()
            return Response(status=204, headers=cors_headers(origin))

        # A cross-origin POST with a simple content type skips pre-flight entirely, so the
        # refusal has to be the answer itself rather than a missing header on a done deed.
        if not is_allowed and subpath not in _PUBLIC_SUBPATHS:
            return refused()

        handled = route(
            request.method, subpath, request.get_data(), app_name_for_origin(origin), deps
        )
        response = Response(
            handled.body, status=handled.status_code, content_type=handled.content_type
        )
        if is_allowed and origin is not None:
            response.headers.extend(cors_headers(origin))
        return response

    @app.route("/")
    def status_page() -> Response:
        """Where feedback is going, and every scribble captured so far with its raw packet."""
        config = load_config(deps.storage_dir / CONFIG_FILENAME)
        view = build_status_view(
            deps.storage_dir,
            config.target_agent_id,
            target_chat_name(config.target_agent_id),
            config.mode,
        )
        page = render_template_string(
            _STATUS_PAGE_PATH.read_text(),
            logo=Markup(_LOGO_PATH.read_text()),
            **view.model_dump(),
        )
        return Response(page, mimetype="text/html")

    @app.route("/raw/<filename>")
    def raw_attachment(filename: str) -> Response:
        """One stored feedback attachment, served in its own native format.

        The name must match the ``<packet id>[-<n>].<ext>`` shape the dispatcher writes, so this
        can only ever reach a file the packets directory itself produced.
        """
        if RAW_FILENAME_PATTERN.match(filename) is None:
            return Response(
                '{"detail": "Not a stored packet file"}', status=404, mimetype="application/json"
            )
        attachment = deps.storage_dir / "packets" / filename
        if not attachment.is_file():
            return Response(
                '{"detail": "No such packet file"}', status=404, mimetype="application/json"
            )
        return Response(attachment.read_bytes(), mimetype=_RAW_CONTENT_TYPES[Path(filename).suffix])

    @app.route("/health")
    def health() -> Response:
        return Response('{"status": "ok"}', mimetype="application/json")

    return app


def main() -> None:
    deps = RedScribbleDeps(
        assets_dir=ASSETS_DIR,
        storage_dir=DATA_DIR,
        list_agents=CachedAgentList().get,
        deliver=deliver_to_agent,
    )
    run_simple(
        "127.0.0.1", PORT, create_app(deps), threaded=True, use_reloader=False, use_debugger=False
    )


if __name__ == "__main__":
    main()
