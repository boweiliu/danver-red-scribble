"""Unit tests for the one-line opt-in helper.

The bootstrap tests below run the *emitted* snippet in node against a stubbed ``location``, so
what is asserted is the URL the browser would actually fetch. The rule it implements mirrors
``deriveServiceOrigin``/``workspaceHostCoordinate`` in the workspace UI's
``frontend/src/origin.ts``; these are the cases that pin the two together.
"""

from pathlib import Path

import pytest
from flask import Flask

from red_scribble.config import RedScribbleConfig
from red_scribble.config import save_config
from red_scribble.embed import register_jinja_helper
from red_scribble.embed import script_tag
from red_scribble.origins import ENV_APPS_FILE
from red_scribble.testing import is_node_available
from red_scribble.testing import run_bootstrap

_REGISTRY_WITH_RED_SCRIBBLE = """
[[apps]]
name = "red-scribble"
url = "http://localhost:8082"
label = "red-scribble-9fk2ax7t"
"""

_REGISTRY_WITHOUT_RED_SCRIBBLE = """
[[apps]]
name = "scribble-box"
url = "http://localhost:8080"
label = "scribble-box-3nbi4bp5"
"""


@pytest.fixture(name="registry_env")
def fixture_registry_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the registry lookup at a throwaway apps.toml and hand back its path."""
    registry_path = tmp_path / "apps.toml"
    registry_path.write_text(_REGISTRY_WITH_RED_SCRIBBLE)
    monkeypatch.setenv(ENV_APPS_FILE, str(registry_path))
    return registry_path


def _config_path(tmp_path: Path, target_agent_id: str | None) -> Path:
    path = tmp_path / "config.json"
    save_config(RedScribbleConfig(target_agent_id=target_agent_id), path)
    return path


def test_an_app_gets_the_bootstrap_when_red_scribble_is_on(tmp_path: Path, registry_env: Path) -> None:
    snippet = script_tag(_config_path(tmp_path, "agent-1"))
    assert snippet.startswith("<script>") and snippet.endswith("</script>")
    assert '"red-scribble-9fk2ax7t"' in snippet


def test_the_bootstrap_carries_the_label_but_never_a_hardcoded_coordinate(
    tmp_path: Path, registry_env: Path
) -> None:
    """The server contributes only the unguessable label; the coordinate is the browser's.

    A coordinate baked in here is the bug this design exists to prevent: the forwarder rewrites
    Host to the backend's own address and forwards nothing, and the coordinate the browser uses
    is not the one this container knows, so any server-side guess is wrong.
    """
    snippet = script_tag(_config_path(tmp_path, "agent-1"))
    assert "location.hostname" in snippet
    assert "location.protocol" in snippet
    assert "location.port" in snippet
    assert "localhost" not in snippet
    assert "host-" not in snippet.replace("host|agent", "")


def test_an_app_gets_nothing_when_red_scribble_is_off(tmp_path: Path, registry_env: Path) -> None:
    assert script_tag(_config_path(tmp_path, None)) == ""


def test_an_always_on_surface_gets_the_bootstrap_even_when_red_scribble_is_off(
    tmp_path: Path, registry_env: Path
) -> None:
    """A surface that exists to exercise Red Scribble must not go dark when it is switched off.

    Otherwise the test surface disappears exactly when someone is debugging Red Scribble itself.
    """
    assert '"red-scribble-9fk2ax7t"' in script_tag(_config_path(tmp_path, None), always_on=True)


def test_an_always_on_surface_still_gets_nothing_when_red_scribble_is_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``always_on`` overrides the switch, not the absence of the service -- there is no label to
    point at, and a bootstrap without one could only produce a console error."""
    registry_path = tmp_path / "apps.toml"
    registry_path.write_text(_REGISTRY_WITHOUT_RED_SCRIBBLE)
    monkeypatch.setenv(ENV_APPS_FILE, str(registry_path))
    assert script_tag(_config_path(tmp_path, None), always_on=True) == ""


def test_an_app_gets_nothing_when_the_config_has_never_been_written(
    tmp_path: Path, registry_env: Path
) -> None:
    assert script_tag(tmp_path / "never-written.json") == ""


def test_an_app_gets_nothing_when_red_scribble_is_not_registered(
    tmp_path: Path, registry_env: Path
) -> None:
    registry_env.write_text(_REGISTRY_WITHOUT_RED_SCRIBBLE)
    assert script_tag(_config_path(tmp_path, "agent-1")) == ""


def test_an_app_gets_nothing_when_the_registry_is_missing_or_broken(
    tmp_path: Path, registry_env: Path
) -> None:
    registry_env.write_text("not = = toml")
    assert script_tag(_config_path(tmp_path, "agent-1")) == ""
    registry_env.unlink()
    assert script_tag(_config_path(tmp_path, "agent-1")) == ""


def test_a_label_that_is_not_a_hostname_label_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The registry is workspace-local and trusted, but this value reaches a page's <script>."""
    registry_path = tmp_path / "apps.toml"
    registry_path.write_text(
        '[[apps]]\nname = "red-scribble"\nurl = "http://localhost:8082"\n'
        'label = "evil\\";alert(1);//"\n'
    )
    monkeypatch.setenv(ENV_APPS_FILE, str(registry_path))
    assert script_tag(_config_path(tmp_path, "agent-1")) == ""


_needs_node = pytest.mark.skipif(not is_node_available(), reason="node not available")


@_needs_node
def test_the_bootstrap_loads_the_plug_in_from_red_scribbles_own_workspace_origin(
    tmp_path: Path, registry_env: Path
) -> None:
    """The point of the whole design: the label is ours, the coordinate is the browser's."""
    snippet = script_tag(_config_path(tmp_path, "agent-1"))

    loaded = run_bootstrap(snippet, "scribble-box-3nbi4bp5.host-a1b2.localhost", port="8421")

    assert loaded == "http://red-scribble-9fk2ax7t.host-a1b2.localhost:8421/plugin.js"


@_needs_node
def test_the_bootstrap_replaces_the_embedding_services_label_rather_than_nesting_under_it(
    tmp_path: Path, registry_env: Path
) -> None:
    """Red Scribble's origin is one label deep onto the coordinate, never onto the host verbatim.

    Prefixing our label onto ``location.hostname`` as it stands would give
    ``red-scribble-....scribble-box-....host-<hex>...``, which the forwarder routes back to
    *scribble-box* -- so the plug-in would be fetched from the embedding app and 404. Any page
    nested deeper under a service label (a multi-origin app) has to reduce to the same answer.
    """
    snippet = script_tag(_config_path(tmp_path, "agent-1"))

    from_service = run_bootstrap(snippet, "scribble-box-3nbi4bp5.host-a1b2.localhost", port="8421")
    from_sub_origin = run_bootstrap(
        snippet, "panel.scribble-box-3nbi4bp5.host-a1b2.localhost", port="8421"
    )

    assert from_sub_origin == from_service


@_needs_node
def test_the_bootstrap_follows_the_browser_onto_a_shared_workspaces_https_origin(
    tmp_path: Path, registry_env: Path
) -> None:
    """Scheme, port, and the coordinate's tail all come from ``location``, so a share just works.

    A shared workspace serves ``https://<label>.host-<hex>.<user>.<region>.<domain>`` with no
    explicit port. Nothing on the server side could have known any of that.
    """
    snippet = script_tag(_config_path(tmp_path, "agent-1"))

    loaded = run_bootstrap(
        snippet,
        "scribble-box-3nbi4bp5.host-aaaa.bbbb.us1.imbueminds.com",
        protocol="https:",
    )

    assert loaded == "https://red-scribble-9fk2ax7t.host-aaaa.bbbb.us1.imbueminds.com/plugin.js"


@_needs_node
@pytest.mark.parametrize(
    "hostname,port",
    [("localhost", "5000"), ("127.0.0.1", "5000"), ("app.example.com", "")],
)
def test_the_bootstrap_does_nothing_at_all_off_a_workspace_origin(
    tmp_path: Path, registry_env: Path, hostname: str, port: str
) -> None:
    """No coordinate to anchor to means no correct answer, and a guess is worse than silence.

    A page served from a plain dev run or from somewhere outside the workspace entirely has no
    ``host-<hex>`` label. Guessing would fetch a script from a host that is not ours -- at best a
    console error on someone else's page, and the app embedding Red Scribble must not be disturbed
    by Red Scribble being inapplicable.
    """
    snippet = script_tag(_config_path(tmp_path, "agent-1"))

    assert run_bootstrap(snippet, hostname, port=port) is None


def test_the_jinja_helper_renders_the_bootstrap_as_markup_not_escaped_text(
    tmp_path: Path, registry_env: Path
) -> None:
    app = Flask(__name__)
    register_jinja_helper(app, _config_path(tmp_path, "agent-1"))
    with app.test_request_context("/"):
        rendered = app.jinja_env.from_string("<head>{{ red_scribble_tag() }}</head>").render()
    assert "<script>" in rendered
    assert "&lt;script&gt;" not in rendered
