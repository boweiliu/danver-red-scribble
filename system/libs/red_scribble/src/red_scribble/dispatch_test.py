"""Unit tests for the framework-neutral Red Scribble request routing."""

import base64
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import red_scribble.dispatch as dispatch
from red_scribble.config import CONFIG_FILENAME
from red_scribble.config import RedScribbleConfig
from red_scribble.config import load_config
from red_scribble.config import save_config
from red_scribble.dispatch import AgentSummary
from red_scribble.dispatch import PacketId
from red_scribble.dispatch import RedScribbleDeps
from red_scribble.dispatch import SavedScribble
from red_scribble.dispatch import build_feedback_message
from red_scribble.dispatch import route
from red_scribble.dispatch import save_packet

# A 1x1 transparent PNG.
_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


class _Recorder:
    """Captures deliveries so tests can assert what reached the agent."""

    def __init__(self, agents: tuple[AgentSummary, ...]) -> None:
        self.agents = agents
        self.delivered: list[tuple[str, str]] = []

    def deliver(self, agent_id: str, message: str) -> bool:
        self.delivered.append((agent_id, message))
        return True


def _make_deps(tmp_path: Path, recorder: _Recorder, with_plugin: bool = True) -> RedScribbleDeps:
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    if with_plugin:
        (assets_dir / "plugin.js").write_text("console.log('red scribble');")
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    return RedScribbleDeps(
        assets_dir=assets_dir,
        storage_dir=storage_dir,
        list_agents=lambda: recorder.agents,
        deliver=recorder.deliver,
    )


def _set_config(deps: RedScribbleDeps, config: RedScribbleConfig) -> None:
    save_config(config, deps.storage_dir / CONFIG_FILENAME)


def test_get_config_reports_state_and_agents(tmp_path: Path) -> None:
    recorder = _Recorder(
        (AgentSummary("a1", "interview-box", "running"), AgentSummary("a2", "admin", "stopped"))
    )
    deps = _make_deps(tmp_path, recorder)
    _set_config(deps, RedScribbleConfig(target_agent_id="a1", mode="live"))
    resp = route("GET", "config", b"", "interview-bot", deps)
    payload = json.loads(resp.body)
    assert resp.status_code == 200
    assert payload["enabled"] is True
    assert payload["target_agent_id"] == "a1"
    assert payload["mode"] == "live"
    assert [a["name"] for a in payload["agents"]] == ["interview-box", "admin"]


def test_post_config_updates_mode_and_target(tmp_path: Path) -> None:
    recorder = _Recorder(())
    deps = _make_deps(tmp_path, recorder)
    _set_config(deps, RedScribbleConfig(target_agent_id="a1", mode="batch"))
    body = json.dumps({"mode": "live", "target_agent_id": "a2"}).encode()
    resp = route("POST", "config", body, "interview-bot", deps)
    assert resp.status_code == 200
    persisted = load_config(deps.storage_dir / CONFIG_FILENAME)
    assert persisted.mode == "live"
    assert persisted.target_agent_id == "a2"


def test_post_config_ignores_unknown_mode(tmp_path: Path) -> None:
    recorder = _Recorder(())
    deps = _make_deps(tmp_path, recorder)
    _set_config(deps, RedScribbleConfig(target_agent_id="a1", mode="batch"))
    resp = route("POST", "config", json.dumps({"mode": "bogus"}).encode(), "app", deps)
    assert resp.status_code == 200
    assert load_config(deps.storage_dir / CONFIG_FILENAME).mode == "batch"


def test_get_plugin_js_serves_asset(tmp_path: Path) -> None:
    deps = _make_deps(tmp_path, _Recorder(()))
    resp = route("GET", "plugin.js", b"", "app", deps)
    assert resp.status_code == 200
    assert resp.content_type == "application/javascript; charset=utf-8"
    assert b"red scribble" in resp.body


def test_get_plugin_js_missing_is_404(tmp_path: Path) -> None:
    deps = _make_deps(tmp_path, _Recorder(()), with_plugin=False)
    resp = route("GET", "plugin.js", b"", "app", deps)
    assert resp.status_code == 404


def test_serves_allowlisted_voice_modules(tmp_path: Path) -> None:
    deps = _make_deps(tmp_path, _Recorder(()))
    (deps.assets_dir / "voice_session.js").write_text("// session")
    (deps.assets_dir / "voice_capture.js").write_text("// capture")
    for name in ("voice_session.js", "voice_capture.js"):
        resp = route("GET", name, b"", "app", deps)
        assert resp.status_code == 200
        assert resp.content_type == "application/javascript; charset=utf-8"


def test_non_allowlisted_asset_is_404_even_if_present(tmp_path: Path) -> None:
    deps = _make_deps(tmp_path, _Recorder(()))
    # A file that exists in the assets dir but is not on the allowlist must not be served.
    (deps.assets_dir / "secret.js").write_text("// not for the web")
    resp = route("GET", "secret.js", b"", "app", deps)
    assert resp.status_code == 404


def test_feedback_persists_and_delivers_when_on(tmp_path: Path) -> None:
    recorder = _Recorder(())
    deps = _make_deps(tmp_path, recorder)
    _set_config(deps, RedScribbleConfig(target_agent_id="a1", mode="batch"))
    packet = {"kind": "text", "text": "make this button bigger", "page_url": "http://x/"}
    resp = route("POST", "feedback", json.dumps({"scribbles": [packet]}).encode(), "interview-bot", deps)
    payload = json.loads(resp.body)
    assert payload["status"] == "ok"
    assert payload["delivered"] is True
    # The raw packet is persisted, provenance included.
    stored = json.loads((deps.storage_dir / "packets" / f"{payload['packet_ids'][0]}.json").read_text())
    assert stored["app"] == "interview-bot"
    assert stored["text"] == "make this button bigger"
    # The agent got a message routed to the target.
    assert recorder.delivered[0][0] == "a1"
    assert "make this button bigger" in recorder.delivered[0][1]


def test_feedback_persisted_but_not_delivered_when_off(tmp_path: Path) -> None:
    recorder = _Recorder(())
    deps = _make_deps(tmp_path, recorder)
    # No config file -> off.
    resp = route("POST", "feedback", json.dumps({"scribbles": [{"kind": "stroke"}]}).encode(), "app", deps)
    payload = json.loads(resp.body)
    assert payload["delivered"] is False
    assert (deps.storage_dir / "packets" / f"{payload['packet_ids'][0]}.json").is_file()
    assert recorder.delivered == []


def test_feedback_invalid_json_is_400(tmp_path: Path) -> None:
    deps = _make_deps(tmp_path, _Recorder(()))
    _set_config(deps, RedScribbleConfig(target_agent_id="a1"))
    resp = route("POST", "feedback", b"{not json", "app", deps)
    assert resp.status_code == 400


def test_feedback_rejects_non_envelope_bodies(tmp_path: Path) -> None:
    deps = _make_deps(tmp_path, _Recorder(()))
    # A bare packet (the pre-envelope shape), an empty envelope, and a non-list are all rejected.
    for body in ({"kind": "text"}, {"scribbles": []}, {"scribbles": "x"}, {"scribbles": [1]}):
        assert route("POST", "feedback", json.dumps(body).encode(), "app", deps).status_code == 400


def test_envelope_screenshot_is_stored_once_and_referenced_once(tmp_path: Path) -> None:
    """A send's single screenshot lands as one .png and one message line, shared by all scribbles."""
    recorder = _Recorder(())
    deps = _make_deps(tmp_path, recorder)
    _set_config(deps, RedScribbleConfig(target_agent_id="a1", mode="batch"))
    envelope = {
        "scribbles": [
            {"kind": "stroke", "strokes": [[{"x": 1, "y": 2}]]},
            {"kind": "stroke", "strokes": [[{"x": 3, "y": 4}]]},
        ],
        "screenshot_png_base64": _PNG_B64,
    }
    resp = route("POST", "feedback", json.dumps(envelope).encode(), "app", deps)
    payload = json.loads(resp.body)
    pngs = list((deps.storage_dir / "packets").glob("*.png"))
    assert [p.name for p in pngs] == [f"{payload['packet_ids'][0]}.png"]
    message = recorder.delivered[0][1]
    root = ET.fromstring(message)
    assert root.get("screenshot") == str(pngs[0])   # named once, on the envelope
    assert not any(s.get("screenshot") for s in root)   # never repeated per scribble


def test_envelope_without_screenshot_has_no_screenshot_line(tmp_path: Path) -> None:
    recorder = _Recorder(())
    deps = _make_deps(tmp_path, recorder)
    _set_config(deps, RedScribbleConfig(target_agent_id="a1", mode="batch"))
    envelope = {"scribbles": [{"kind": "text", "text": "hi"}]}
    route("POST", "feedback", json.dumps(envelope).encode(), "app", deps)
    assert ET.fromstring(recorder.delivered[0][1]).get("screenshot") is None


def test_envelope_of_scribbles_is_one_delivery(tmp_path: Path) -> None:
    """A send operation's whole envelope becomes ONE message and ONE deliver call."""
    recorder = _Recorder(())
    deps = _make_deps(tmp_path, recorder)
    _set_config(deps, RedScribbleConfig(target_agent_id="a1", mode="live"))
    envelope = {
        "scribbles": [
            {"kind": "stroke", "strokes": [[{"x": 1, "y": 2}]], "page_url": "http://x/"},
            {"kind": "text", "text": "move this left", "page_url": "http://x/"},
            {"kind": "voice", "transcript": "make it red", "page_url": "http://x/"},
        ]
    }
    resp = route("POST", "feedback", json.dumps(envelope).encode(), "scribble-box", deps)
    payload = json.loads(resp.body)
    assert payload["delivered"] is True
    assert len(payload["packet_ids"]) == 3
    # Each scribble is persisted and registered individually (closeable one by one)...
    for packet_id in payload["packet_ids"]:
        assert (deps.storage_dir / "packets" / f"{packet_id}.json").is_file()
    scribbles = json.loads(route("GET", "scribbles", b"", "app", deps).body)["scribbles"]
    assert [s["id"] for s in scribbles] == payload["packet_ids"]
    # ...but the agent hears about all of them exactly once, as one tagged document.
    assert len(recorder.delivered) == 1
    message = recorder.delivered[0][1]
    root = ET.fromstring(message)
    assert root.tag == "red-scribble-feedback"
    assert root.get("mode") == "live"
    assert root.get("app") == "scribble-box"
    assert root.get("count") == "3"
    children = list(root)
    assert [c.get("id") for c in children] == payload["packet_ids"]
    assert [c.get("kind") for c in children] == ["stroke", "text", "voice"]
    assert children[1].text == "move this left"
    assert children[2].text == "make it red"


# Third-party code we vendor rather than author. It is not held to the ASCII rule below --
# we do not get to choose its bytes -- which is exactly why every asset is served with an
# explicit charset.
_VENDORED_ASSETS = frozenset({"html2canvas.js"})


def test_hand_written_js_assets_are_pure_ascii() -> None:
    """Every plug-in asset we author must be pure ASCII, so its source reads the same anywhere.

    These run inside arbitrary third-party app pages, and a raw glyph is easy to mangle in
    transit through an editor, a diff, or a copy into another repo -- mojibake for a display
    glyph, or a broken character class for logic (e.g. the voice ``_PUNCT`` regex). Writing
    ``\\uXXXX`` escapes instead keeps the source unambiguous. This test is the guard on that
    invariant, so a raw glyph can never be reintroduced unnoticed.
    """
    assets_dir = Path(dispatch.__file__).parent / "assets"
    offenders = {
        name: [i for i, byte in enumerate((assets_dir / name).read_bytes()) if byte > 0x7F]
        for name in dispatch.SERVED_ASSETS - _VENDORED_ASSETS
    }
    non_ascii = {name: positions for name, positions in offenders.items() if positions}
    assert not non_ascii, f"authored assets must be pure ASCII; non-ASCII byte offsets: {non_ascii}"


def test_served_js_assets_declare_utf8(tmp_path: Path) -> None:
    """A served asset names its own charset, so the embedding page's charset cannot corrupt it.

    Vendored third-party code contains non-ASCII bytes we do not control, and the plug-in is
    loaded by pages that may declare any charset at all (or none).
    """
    deps = _make_deps(tmp_path, _Recorder(()))
    for name in dispatch.SERVED_ASSETS:
        (deps.assets_dir / name).write_text("// served")
        resp = route("GET", name, b"", "app", deps)
        assert resp.status_code == 200, name
        assert resp.content_type == "application/javascript; charset=utf-8", name


def test_unknown_route_is_404(tmp_path: Path) -> None:
    deps = _make_deps(tmp_path, _Recorder(()))
    resp = route("GET", "nope", b"", "app", deps)
    assert resp.status_code == 404


def test_save_packet_stores_screenshot_once_as_png(tmp_path: Path) -> None:
    packet = {"kind": "stroke", "screenshot_png_base64": _PNG_B64}
    packet_id, raw_path = save_packet(tmp_path, "interview-bot", packet)
    stored = json.loads(raw_path.read_text())
    # The image is a sibling .png referenced by name; the base64 blob is not duplicated in the JSON.
    assert stored["screenshot"] == f"{packet_id}.png"
    assert "screenshot_png_base64" not in stored
    png_path = tmp_path / "packets" / f"{packet_id}.png"
    assert png_path.read_bytes() == base64.b64decode(_PNG_B64)


def test_save_packet_keeps_undecodable_screenshot_in_json(tmp_path: Path) -> None:
    packet = {"kind": "stroke", "screenshot_png_base64": "!!not base64!!"}
    _packet_id, raw_path = save_packet(tmp_path, "app", packet)
    stored = json.loads(raw_path.read_text())
    # Undecodable image is not discarded: it stays in the JSON rather than becoming a .png ref.
    assert stored["screenshot_png_base64"] == "!!not base64!!"
    assert "screenshot" not in stored


def test_save_packet_externalizes_single_audio_wav(tmp_path: Path) -> None:
    wav = base64.b64encode(b"fake-wav-bytes").decode()
    packet_id, raw_path = save_packet(tmp_path, "app", {"kind": "voice", "audio_wav_base64": wav})
    stored = json.loads(raw_path.read_text())
    assert stored["audio"] == f"{packet_id}.wav"
    assert "audio_wav_base64" not in stored
    assert (tmp_path / "packets" / f"{packet_id}.wav").read_bytes() == b"fake-wav-bytes"


def test_save_packet_externalizes_multiple_audio_wavs(tmp_path: Path) -> None:
    wavs = [base64.b64encode(b"one").decode(), base64.b64encode(b"two").decode()]
    packet_id, raw_path = save_packet(tmp_path, "app", {"kind": "voice", "audio_wav_base64": wavs})
    stored = json.loads(raw_path.read_text())
    assert stored["audio"] == [f"{packet_id}-0.wav", f"{packet_id}-1.wav"]
    assert (tmp_path / "packets" / f"{packet_id}-0.wav").read_bytes() == b"one"
    assert (tmp_path / "packets" / f"{packet_id}-1.wav").read_bytes() == b"two"


def test_feedback_registers_an_open_scribble(tmp_path: Path) -> None:
    deps = _make_deps(tmp_path, _Recorder(()))
    resp = route("POST", "feedback", json.dumps({"scribbles": [{"kind": "stroke"}]}).encode(), "interview-bot", deps)
    packet_id = json.loads(resp.body)["packet_ids"][0]
    scribbles = json.loads(route("GET", "scribbles", b"", "app", deps).body)["scribbles"]
    assert [(s["id"], s["status"], s["kind"]) for s in scribbles] == [(packet_id, "open", "stroke")]


def test_close_route_closes_scribble(tmp_path: Path) -> None:
    deps = _make_deps(tmp_path, _Recorder(()))
    resp = route("POST", "feedback", json.dumps({"scribbles": [{"kind": "stroke"}]}).encode(), "app", deps)
    packet_id = json.loads(resp.body)["packet_ids"][0]
    closed = json.loads(route("POST", "close", json.dumps({"ids": [packet_id]}).encode(), "app", deps).body)
    assert closed["closed"] == [packet_id]
    scribbles = json.loads(route("GET", "scribbles", b"", "app", deps).body)["scribbles"]
    assert scribbles[0]["status"] == "closed"


def test_close_route_rejects_bad_body(tmp_path: Path) -> None:
    deps = _make_deps(tmp_path, _Recorder(()))
    assert route("POST", "close", json.dumps({"ids": "x"}).encode(), "app", deps).status_code == 400
    assert route("POST", "close", b"{not json", "app", deps).status_code == 400


def test_build_message_is_terse_and_delegates_to_the_skill() -> None:
    packet = {"kind": "text", "text": "note", "page_url": "http://x/"}
    saved = [SavedScribble(packet=packet, packet_id=PacketId.generate(), raw_path=Path("/tmp/x.json"))]

    live = build_feedback_message(saved, RedScribbleConfig(mode="live"), "app")
    root = ET.fromstring(live)
    assert root.get("mode") == "live"
    assert root.get("count") == "1"
    assert "/red-scribble-feedback" in live            # the playbook is delegated to the skill
    assert list(root)[0].get("id") == str(saved[0].packet_id)
    assert list(root)[0].text == "note"
    # The verbose boilerplate now lives in the skill, not in every message.
    assert "Distill the user's intent" not in live
    assert "red-scribble close" not in live
    assert "red-scribble-live-" not in live

    batch = build_feedback_message(saved, RedScribbleConfig(mode="batch"), "app")
    assert ET.fromstring(batch).get("mode") == "batch"
    assert "/red-scribble-feedback" in batch


def test_build_message_is_well_formed_with_hostile_content() -> None:
    """Anchors and notes full of XML metacharacters must still yield a parseable document."""
    packet = {
        "kind": "text",
        "text": 'make it <bigger> & "bolder"',
        "anchor": 'div[data-x="1"] > span < & "q"',
        "page_url": "http://x/?a=1&b=2",
        "point": {"x": 1, "y": 2},
    }
    saved = [SavedScribble(packet=packet, packet_id=PacketId.generate(), raw_path=Path("/tmp/x.json"))]
    message = build_feedback_message(saved, RedScribbleConfig(mode="batch"), "app")
    root = ET.fromstring(message)
    child = list(root)[0]
    assert child.text == 'make it <bigger> & "bolder"'
    assert child.get("anchor") == 'div[data-x="1"] > span < & "q"'
    assert child.get("page") == "http://x/?a=1&b=2"


def test_build_message_names_every_attribute_the_chat_card_reads() -> None:
    """The envelope's attribute names are a cross-language contract.

    The chat view's parser (``system_interface``'s ``frontend/src/views/red-scribble.ts``)
    reads these names out of the document this builder emits, so renaming one degrades every
    batch card back to a raw XML bubble. The envelope's routing attributes are already pinned
    by ``test_envelope_of_scribbles_is_one_delivery``; what that leaves unguarded is the set
    the card *renders* -- ``screenshot`` (the header's affordance), ``strokes`` (the "N
    strokes" tile label), and ``point``/``raw`` (rows of the hover detail card). Those are
    covered end-to-end against this builder only by a release-marked Playwright test, so pin
    them here too, where an ordinary test run catches the rename.
    """
    stroke = {"kind": "stroke", "point": {"x": 1.5, "y": 2.5}, "strokes": [[[0, 0]], [[1, 1]]]}
    note = {"kind": "voice", "transcript": "make it louder"}
    saved = [
        SavedScribble(packet=stroke, packet_id=PacketId.generate(), raw_path=Path("/tmp/1.json")),
        SavedScribble(packet=note, packet_id=PacketId.generate(), raw_path=Path("/tmp/2.json")),
    ]
    root = ET.fromstring(
        build_feedback_message(saved, RedScribbleConfig(mode="batch"), "scribble-box", Path("/tmp/shot.png"))
    )

    assert root.tag == "red-scribble-feedback"
    assert root.get("mode") == "batch"
    assert root.get("app") == "scribble-box"
    assert root.get("screenshot") == "/tmp/shot.png"

    # A stroke group: self-closing, carrying its stroke count and no note text.
    stroke_element, note_element = list(root)
    assert stroke_element.tag == "scribble"
    assert stroke_element.get("kind") == "stroke"
    assert stroke_element.get("point") == "1.5,2.5"
    assert stroke_element.get("strokes") == "2"
    assert stroke_element.get("raw") == "/tmp/1.json"
    assert not (stroke_element.text or "").strip()

    # A note: its text is element content, and it carries no stroke count.
    assert note_element.get("kind") == "voice"
    assert note_element.text == "make it louder"
    assert note_element.get("strokes") is None

    # The screenshot attribute is genuinely optional -- absent, not empty.
    without = ET.fromstring(build_feedback_message(saved, RedScribbleConfig(mode="live"), "notes"))
    assert without.get("screenshot") is None
    assert without.get("mode") == "live"


# The chat app's e2e suite renders this library's feedback document from a checked-in copy
# (the chat's venv does not hold this standalone library), so this test holds that copy to
# what ``build_feedback_message`` builds today from the same inputs.
_CHAT_FIXTURE = (
    Path(__file__).resolve().parents[4] / "apps/chat/imbue/chat/testdata/red_scribble_feedback.xml"
)


def test_build_feedback_message_still_matches_the_chat_apps_fixture() -> None:
    def packet_id(number: int) -> PacketId:
        return PacketId(f"fbk-{number:032x}")

    saved = [
        SavedScribble(
            packet={
                "kind": "stroke",
                "point": {"x": 534.19, "y": 86.38},
                "anchor": "html > body > main",
                "strokes": [[[1, 2]]],
                "page_url": "https://example/app",
            },
            packet_id=packet_id(1),
            raw_path=Path("/abs/1.json"),
        ),
        SavedScribble(
            packet={
                "kind": "voice",
                "point": {"x": 590.61, "y": 116.48},
                "anchor": "main > div",
                "transcript": "I want an earthquake",
                "page_url": "https://example/app",
            },
            packet_id=packet_id(2),
            raw_path=Path("/abs/2.json"),
        ),
        SavedScribble(
            packet={
                "kind": "text",
                "point": {"x": 618.27, "y": 159.35},
                "anchor": "main > div",
                "text": "earthquake button",
                "page_url": "https://example/app",
            },
            packet_id=packet_id(3),
            raw_path=Path("/abs/3.json"),
        ),
    ]
    config = RedScribbleConfig(target_agent_id="agent-test-123", mode="batch")

    built = build_feedback_message(saved, config, "scribble-box", Path("/abs/shot.png"))

    assert built == _CHAT_FIXTURE.read_text(), (
        f"the feedback document changed; write the new one to {_CHAT_FIXTURE} so the chat's "
        "e2e test renders what the library sends"
    )
