"""Tests for ``opt_in_app.py``.

Run via: ``uv run --no-sync pytest .agents/skills/enable-red-scribble/python``

The property that matters is idempotence: the skill is the thing a user re-runs when they are
not sure whether Red Scribble is already on, so a second application must not duplicate the tag,
duplicate the dependency, or otherwise disturb the app. Each test builds a throwaway app tree
rather than touching a real one.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from enable_red_scribble_skill import opt_in_app


_PYPROJECT = """[project]
name = "demo-app"
version = "0.1.0"
dependencies = [
    "flask>=3.0",
]
"""

_PAGE = """<!doctype html>
<html>
<head>
  <title>Demo</title>
</head>
<body>hello</body>
</html>
"""


def _build_app(repo_root: Path, package_name: str = "demo_app") -> Path:
    (repo_root / "system").mkdir(parents=True, exist_ok=True)
    (repo_root / "system" / "supervisord.conf").write_text("")
    app_dir = repo_root / "system" / "apps" / package_name
    assets_dir = app_dir / "src" / package_name / "assets"
    assets_dir.mkdir(parents=True)
    (app_dir / "pyproject.toml").write_text(_PYPROJECT)
    (assets_dir / "page.html").write_text(_PAGE)
    (app_dir / "src" / package_name / "runner.py").write_text("app = None\n")
    return app_dir


def test_opt_in_adds_the_dependency_and_the_tag(tmp_path: Path) -> None:
    app_dir = _build_app(tmp_path)

    opt_in_app.apply_opt_in(tmp_path, "demo-app", is_check_only=False, is_removal=False)

    pyproject = tomllib.loads((app_dir / "pyproject.toml").read_text())
    assert "red-scribble" in pyproject["project"]["dependencies"]
    # A standalone app takes the library from the checkout, through a path source of its own.
    assert pyproject["tool"]["uv"]["sources"]["red-scribble"] == {
        "path": "../../libs/red_scribble",
        "editable": True,
    }
    page = (app_dir / "src" / "demo_app" / "assets" / "page.html").read_text()
    assert "{{ red_scribble_tag() }}" in page
    assert page.index("{{ red_scribble_tag() }}") < page.index("</head>")


def test_opting_in_twice_changes_nothing_the_second_time(tmp_path: Path) -> None:
    app_dir = _build_app(tmp_path)
    opt_in_app.apply_opt_in(tmp_path, "demo-app", is_check_only=False, is_removal=False)
    after_first = (
        (app_dir / "pyproject.toml").read_text(),
        (app_dir / "src" / "demo_app" / "assets" / "page.html").read_text(),
    )

    opt_in_app.apply_opt_in(tmp_path, "demo-app", is_check_only=False, is_removal=False)

    assert after_first == (
        (app_dir / "pyproject.toml").read_text(),
        (app_dir / "src" / "demo_app" / "assets" / "page.html").read_text(),
    )
    assert after_first[1].count("{{ red_scribble_tag() }}") == 1


def test_removing_the_opt_in_restores_the_original_files(tmp_path: Path) -> None:
    app_dir = _build_app(tmp_path)
    opt_in_app.apply_opt_in(tmp_path, "demo-app", is_check_only=False, is_removal=False)

    opt_in_app.apply_opt_in(tmp_path, "demo-app", is_check_only=False, is_removal=True)

    assert "red-scribble" not in (app_dir / "pyproject.toml").read_text()
    assert (app_dir / "src" / "demo_app" / "assets" / "page.html").read_text() == _PAGE


def test_checking_reports_without_changing_anything(tmp_path: Path) -> None:
    app_dir = _build_app(tmp_path)

    opt_in_app.apply_opt_in(tmp_path, "demo-app", is_check_only=True, is_removal=False)

    assert "red-scribble" not in (app_dir / "pyproject.toml").read_text()
    assert (app_dir / "src" / "demo_app" / "assets" / "page.html").read_text() == _PAGE


def test_the_tag_goes_into_the_head_of_a_page_shaped_nothing_like_the_scribble_boxs(
    tmp_path: Path,
) -> None:
    """The apps this is pointed at are hand-written, so the edit must not assume a house style.

    A real one (the browser viewer) closes its ``<head>`` straight after a long inline
    ``<style>``, uses no Jinja constructs of its own, and is served by reading the file rather
    than rendering it -- so the tag has to land inside the head and leave the rest untouched.
    """
    app_dir = _build_app(tmp_path)
    page_path = app_dir / "src" / "demo_app" / "assets" / "page.html"
    unusual_page = (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8" />\n'
        "<style>\n  #app { color: #ddd; }\n</style>\n</head>\n"
        '<body>\n<div id="app"></div>\n<script>const t = `a ${1} b`;</script>\n</body>\n</html>\n'
    )
    page_path.write_text(unusual_page)

    opt_in_app.apply_opt_in(tmp_path, "demo-app", is_check_only=False, is_removal=False)

    updated = page_path.read_text()
    assert updated.index("{{ red_scribble_tag() }}") > updated.index("</style>")
    assert updated.index("{{ red_scribble_tag() }}") < updated.index("</head>")
    assert "const t = `a ${1} b`;" in updated
    opt_in_app.apply_opt_in(tmp_path, "demo-app", is_check_only=False, is_removal=True)
    assert page_path.read_text() == unusual_page


def test_html_a_frontend_build_produced_is_not_mistaken_for_the_apps_page(tmp_path: Path) -> None:
    """An app with a built frontend has plenty of HTML that is nobody's page to edit.

    Counting ``node_modules``/``dist`` output as candidates would make any such app either refuse
    the opt-in as ambiguous or, worse, put the tag in a vendored file where it renders as text.
    """
    app_dir = _build_app(tmp_path)
    for vendored in ("node_modules/pkg/demo.html", "dist/index.html", ".venv/share/doc/thing.html"):
        path = app_dir / vendored
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_PAGE)

    opt_in_app.apply_opt_in(tmp_path, "demo-app", is_check_only=False, is_removal=False)

    assert "{{ red_scribble_tag() }}" in (app_dir / "src" / "demo_app" / "assets" / "page.html").read_text()
    assert "{{ red_scribble_tag() }}" not in (app_dir / "dist" / "index.html").read_text()


def test_a_file_that_is_not_decodable_text_is_stepped_over_not_crashed_on(tmp_path: Path) -> None:
    """``.html`` is only a file name; the search must not die on whatever is actually in there."""
    app_dir = _build_app(tmp_path)
    (app_dir / "src" / "demo_app" / "assets" / "captured.html").write_bytes(b"\xff\xfe</head>\x00")

    opt_in_app.apply_opt_in(tmp_path, "demo-app", is_check_only=False, is_removal=False)

    assert "{{ red_scribble_tag() }}" in (app_dir / "src" / "demo_app" / "assets" / "page.html").read_text()


def test_an_app_with_several_pages_is_refused_and_the_listing_says_why(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Which page to scribble on is the author's call, and the listing has to say that.

    Reporting it as "no HTML page found" sends the reader looking for a page that is right there.
    """
    app_dir = _build_app(tmp_path)
    (app_dir / "src" / "demo_app" / "assets" / "settings.html").write_text(_PAGE)

    with pytest.raises(opt_in_app.OptInError, match="more than one HTML template"):
        opt_in_app.apply_opt_in(tmp_path, "demo-app", is_check_only=False, is_removal=False)

    opt_in_app.list_candidate_apps(tmp_path)
    listed = capsys.readouterr().out
    assert "more than one HTML template" in listed
    assert "settings.html" in listed


def test_an_app_with_no_html_page_is_refused_with_an_explanation(tmp_path: Path) -> None:
    app_dir = _build_app(tmp_path)
    (app_dir / "src" / "demo_app" / "assets" / "page.html").unlink()

    with pytest.raises(opt_in_app.OptInError, match="no HTML template"):
        opt_in_app.apply_opt_in(tmp_path, "demo-app", is_check_only=False, is_removal=False)


def test_an_unknown_app_is_refused_with_an_explanation(tmp_path: Path) -> None:
    _build_app(tmp_path)

    with pytest.raises(opt_in_app.OptInError, match="no app package"):
        opt_in_app.apply_opt_in(tmp_path, "nope", is_check_only=False, is_removal=False)


def test_the_jinja_helper_is_reported_as_wired_only_when_it_is_both_imported_and_called(
    tmp_path: Path,
) -> None:
    app_dir = _build_app(tmp_path)
    runner_path = app_dir / "src" / "demo_app" / "runner.py"

    runner_path.write_text("from red_scribble.embed import register_jinja_helper\n")
    assert not opt_in_app.is_helper_wired(app_dir)

    runner_path.write_text(
        "from red_scribble.embed import register_jinja_helper\n\nregister_jinja_helper(app)\n"
    )
    assert opt_in_app.is_helper_wired(app_dir)
