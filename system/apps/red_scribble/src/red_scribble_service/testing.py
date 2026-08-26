"""Test helpers for standing the Red Scribble service up in front of a caller.

Everything here is shared by more than one of this app's test modules: the two workspace service
origins the tests speak from, the registry that makes them siblings, a recorder for what the
service handed a chat, and a loopback server for the tests that need a real socket rather than
Flask's test client. The fixtures that assemble these live in this app's ``conftest.py``.
"""

import threading
from collections.abc import Callable
from collections.abc import Iterable
from pathlib import Path
from typing import Final

from werkzeug.serving import make_server

# Two workspace service origins sharing one coordinate, which is what makes them siblings.
# ``*.localhost`` resolves to loopback in the browser, so both are reachable on one machine.
APP_LABEL: Final[str] = "scribble-box-3nbi4bp5"
SERVICE_LABEL: Final[str] = "red-scribble-9fk2ax7t"
COORDINATE: Final[str] = "host-a1b2.localhost"

# The service registry both origins are looked up in: label -> service name, which is how a
# caller is authorized and how a feedback packet gets its provenance.
WORKSPACE_REGISTRY: Final[str] = f"""
[[apps]]
name = "scribble-box"
url = "http://localhost:8080"
label = "{APP_LABEL}"

[[apps]]
name = "red-scribble"
url = "http://localhost:8082"
label = "{SERVICE_LABEL}"
"""

# The workspace-provisioned stealth Chromium. Playwright's own cache lookup only finds builds it
# downloaded itself, so the executable is named explicitly (see the root CLAUDE.md).
FORTRESS_CHROMIUM_PATH: Final[Path] = Path("/opt/fortress/tilion-fortress/tilion")


# The WSGI contract, written out rather than left as ``object``. The official spelling
# (``_typeshed.wsgi``) is only importable under a ``TYPE_CHECKING`` guard, which this repo does not
# allow, and a server that accepts ``object`` would not catch a handler written to the wrong shape
# until a browser test made a request against it. ``start_response`` keeps an open parameter list
# because a WSGI server may pass the optional ``exc_info`` third argument, and Flask's own
# ``__call__`` is typed for a server that does.
StartResponse = Callable[..., Callable[[bytes], object]]
WsgiApplication = Callable[[dict[str, object], StartResponse], Iterable[bytes]]


class Deliveries:
    """Captures what the service handed to the target chat."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def deliver(self, agent_id: str, message: str) -> bool:
        self.sent.append((agent_id, message))
        return True


class Server:
    """A WSGI app on its own loopback port, shut down with the fixture that made it."""

    def __init__(self, wsgi_app: WsgiApplication) -> None:
        # Port 0 lets the server itself take a free port and keep it. Probing for one first and
        # handing the number over would unbind it in between, leaving a window for anything on the
        # machine -- the second Server the same fixture builds, a parallel worker -- to take it.
        self._server = make_server("127.0.0.1", 0, wsgi_app, threaded=True)
        self.port = int(self._server.server_port)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def origin(self, label: str) -> str:
        return f"http://{label}.{COORDINATE}:{self.port}"

    def shutdown(self) -> None:
        self._server.shutdown()
        self._thread.join(timeout=10)
