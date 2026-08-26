"""Test helpers for exercising Red Scribble's browser-side code off the browser.

The one thing here is :func:`run_bootstrap`, which executes the snippet
:func:`red_scribble.embed.script_tag` emits against a stubbed ``location``/``document`` and
reports the script URL it decided to load. Asserting on the *emitted* snippet rather than a copy
of it keeps ``embed.py`` the single source of truth: the bootstrap's whole job is to compute one
URL from ``location``, and a test that only greps the string for ``location.hostname`` cannot tell
a correct derivation from a wrong one.
"""

import json
import shutil
import subprocess
from typing import Final

# The bootstrap only ever touches these two globals, so the stub is small enough to be obviously
# faithful: it records the src of whatever <script> the snippet appends, and reports the absence of
# one (the no-op case) as null.
_HARNESS: Final[str] = """\
var loaded = null;
var location = %(location)s;
var node = { set src(value) { loaded = value; }, get src() { return loaded; }, defer: false };
var document = {
  createElement: function () { return node; },
  head: { appendChild: function (appended) { if (appended !== node) throw new Error("appended a foreign node"); } },
  documentElement: null,
};
%(bootstrap)s
console.log(JSON.stringify(loaded));
"""


def is_node_available() -> bool:
    """Whether ``node`` is on PATH, so a caller can skip rather than fail without it."""
    return shutil.which("node") is not None


def run_bootstrap(snippet: str, hostname: str, port: str = "", protocol: str = "http:") -> str | None:
    """Run an emitted bootstrap snippet against a stubbed browser and return the URL it loads.

    ``snippet`` is exactly what ``script_tag`` returned, ``<script>`` wrapper and all. Returns the
    ``src`` the snippet gave the script element it appended, or None when it appended nothing --
    which is the intended behaviour off a workspace origin.
    """
    assert snippet.startswith("<script>") and snippet.endswith("</script>"), snippet
    bootstrap = snippet[len("<script>") : -len("</script>")]
    harness = _HARNESS % {
        "location": json.dumps({"hostname": hostname, "port": port, "protocol": protocol}),
        "bootstrap": bootstrap,
    }
    result = subprocess.run(
        ["node", "--input-type=module", "-e", harness],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip())
