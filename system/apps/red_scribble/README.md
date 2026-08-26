# red-scribble (service)

Serves Red Scribble on its own workspace origin: the plug-in an app loads, the config and
scribble endpoints it talks to, and a status page showing where feedback is going and every
scribble captured so far (each linked to its raw packet, screenshot, and voice audio).

The behaviour lives in the `red_scribble` library (`system/libs/red_scribble/`) -- this package
is a thin Flask adapter that supplies the host boundary: where files live, how to list the
workspace's chats, how to deliver a message to one, which origins may call, and which app a
piece of feedback came from.

To add Red Scribble to an app, you do not change anything here -- see
[the library's README](../../libs/red_scribble/README.md#adding-red-scribble-to-an-app) for the
one line, or run the `enable-red-scribble` skill.

## Layout

- `src/red_scribble_service/runner.py` -- the Flask app: routes, CORS enforcement, the status
  page, and the raw-attachment viewer.
- `src/red_scribble_service/cors.py` -- which cross-origin callers are answered, and with what
  headers.
- `src/red_scribble_service/agents.py` -- the two mngr calls: list the workspace's chats, and
  deliver a message to one.
- `src/red_scribble_service/status.py` -- the status page's view of the scribble registry,
  including the stroke thumbnails drawn from the stored vectors.

The Python package is named `red_scribble_service` rather than `red_scribble` because the
library already owns that import name.
