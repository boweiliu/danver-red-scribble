"""Unit tests for the service's trust boundary: who may call, and who a packet is credited to.

The feedback endpoint hands a message to the user's chat, so "a page outside this workspace
cannot reach it" is the property worth pinning. The tests drive the real Flask app through its
test client, with the mngr-facing callbacks replaced by fakes.
"""

import json
from pathlib import Path

import pytest
from flask.testing import FlaskClient

from red_scribble.config import RedScribbleConfig
from red_scribble.config import save_config
from red_scribble.dispatch import AgentSummary
from red_scribble.dispatch import RedScribbleDeps
from red_scribble.origins import ENV_APPS_FILE
from red_scribble_service.runner import _PUBLIC_SUBPATHS
from red_scribble_service.runner import create_app
from red_scribble_service.testing import APP_LABEL
from red_scribble_service.testing import COORDINATE
from red_scribble_service.testing import SERVICE_LABEL
from red_scribble_service.testing import WORKSPACE_REGISTRY
from red_scribble_service.testing import Deliveries

_RED_SCRIBBLE_HOST = f"{SERVICE_LABEL}.{COORDINATE}:8421"
_APP_ORIGIN = f"http://{APP_LABEL}.{COORDINATE}:8421"
_FOREIGN_ORIGIN = "https://evil.example.com"


@pytest.fixture(name="client")
def fixture_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, deliveries: Deliveries
) -> FlaskClient:
    """A configured service over throwaway storage, with the mngr calls replaced by fakes."""
    registry_path = tmp_path / "apps.toml"
    registry_path.write_text(WORKSPACE_REGISTRY)
    monkeypatch.setenv(ENV_APPS_FILE, str(registry_path))

    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    save_config(RedScribbleConfig(target_agent_id="agent-1"), storage_dir / "config.json")

    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    (assets_dir / "plugin.js").write_text("// the plug-in")

    deps = RedScribbleDeps(
        assets_dir=assets_dir,
        storage_dir=storage_dir,
        list_agents=lambda: (AgentSummary("agent-1", "chat", "running"),),
        deliver=deliveries.deliver,
    )
    return create_app(deps).test_client()


def _headers(origin: str | None = None) -> dict[str, str]:
    headers = {"Host": _RED_SCRIBBLE_HOST}
    if origin is not None:
        headers["Origin"] = origin
    return headers


def test_a_page_in_this_workspace_is_answered_with_credentialed_cors(client: FlaskClient) -> None:
    response = client.get("/config", headers=_headers(_APP_ORIGIN))

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == _APP_ORIGIN
    assert response.headers["Access-Control-Allow-Credentials"] == "true"
    assert response.headers["Vary"] == "Origin"


def test_the_allowed_origin_is_reflected_and_never_a_wildcard(client: FlaskClient) -> None:
    response = client.get("/config", headers=_headers(_APP_ORIGIN))

    assert "*" not in response.headers["Access-Control-Allow-Origin"]


def test_a_page_from_outside_this_workspace_is_refused_with_no_cors_headers(
    client: FlaskClient, deliveries: Deliveries
) -> None:
    response = client.post(
        "/feedback",
        headers=_headers(_FOREIGN_ORIGIN),
        json={"scribbles": [{"kind": "text", "text": "stolen"}]},
    )

    assert response.status_code == 403
    assert "Access-Control-Allow-Origin" not in response.headers
    assert deliveries.sent == []


def test_a_request_with_no_origin_at_all_cannot_reach_the_chat(
    client: FlaskClient, deliveries: Deliveries
) -> None:
    """A simple cross-origin POST skips pre-flight, so the refusal has to be the answer itself."""
    response = client.post(
        "/feedback",
        headers=_headers(),
        data=json.dumps({"scribbles": [{"kind": "text", "text": "stolen"}]}),
        content_type="text/plain",
    )

    assert response.status_code == 403
    assert deliveries.sent == []


def test_preflight_is_answered_for_a_page_in_this_workspace(client: FlaskClient) -> None:
    response = client.options("/feedback", headers=_headers(_APP_ORIGIN))

    assert response.status_code == 204
    assert response.headers["Access-Control-Allow-Origin"] == _APP_ORIGIN
    assert "POST" in response.headers["Access-Control-Allow-Methods"]
    assert "Content-Type" in response.headers["Access-Control-Allow-Headers"]


def test_preflight_from_outside_this_workspace_gets_nothing(client: FlaskClient) -> None:
    response = client.options("/feedback", headers=_headers(_FOREIGN_ORIGIN))

    assert response.status_code == 403
    assert "Access-Control-Allow-Origin" not in response.headers


def test_the_plug_in_loads_without_an_origin_header_because_a_script_tag_sends_none(
    client: FlaskClient,
) -> None:
    response = client.get("/plugin.js", headers=_headers())

    assert response.status_code == 200
    assert b"the plug-in" in response.data


def test_feedback_is_credited_to_the_app_its_origin_names(
    client: FlaskClient, deliveries: Deliveries
) -> None:
    response = client.post(
        "/feedback",
        headers=_headers(_APP_ORIGIN),
        json={"scribbles": [{"kind": "text", "text": "make this bigger"}]},
    )

    assert response.status_code == 200
    assert deliveries.sent[0][0] == "agent-1"
    assert 'app="scribble-box"' in deliveries.sent[0][1]


def test_feedback_from_an_unregistered_origin_is_refused_even_inside_the_family(
    client: FlaskClient, deliveries: Deliveries
) -> None:
    """Membership is proved by a registered origin label, not by domain shape.

    Sharing the workspace's domain is not enough: the labels are unguessable and minted per
    service, so an origin no registered service owns has no claim on the user's chat. This is
    stricter than the domain comparison it replaced -- which could not be used at all, because
    the forwarder rewrites Host and the service cannot see its own public origin.
    """
    response = client.post(
        "/feedback",
        headers=_headers("http://mystery-zzzz1111.host-a1b2.localhost:8421"),
        json={"scribbles": [{"kind": "text", "text": "from somewhere"}]},
    )

    assert response.status_code == 403
    assert deliveries.sent == []


def test_a_sibling_service_is_recognised_without_the_service_knowing_its_own_host(
    client: FlaskClient, deliveries: Deliveries
) -> None:
    """The regression that kept every scribble from being delivered.

    Behind the forwarder this service sees ``Host: localhost:8082``, so any check phrased as
    "is the caller in my own origin family?" refused its own siblings. The test client's host is
    equally uninformative, which is the point: authorization must not depend on it.
    """
    response = client.post(
        "/feedback",
        headers=_headers(_APP_ORIGIN),
        json={"scribbles": [{"kind": "text", "text": "delivered"}]},
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == _APP_ORIGIN
    assert deliveries.sent != []


def test_a_page_wearing_a_registered_label_on_its_own_domain_cannot_reach_the_chat(
    client: FlaskClient, deliveries: Deliveries
) -> None:
    """Anyone can put any label in front of a domain they own, and the label alone is not enough.

    Neither origin here is a workspace one: the first has no coordinate-shaped label behind the
    registered label, and the second is the attacker's domain with a workspace host smuggled into
    the userinfo, which the strict authority parse rejects. On the TLS path the workspace session
    cookie is ``SameSite=None``, so the browser attaches it to a simple cross-site POST -- the
    refusal here is what stops the send, not the cookie.
    """
    for origin in (
        "https://scribble-box-3nbi4bp5.attacker.example",
        f"{_APP_ORIGIN}@attacker.example",
    ):
        response = client.post(
            "/feedback",
            headers=_headers(origin),
            json={"scribbles": [{"kind": "text", "text": "stolen"}]},
        )
        assert response.status_code == 403, origin
        assert "Access-Control-Allow-Origin" not in response.headers
    assert deliveries.sent == []


def test_no_endpoint_that_touches_the_users_state_answers_a_foreign_origin(
    client: FlaskClient,
) -> None:
    """Every route but the front-end code is behind the boundary, whatever the method.

    ``/config`` reveals the target chat and the workspace's chat list, ``/scribbles`` the feedback
    already given, ``POST /config`` re-points delivery, and ``/close`` retires scribbles -- so a
    foreign page must get nothing from any of them.
    """
    refusals = (
        client.get("/config", headers=_headers(_FOREIGN_ORIGIN)),
        client.get("/scribbles", headers=_headers(_FOREIGN_ORIGIN)),
        client.post("/config", headers=_headers(_FOREIGN_ORIGIN), json={"target_agent_id": "theirs"}),
        client.post("/close", headers=_headers(_FOREIGN_ORIGIN), json={"ids": []}),
    )

    for response in refusals:
        assert response.status_code == 403
        assert b"agent-1" not in response.data
    assert client.get("/config", headers=_headers(_APP_ORIGIN)).json["target_agent_id"] == "agent-1"


def test_the_openly_served_subpaths_are_front_end_code_and_nothing_else(
    client: FlaskClient, deliveries: Deliveries
) -> None:
    """``_PUBLIC_SUBPATHS`` is open because a ``<script src>`` sends no Origin -- so it must hold
    only static code. A non-GET behind it reaches no handler, and it grants no CORS either."""
    assert _PUBLIC_SUBPATHS == frozenset(
        {"plugin.js", "voice_session.js", "voice_capture.js", "html2canvas.js"}
    )
    for subpath in sorted(_PUBLIC_SUBPATHS):
        posted = client.post(f"/{subpath}", headers=_headers(_FOREIGN_ORIGIN), data=b"{}")
        assert posted.status_code == 404
        fetched = client.get(f"/{subpath}", headers=_headers(_FOREIGN_ORIGIN))
        assert "Access-Control-Allow-Origin" not in fetched.headers
    assert deliveries.sent == []


def test_the_health_check_answers_without_any_origin(client: FlaskClient) -> None:
    response = client.get("/health", headers=_headers())

    assert response.status_code == 200
    assert json.loads(response.data)["status"] == "ok"


def test_the_status_page_shows_where_feedback_is_going(client: FlaskClient) -> None:
    client.post(
        "/feedback",
        headers=_headers(_APP_ORIGIN),
        json={"scribbles": [{"kind": "text", "text": "make this bigger"}]},
    )

    page = client.get("/", headers=_headers()).get_data(as_text=True)

    assert "Red Scribble" in page
    assert "chat" in page
    assert "make this bigger" in page
    assert "scribble-box" in page


def test_a_stored_packet_can_be_opened_in_its_own_format(client: FlaskClient) -> None:
    posted = client.post(
        "/feedback",
        headers=_headers(_APP_ORIGIN),
        json={"scribbles": [{"kind": "text", "text": "make this bigger"}]},
    )
    packet_id = json.loads(posted.data)["packet_ids"][0]

    response = client.get(f"/raw/{packet_id}.json", headers=_headers())

    assert response.status_code == 200
    assert response.mimetype == "application/json"
    assert json.loads(response.data)["text"] == "make this bigger"


def test_the_raw_viewer_only_serves_stored_packet_files(client: FlaskClient) -> None:
    for name in ("../config.json", "config.json", "..%2fconfig.json", "fbk-nope.json"):
        assert client.get(f"/raw/{name}", headers=_headers()).status_code == 404


def test_feedback_is_accepted_as_a_cors_simple_request(
    client: FlaskClient, deliveries: Deliveries
) -> None:
    """The plug-in posts JSON under ``text/plain`` on purpose, and the service must accept it.

    ``application/json`` would make the browser send a CORS preflight first, and a preflight
    carries no cookies -- so the workspace forwarder rejects it as unauthenticated before it ever
    reaches this service, and the POST can never succeed however correct our CORS headers are.
    Keeping the request "simple" is what makes feedback deliverable at all; parsing must
    therefore not depend on the content type.
    """
    response = client.post(
        "/feedback",
        headers={**_headers(_APP_ORIGIN), "Content-Type": "text/plain;charset=UTF-8"},
        data=json.dumps({"scribbles": [{"kind": "text", "text": "sent without a preflight"}]}),
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == _APP_ORIGIN
    assert deliveries.sent != []
    assert "sent without a preflight" in deliveries.sent[0][1]
