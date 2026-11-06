#!/usr/bin/env python3
"""Add (or remove) an app's Red Scribble opt-in, idempotently.

The opt-in is two mechanical edits plus one wiring line:

1. the app depends on ``red-scribble`` (its server has to look up Red Scribble's
   deliberately unguessable origin in the service registry);
2. the app's HTML template emits ``{{ red_scribble_tag() }}`` in its ``<head>``;
3. the app's Flask module registers the Jinja helper and renders the page through Jinja.

This script does 1 and 2 and *reports* on 3, which it never edits: an app's request handler is
hand-written and rewriting it blind is how a working app gets broken. Running it twice changes
nothing the second time.

Usage:
    opt_in_app.py --list                 # apps that could take Red Scribble, and which have it
    opt_in_app.py <app> [--check]        # apply the opt-in (or just report on it)
    opt_in_app.py <app> --remove         # take the opt-in back out
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Final

import tomlkit
from tomlkit.items import Array, Table

APPS_DIR: Final[str] = "system/apps"
DEPENDENCY_NAME: Final[str] = "red-scribble"
TEMPLATE_TAG: Final[str] = "{{ red_scribble_tag() }}"
HELPER_IMPORT: Final[str] = "from red_scribble.embed import register_jinja_helper"
HELPER_CALL: Final[str] = "register_jinja_helper("
# An app under system/apps is a standalone uv project, so it takes the library from its
# checkout through an editable path source of its own (the root workspace gives it nothing).
LIBRARY_SOURCE: Final[dict[str, object]] = {"path": "../../libs/red_scribble", "editable": True}

# The apps that serve the workspace itself rather than a page someone iterates on. None is a
# Flask template this skill could edit, and none is a surface Red Scribble is meant for. ``chat``
# is here for the same reason as ``system_interface`` -- this workspace splits the chat out of the
# shell into its own app, and it is also where feedback is delivered, so scribbling on it would
# feed the surface back into itself.
EXCLUDED_APPS: Final[frozenset[str]] = frozenset({"system_interface", "chat", "red_scribble", "terminal"})

_HEAD_CLOSE: Final[str] = "</head>"

# Directories whose HTML is not the app's page: installed packages and anything a frontend build
# produced or vendored. Without this, an app with a built frontend has hundreds of candidate
# pages and the search either refuses it or picks a third party's.
_NOT_THE_APPS_OWN: Final[frozenset[str]] = frozenset(
    {".venv", "venv", "node_modules", "dist", "build", "site-packages", "__pycache__", ".git"}
)


class OptInError(Exception):
    """Raised when an app cannot take the Red Scribble opt-in."""


def _repo_root(start: Path) -> Path:
    for candidate in (start.resolve(), *start.resolve().parents):
        if (candidate / "system" / "supervisord.conf").exists():
            return candidate
    raise OptInError("could not locate the repo root (no system/supervisord.conf above cwd)")


def app_directory(repo_root: Path, app_name: str) -> Path:
    """The package directory for a registered app name, which may be kebab- or snake-cased."""
    for candidate_name in (app_name.replace("-", "_"), app_name):
        candidate = repo_root / APPS_DIR / candidate_name
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise OptInError(
        f"no app package for {app_name!r} under {APPS_DIR}/ "
        "(expected a directory with a pyproject.toml)"
    )


def _read_text_or_empty(path: Path) -> str:
    """A file's text, or ``""`` when it will not decode as text.

    An app's tree can hold anything; a file that will not decode is certainly not the page whose
    ``<head>`` we are about to edit, nor the module that wires the helper, so it drops out of the
    search rather than ending the run in a traceback.
    """
    try:
        return path.read_text()
    except (UnicodeDecodeError, OSError):
        return ""


def _own_html_files(app_dir: Path) -> list[Path]:
    """Every HTML file the app itself wrote, skipping vendored and generated trees."""
    return [
        path
        for path in app_dir.rglob("*.html")
        if not _NOT_THE_APPS_OWN.intersection(path.relative_to(app_dir).parts)
    ]


def find_page_template(app_dir: Path) -> Path:
    """The app's one HTML page, identified by having a ``</head>`` to insert into."""
    candidates = sorted(path for path in _own_html_files(app_dir) if _HEAD_CLOSE in _read_text_or_empty(path))
    if not candidates:
        raise OptInError(
            f"{app_dir} has no HTML template with a </head> to put the tag in -- this app "
            "probably builds its page some other way, so add the tag by hand"
        )
    if len(candidates) > 1:
        listed = ", ".join(str(path.relative_to(app_dir)) for path in candidates)
        raise OptInError(
            f"{app_dir} has more than one HTML template ({listed}) -- add the tag by hand to "
            "whichever one is the page you want to scribble on"
        )
    return candidates[0]


def _python_sources(app_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in app_dir.rglob("*.py")
        if not path.name.endswith("_test.py")
        and not _NOT_THE_APPS_OWN.intersection(path.relative_to(app_dir).parts)
    )


def is_helper_wired(app_dir: Path) -> bool:
    """Whether some module in the app both imports the Jinja helper and calls it."""
    return any(
        HELPER_IMPORT in text and HELPER_CALL in text
        for text in (_read_text_or_empty(source) for source in _python_sources(app_dir))
    )


def _dependencies(pyproject_path: Path) -> tuple[tomlkit.TOMLDocument, Array]:
    document = tomlkit.parse(pyproject_path.read_text())
    project = document.get("project")
    if not isinstance(project, Table):
        raise OptInError(f"{pyproject_path} has no [project] table")
    dependencies = project.get("dependencies")
    if not isinstance(dependencies, Array):
        raise OptInError(f"{pyproject_path} has no [project].dependencies array")
    return document, dependencies


def _has_dependency(dependencies: Array) -> bool:
    return any(str(entry).split(">")[0].split("=")[0].strip() == DEPENDENCY_NAME for entry in dependencies)


def _uv_sources(document: tomlkit.TOMLDocument) -> Table:
    tool = document.setdefault("tool", tomlkit.table(is_super_table=True))
    uv = tool.setdefault("uv", tomlkit.table(is_super_table=True))
    return uv.setdefault("sources", tomlkit.table())


def _has_source(document: tomlkit.TOMLDocument) -> bool:
    sources = document.get("tool", {}).get("uv", {}).get("sources", {})
    return DEPENDENCY_NAME in sources


def add_dependency(pyproject_path: Path) -> bool:
    """Declare the ``red-scribble`` dependency and its path source. Returns whether anything changed."""
    document, dependencies = _dependencies(pyproject_path)
    if _has_dependency(dependencies) and _has_source(document):
        return False
    if not _has_dependency(dependencies):
        dependencies.append(DEPENDENCY_NAME)
    if not _has_source(document):
        source = tomlkit.inline_table()
        source.update(LIBRARY_SOURCE)
        _uv_sources(document)[DEPENDENCY_NAME] = source
    pyproject_path.write_text(tomlkit.dumps(document))
    return True


def remove_dependency(pyproject_path: Path) -> bool:
    document, dependencies = _dependencies(pyproject_path)
    if not _has_dependency(dependencies) and not _has_source(document):
        return False
    for index in reversed(range(len(dependencies))):
        if str(dependencies[index]).split(">")[0].split("=")[0].strip() == DEPENDENCY_NAME:
            del dependencies[index]
    if _has_source(document):
        sources = _uv_sources(document)
        del sources[DEPENDENCY_NAME]
        if not sources:
            del document["tool"]["uv"]["sources"]
            if not document["tool"]["uv"]:
                del document["tool"]["uv"]
            if not document["tool"]:
                del document["tool"]
    pyproject_path.write_text(tomlkit.dumps(document))
    return True


def add_template_tag(template_path: Path) -> bool:
    """Emit the plug-in's tag from the page's ``<head>``. Returns whether anything changed."""
    markup = template_path.read_text()
    if TEMPLATE_TAG in markup:
        return False
    template_path.write_text(markup.replace(_HEAD_CLOSE, f"  {TEMPLATE_TAG}\n{_HEAD_CLOSE}", 1))
    return True


def remove_template_tag(template_path: Path) -> bool:
    markup = template_path.read_text()
    if TEMPLATE_TAG not in markup:
        return False
    without_tag = re.sub(r"[ \t]*" + re.escape(TEMPLATE_TAG) + r"\n?", "", markup)
    template_path.write_text(without_tag)
    return True


def _describe(repo_root: Path, path: Path) -> str:
    return str(path.relative_to(repo_root))


def list_candidate_apps(repo_root: Path) -> int:
    """Print every app that could take Red Scribble, and whether it already has it."""
    apps_dir = repo_root / APPS_DIR
    for app_dir in sorted(path for path in apps_dir.iterdir() if path.is_dir()):
        if app_dir.name in EXCLUDED_APPS or not (app_dir / "pyproject.toml").is_file():
            continue
        service_name = app_dir.name.replace("_", "-")
        try:
            template_path = find_page_template(app_dir)
        except OptInError as error:
            # The reason itself, not a guess at it: "no page" and "several pages" need different
            # things done about them, and this listing is what the agent reads before deciding.
            print(f"{service_name}\topt in by hand\t{error}")
            continue
        is_opted_in = TEMPLATE_TAG in template_path.read_text()
        print(f"{service_name}\t{'on' if is_opted_in else 'off'}\t{_describe(repo_root, template_path)}")
    return 0


def apply_opt_in(repo_root: Path, app_name: str, is_check_only: bool, is_removal: bool) -> int:
    app_dir = app_directory(repo_root, app_name)
    pyproject_path = app_dir / "pyproject.toml"
    template_path = find_page_template(app_dir)

    if is_check_only:
        has_dependency = _has_dependency(_dependencies(pyproject_path)[1])
        has_tag = TEMPLATE_TAG in template_path.read_text()
        print(f"dependency\t{'present' if has_dependency else 'missing'}\t{_describe(repo_root, pyproject_path)}")
        print(f"template tag\t{'present' if has_tag else 'missing'}\t{_describe(repo_root, template_path)}")
        print(f"jinja helper\t{'wired' if is_helper_wired(app_dir) else 'not wired'}\t{_describe(repo_root, app_dir)}")
        return 0

    if is_removal:
        print(f"dependency\t{'removed' if remove_dependency(pyproject_path) else 'was not there'}")
        print(f"template tag\t{'removed' if remove_template_tag(template_path) else 'was not there'}")
        if is_helper_wired(app_dir):
            print(
                "jinja helper\tstill wired -- harmless (it renders nothing while Red Scribble is "
                f"off), remove it by hand from {_describe(repo_root, app_dir)} if you want it gone"
            )
        return 0

    print(f"dependency\t{'added' if add_dependency(pyproject_path) else 'already there'}\t{_describe(repo_root, pyproject_path)}")
    print(f"template tag\t{'added' if add_template_tag(template_path) else 'already there'}\t{_describe(repo_root, template_path)}")
    if is_helper_wired(app_dir):
        print(f"jinja helper\talready wired\t{_describe(repo_root, app_dir)}")
        return 0
    print(
        "jinja helper\tNOT WIRED -- add these to the module that builds the Flask app, and make "
        "the page route render through Jinja (render_template_string) so the tag is evaluated:\n"
        f"    {HELPER_IMPORT}\n"
        "    register_jinja_helper(app)"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Add or remove an app's Red Scribble opt-in.")
    parser.add_argument("app", nargs="?", help="the app's name, e.g. scribble-box")
    parser.add_argument("--list", action="store_true", help="list apps that could take Red Scribble")
    parser.add_argument("--check", action="store_true", help="report the opt-in's state, change nothing")
    parser.add_argument("--remove", action="store_true", help="take the opt-in back out")
    args = parser.parse_args()

    try:
        repo_root = _repo_root(Path.cwd())
        if args.list:
            return list_candidate_apps(repo_root)
        if not args.app:
            parser.error("name an app, or pass --list to see the candidates")
        return apply_opt_in(repo_root, args.app, args.check, args.remove)
    except OptInError as error:
        sys.stderr.write(f"error: {error}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
