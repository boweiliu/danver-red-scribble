"""Unit tests for the registry lookups that decide who Red Scribble will talk to."""

from pathlib import Path

from red_scribble.origins import read_service_labels
from red_scribble.origins import service_name_for_origin

_APP_HOST = "scribble-box-3nbi4bp5.host-a1b2.localhost:8421"
_APP_ORIGIN = f"http://{_APP_HOST}"

_REGISTRY = """
[[apps]]
name = "scribble-box"
url = "http://localhost:8080"
label = "scribble-box-3nbi4bp5"

[[apps]]
name = "red-scribble"
url = "http://localhost:8082"
label = "red-scribble-9fk2ax7t"
"""


def _registry(tmp_path: Path) -> Path:
    path = tmp_path / "apps.toml"
    path.write_text(_REGISTRY)
    return path


def test_an_origin_resolves_to_the_service_name_the_registry_gives_it(tmp_path: Path) -> None:
    assert service_name_for_origin(_APP_ORIGIN, _registry(tmp_path)) == "scribble-box"


def test_an_unregistered_label_resolves_to_no_service(tmp_path: Path) -> None:
    assert service_name_for_origin("http://mystery-zz.host-a1b2.localhost:8421", _registry(tmp_path)) is None
    assert service_name_for_origin("https://evil.example.com", _registry(tmp_path)) is None


def test_an_unreadable_or_malformed_registry_reads_as_nothing_registered(tmp_path: Path) -> None:
    assert read_service_labels(tmp_path / "missing.toml") == {}
    broken = tmp_path / "broken.toml"
    broken.write_text("this is not = = toml")
    assert read_service_labels(broken) == {}
    unlabelled = tmp_path / "unlabelled.toml"
    unlabelled.write_text('[[apps]]\nname = "x"\nurl = "http://localhost:1"\n')
    assert read_service_labels(unlabelled) == {}


def test_a_deeper_sub_origin_belongs_to_no_registered_service(tmp_path: Path) -> None:
    """A sub-origin of another service is not a service in its own right.

    The forwarder routes deeper labels back to the owning service, so admitting one would widen
    who may message the user's agent. Nothing is looked up here: what follows ``sub`` is the app's
    own label, not a coordinate, so the origin never reaches the registry at all.
    """
    assert service_name_for_origin(f"http://sub.{_APP_HOST}", _registry(tmp_path)) is None


def test_a_registered_label_pinned_straight_onto_another_domain_belongs_to_no_service(
    tmp_path: Path,
) -> None:
    """A registered label with no coordinate-shaped label behind it is not a workspace origin.

    Anyone can put any hostname label in front of a domain they own. If a bare leading-label match
    were enough, a page at ``https://<a registered app label>.attacker.example`` would be
    authorized to POST feedback into the user's chat, and on the TLS path the workspace session
    cookie is ``SameSite=None`` -- so the browser would attach it and the send would land.
    """
    registry = _registry(tmp_path)
    for origin in (
        "https://scribble-box-3nbi4bp5.attacker.example",
        "http://scribble-box-3nbi4bp5.localhost:8421",
        "https://scribble-box-3nbi4bp5.host-not-hex.attacker.example",
    ):
        assert service_name_for_origin(origin, registry) is None, origin


def test_the_coordinate_is_checked_for_shape_only_so_the_label_is_the_secret(tmp_path: Path) -> None:
    """Where this boundary actually ends, pinned so nobody has to rediscover it.

    The coordinate cannot be checked against *ours*: the forwarder rewrites ``Host`` and the
    service never learns its own public origin, which is the premise the whole module rests on. So
    a caller who owns a domain can hang any ``host-<hex>`` label off it and satisfy the shape.
    What they still cannot do is guess the per-workspace service label, and that -- not the
    coordinate -- is what keeps a stranger out. This test asserts the permissive result on
    purpose; tightening it would refuse every share, whose coordinate tail is equally unknowable.
    """
    registry = _registry(tmp_path)
    for origin in (
        "https://scribble-box-3nbi4bp5.host-a1b2.attacker.example",
        "https://scribble-box-3nbi4bp5.host-deadbeef.evil.co.uk",
    ):
        assert service_name_for_origin(origin, registry) == "scribble-box", origin
    assert service_name_for_origin("https://not-a-registered-label.host-a1b2.attacker.example", registry) is None


def test_a_workspace_host_smuggled_into_userinfo_belongs_to_no_service(tmp_path: Path) -> None:
    """The authority is parsed strictly, so it cannot read as one host here and another in a browser.

    ``http://<workspace host>:8421@attacker.example`` is the attacker's origin; a parse that
    partitions on the first ``:`` or ``.`` sees the workspace host in front of it and admits it.
    """
    smuggled = f"http://{_APP_HOST}@attacker.example"
    assert service_name_for_origin(smuggled, _registry(tmp_path)) is None


def test_the_registered_service_is_found_however_the_origin_is_cased(tmp_path: Path) -> None:
    """Hostnames are case-insensitive, and a browser is not the only thing that sets this header."""
    assert service_name_for_origin(_APP_ORIGIN.upper(), _registry(tmp_path)) == "scribble-box"


def test_the_shared_workspace_coordinate_is_recognised_as_well_as_the_local_one(tmp_path: Path) -> None:
    """A shared workspace's coordinate is longer but the same shape, so the same rule covers it.

    Shares serve ``<label>.host-<hex>.<user>.<region>.<domain>`` (see the share gateway), which is
    the local ``<label>.host-<hex>.localhost:8421`` with a different tail.
    """
    shared = "https://scribble-box-3nbi4bp5.host-aaaa.bbbb.us1.imbueminds.com"
    assert service_name_for_origin(shared, _registry(tmp_path)) == "scribble-box"


def test_the_bare_workspace_origin_is_not_a_service(tmp_path: Path) -> None:
    """The coordinate on its own carries no service label, so it resolves to no service."""
    assert service_name_for_origin("http://host-a1b2.localhost:8421", _registry(tmp_path)) is None


def test_a_malformed_origin_belongs_to_no_service(tmp_path: Path) -> None:
    """``Origin`` is attacker-influenced, so anything that is not a plain http(s) origin is out."""
    registry = _registry(tmp_path)
    for origin in (
        "",
        "null",
        _APP_HOST,
        "file://x",
        f"http://{_APP_HOST}/path",
        "ftp://x.y.z",
        f"http://{_APP_HOST}:notaport",
        f"http://user:pass@{_APP_HOST}",
    ):
        assert service_name_for_origin(origin, registry) is None, origin
