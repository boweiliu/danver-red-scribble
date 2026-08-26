---
name: enable-red-scribble
description: "Turn Red Scribble on for an app so the user can draw, type, or speak feedback directly on top of it and have it arrive in this chat. Use when the user says anything like 'let me scribble on X', 'turn on Red Scribble (for X)', 'I want to give feedback on this app by drawing on it', 'let me mark up the dashboard', or 'switch on the red pen'. Also covers turning it back off."
metadata:
  author: imbue
  crystallized: true
---

# Turning Red Scribble on for an app

Red Scribble puts a red circle in the corner of an app. The user clicks it, draws (or
double-clicks to type, or double-clicks and holds to talk) on top of whatever they want changed,
and the feedback lands in a chat as a card. Acting on that feedback is a different skill --
`red-scribble-feedback` -- which activates itself when the first message arrives.

Switching it on is two separate things, and **both are needed**:

1. **The app opts in** -- the app emits the plug-in's `<script>` tag from its own page. This is a
   code change in the app, committed like any other.
2. **Red Scribble is switched on and pointed at a chat** -- a runtime setting, not code.

An app with the opt-in but no target chat shows nothing at all; a target chat with no opt-in
gets no feedback. Do both.

Everything here is idempotent: running it twice changes nothing the second time.

## Step 1 -- know which app

The user usually names it ("let me scribble on the dashboard"). If they did not, list the
candidates and ask which one -- do not guess:

```bash
uv run .agents/skills/enable-red-scribble/scripts/opt_in_app.py --list
```

Each line is an app, whether it is already opted in, and the page the tag goes in. An app that
cannot be opted in automatically reads `opt in by hand` instead, with the reason as a third
column -- and the two reasons want different things done about them. No HTML page with a
`</head>`: the app builds its page some other way, so say so rather than forcing it. More than
one HTML template: the pages are all there, and which one to scribble on is the author's call, so
ask, then put `{{ red_scribble_tag() }}` in that page's `<head>` yourself.

## Step 2 -- opt the app in

```bash
uv run .agents/skills/enable-red-scribble/scripts/opt_in_app.py <app>
```

This declares the app's dependency on `red-scribble` and puts `{{ red_scribble_tag() }}` in its
page's `<head>`, both only if they are not already there.

It does **not** edit the app's request handler, because that is hand-written code and rewriting
it blind breaks apps. If the last line says `jinja helper NOT WIRED`, make that edit yourself --
it is two lines plus rendering the page through Jinja:

```python
from red_scribble.embed import register_jinja_helper

app = Flask("your_app")
register_jinja_helper(app)


@app.route("/")
def index() -> Response:
    return Response(render_template_string(_PAGE_PATH.read_text()), mimetype="text/html")
```

Then pick up the new dependency:

```bash
uv sync --all-packages
```

## Step 3 -- point Red Scribble at this chat

```bash
red-scribble on --agent "$MNGR_AGENT_ID"          # add --mode live for rapid prototyping
red-scribble status
```

`$MNGR_AGENT_ID` is the chat running this, which is what the user means by "send it to me here".
If you are a sub-agent, use the id of the chat the user is actually talking in, not your own.

Batch (the default) holds scribbles until the user long-presses the circle and chooses **Send**.
Live sends each one a couple of seconds after it is drawn -- offer it only when the user wants a
rapid back-and-forth, and check first that no hardening pass is running, since live feedback
means "do not harden".

The user can change the target chat and the mode themselves from the long-press menu, so this is
a starting point, not a lock.

## Step 4 -- make sure both services are actually running

Red Scribble serves the plug-in from its own service, and the app has to restart to pick up the
template change:

```bash
supervisorctl reread && supervisorctl update
supervisorctl status red-scribble || supervisorctl start red-scribble
supervisorctl restart <app>
```

If `red-scribble` is not a known program, this workspace does not have the service installed --
see `system/libs/red_scribble/README.md`.

## Step 5 -- put it in front of the user

```bash
python3 system/scripts/layout.py refresh <app>     # or `open <app>` if no tab is showing it
```

Then confirm the red circle is there before telling the user it is on. Fetching the page and
looking for the tag is enough:

```bash
curl -s http://127.0.0.1:<app port>/ | grep -c plugin.js
```

## Step 6 -- tell the user how to use it

In plain words, roughly:

> Red Scribble is on for **&lt;app&gt;**. There is a red circle in the bottom-right corner of
> its tab. Click it and the page freezes so you can draw on it -- circle something, cross it
> out, draw an arrow. Click it again to go back to using the page normally; your marks stay but
> hide. Double-click to type a note instead, or double-click and hold to say one out loud.
> When you are ready, press and hold the circle and choose **Send**, and it comes straight to me
> here.

Do not describe the plumbing.

## Turning it off

```bash
red-scribble off        # feedback stops immediately; the circle disappears from every app
```

That is usually all the user means by "turn it off" -- the opt-in can stay, because the tag
renders nothing while Red Scribble is off. To take the code opt-in back out as well:

```bash
uv run .agents/skills/enable-red-scribble/scripts/opt_in_app.py <app> --remove
uv sync --all-packages
supervisorctl restart <app>
python3 system/scripts/layout.py refresh <app>
```

## When something is not right

- **No red circle.** Check `red-scribble status` (it must name a target chat), then that the
  page actually contains `plugin.js` (step 5), then that the `red-scribble` service is running.
- **The circle is there but nothing arrives.** Look at the app's own page in the browser console
  for a blocked request: Red Scribble only answers pages on this workspace's own origins.
- **The page renders `{{ red_scribble_tag() }}` as literal text.** The page is not being
  rendered through Jinja -- step 2's wiring is missing.
