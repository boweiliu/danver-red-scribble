# red-scribble

A lightweight, framework-agnostic browser plug-in that lets a Minds user give visual/UI
feedback by scribbling, typing, or speaking directly on top of a rendered app. Feedback is
packaged (screenshot + strokes + text + voice transcript + on-screen location + the app it came
from) and delivered to a specific chat's agent for fast iteration.

Red Scribble is designed to be published as a shareable **template** and adapted into other
minds. See `system/libs/red_scribble/docs/concise.md` for the full requirements and architecture.

## How it plugs in

Red Scribble runs as an ordinary workspace app on its own origin -- `system/apps/red_scribble/`
serves this library over HTTP -- exactly like any other service. Nothing proxies it, and nothing
outside this feature has to know it exists.

An app joins by emitting one `<script>` tag pointing at that origin. The plug-in then runs
inside the app's own document and talks back to Red Scribble cross-origin; both origins sit in
one workspace origin family covered by a single session cookie, so the requests are already
authenticated and only need CORS.

The one thing an app cannot do for itself is *find* Red Scribble: service origin labels are
deliberately unguessable (a security property -- see `system/scripts/forward_port.py`). So the
app's **server** looks the origin up in the service registry, which is what `embed.py` does.

## Adding Red Scribble to an app

Two steps, both one line. (Or ask a chat to "turn on Red Scribble for `<app>`" and the
`enable-red-scribble` skill does all of this for you.)

**1. Depend on this library** in the app's `pyproject.toml`:

```toml
dependencies = [
    "flask>=3.0",
    "red-scribble",
]
```

**2. Emit the tag.** For a Flask app, register the helper once and put it in your template:

```python
from red_scribble.embed import register_jinja_helper

app = Flask("your_app")
register_jinja_helper(app)
```

```html
<head>
  ...
  {{ red_scribble_tag() }}
</head>
```

If your app does not render its page through Jinja, call the underlying function directly with
the request's own `Host` header and interpolate the result:

```python
from red_scribble.embed import script_tag

@app.route("/")
def index() -> Response:
    return Response(page_html.replace("</head>", script_tag(request.host) + "</head>"))
```

That is the entire integration. When Red Scribble is off -- or not installed, or the request did
not arrive through the workspace forwarder -- the helper returns an empty string and the page is
byte-for-byte what it was. `script_tag` never raises: a problem inside Red Scribble must not
break the app embedding it.

**Turning it on.** Red Scribble is off until a chat claims it:

```
uv run --no-sync --project system/libs/red_scribble red-scribble on --agent <chat's agent id> [--mode batch|live]   # feedback routes to that chat
uv run --no-sync --project system/libs/red_scribble red-scribble off
uv run --no-sync --project system/libs/red_scribble red-scribble status
```

Then click the red circle in the corner of the app to start scribbling, click it again to use
the page normally, and long-press it for the menu (live/batch, target chat, send).

## Layout

- `config.py` -- the agent-writable target-agent + delivery-mode setting, persisted under
  `data/.apps/red_scribble/config.json`. "On" is derived from the target being set, not stored.
- `origins.py` -- the service-registry lookups: a service name to its unguessable origin label,
  and an `Origin` back to the service that owns it. That second direction is how "may this caller
  reach us?" is answered, without the service needing to know its own public address. A caller
  qualifies only as `<registered label>.<coordinate-shaped label>...`, which rules out a
  registered label put straight in front of a domain someone owns. The coordinate is checked for
  shape only -- our own is not knowable here -- so the unguessable label is what really keeps
  strangers out.
- `embed.py` -- the opt-in: the `<script>` tag an app emits, plus the Flask/Jinja convenience.
- `store.py` -- the scribble registry: every user scribble (a stroke group, text entry, or voice
  note) with its open/closed status.
- `dispatch.py` -- framework-neutral request routing: serves `plugin.js`, serves the plug-in's
  config, and ingests feedback packets (persisting the raw packet and handing a distilled
  message to the target agent through injected callbacks).
- `assets/plugin.js` -- the plug-in itself, plus the vendored `html2canvas.js` it screenshots
  with and the voice-capture modules.
- `reference/voice-transcription.md` -- the mandatory design for the voice-capture (speech-to-text)
  pipeline: single-mechanism silence-anchored commit-and-slice. Read it before writing voice code.
