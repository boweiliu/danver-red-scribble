---
title: "Red Scribble"
description: "Scribble, type, or speak UI feedback directly on any app in your workspace; it routes to your chat agent as one batched, rendered card per send."
thumbnail: "template.svg"
version: v3
format: v2
---

# Red Scribble

This file is the manifest for the **Red Scribble** template (slug:
`red-scribble`). It is the one document a future agent reads to understand,
present, and adapt this template. If you are an agent in a mind that was
created from this template, this file is your script: read all of it, then
follow "How to adapt it" below.

## What it is

Scribble, type, or speak UI feedback directly on any app in your workspace; it routes to your chat agent as one batched, rendered card per send.

Red Scribble solves the awkwardness of describing UI problems in prose. Once an
agent turns it on for an app, a small red circle floats in that app's lower-right
corner. Click it and the page stops responding to clicks -- your input becomes
annotation instead: draw freehand over anything, double-click to drop a typed
note, or double-click-and-hold to speak one. Click again and the page is yours
back; your marks hide but are kept. Press and hold the circle for a menu that
picks which chat receives the feedback and sends what you have gathered.

One send becomes one message: every mark, plus a single screenshot, arrives in
that chat as a card of tiles you can hover for detail. The agent reads your
intent, makes the change, and closes each scribble so it disappears from your
screen. Two delivery modes tune the pace -- **batch** waits for you to press send
and lets the agent harden its work, while **live** auto-sends a couple of seconds
after each mark and primes the agent for fast, throwaway prototyping. While it
runs, all you see is the red circle and your own annotations.

## How it works

The snapshot includes these paths (each is a repo-root-relative path copied
from the original mind onto a clean default-workspace-template base):

- `system/libs/red_scribble`
- `system/apps/red_scribble`
- `system/apps/scribble_box`
- `.agents/skills/red-scribble-feedback`
- `.agents/skills/enable-red-scribble`
- `system/supervisord.conf`
- `pyproject.toml`
- `uv.lock`
- `system/apps/system_interface/pyproject.toml`
- `system/apps/system_interface/imbue/system_interface/test_e2e.py`
- `system/apps/system_interface/frontend/src/style.css`
- `system/apps/system_interface/frontend/src/views/hoverTooltip.ts`
- `system/apps/system_interface/frontend/src/views/icons.ts`
- `system/apps/system_interface/frontend/src/views/message-classification.ts`
- `system/apps/system_interface/frontend/src/views/message-kinds.ts`
- `system/apps/system_interface/frontend/src/views/user-message-display.ts`
- `system/apps/system_interface/frontend/src/views/red-scribble.ts`
- `system/apps/system_interface/frontend/src/views/red-scribble.test.ts`
- `system/apps/system_interface/frontend/src/views/red-scribble-card.ts`
- `system/apps/system_interface/frontend/src/views/red-scribble-card.test.ts`

**Red Scribble runs as an ordinary workspace app on its own origin, and any app
opts in with one line.** That is the whole architecture, and it is deliberate:
nothing here depends on internals of the workspace UI or of minds, so a change
to either does not break it.

- **`system/libs/red_scribble`** -- the self-contained library. `config.py` (the
  agent-writable target-chat and delivery-mode setting, where "on" is *derived*
  from a target being set, never stored); `dispatch.py` (a framework-neutral
  router -- it takes a method, path and body and returns a plain response, so it
  depends on neither Flask nor mngr); `store.py` (the scribble registry tracking
  each mark's open/closed state); `origins.py` (service-registry lookups);
  `embed.py` (the one-line opt-in); `cli.py` (`red-scribble on/off/status/list/close`).
  Browser assets under `src/red_scribble/assets/`: `plugin.js` (floating logo,
  input-intercept overlay, stroke canvas, typed-note box, voice capture,
  screenshots, long-press menu, send logic), a vendored `html2canvas.js`, and
  the voice modules. Architecture in `docs/concise.md`.
- **`system/apps/red_scribble`** -- the service. A thin Flask adapter over the
  library's router, serving `/plugin.js`, `/config`, `/scribbles`, `/feedback`
  and `/close` on its own origin, plus a status page listing every captured
  scribble with its raw packet. It owns the trust boundary: an `Origin` is
  answered only when its leading label belongs to a service registered in this
  workspace.
- **`system/apps/scribble_box`** -- the "Scribble Box" scratchpad (a Jabberwocky
  poem with a mouse-sparkle effect) for trying Red Scribble against a live app.
  It is the worked example of the opt-in, and its files carry a
  never-commit-demo-edits rule.
- **`.agents/skills/enable-red-scribble`** -- turns Red Scribble on for a named
  app: adds the opt-in line to that app's template and points feedback at the
  chat that ran it. Idempotent, and covers turning it off.
- **`.agents/skills/red-scribble-feedback`** -- the agent playbook for acting on
  delivered scribbles: live vs batch, how to read a stroke, when to WAIT rather
  than guess, and closing scribbles.
- **The workspace-UI files** -- the chat-side rendering only:
  `red-scribble*.ts` detect a delivered feedback message and draw it as a card of
  tiles with hover detail, and the handful of neighbouring files they hook into
  (message classification and kinds, the hover tooltip, icons, the user-message
  view, and the stylesheet). No proxy seam, no dispatcher branch -- an earlier
  version of this template needed those and they no longer exist.
- **`system/supervisord.conf`, `pyproject.toml`, `uv.lock`** -- the two program
  entries and the package wiring.

**At runtime** two supervisord programs run: `red-scribble` (port 8082) and
`scribble-box` (port 8080), each registering its port through
`system/scripts/forward_port.py` like any other app. An app opts in by calling
`register_jinja_helper(app)` once and putting `{{ red_scribble_tag() }}` in its
template's `<head>`; the server contributes Red Scribble's unguessable service
label and the browser assembles the rest of the address, because the workspace
forwarder rewrites `Host` and a service can never learn its own public origin.
Feedback reaches the chat through the in-workspace mngr `send_message_to_agent`
call -- picked up at the agent's next turn boundary.

## Recipe

This template is version `v3`. It is not a fork of the
workspace it came from -- it is DERIVED from it by a recipe: include these
paths, leave these out, apply these published-version rules. An update re-runs
the recipe against the current workspace and publishes the result as the next
version, so anything excluded stays excluded even though it still exists in the
source workspace.

The recipe is machine-read, so it lives in the sibling
[`template.toml`](template.toml) -- its `[recipe]` table -- along with
the structured requirements and the environment this template needs
installed. That file is authoritative for all of it; this one holds the prose.

## Requirements

Everything the adopting mind must deal with before this template is really
theirs. Two kinds of entry, handled at different times:

- **Activation** -- what must be SET UP before anything runs, in the
  machine-readable `requires_` forms below. The adopting agent acts on these
  ITSELF, first, before asking anything.
- **Adaptation** -- what must be DECIDED or REWIRED, in prose. Worked through
  interactively with the user, after activation.

**Activation** -- nothing to set up:

No requirements -- runs as published, with no external permissions or secrets.

**Adaptation** -- what you must decide or rewire:

- **Opt your app in before you enable Red Scribble.** Red Scribble appears on an
  app once that app carries the one-line opt-in. Run the `enable-red-scribble`
  skill for each app you want to scribble on. The included Scribble Box is
  already opted in, so you can try it immediately.

## Environment

What this template needs INSTALLED, beyond what the template already has.
Declared in `template.toml`'s `[environment]` table; an adopting mind
converges it at ITS OWN pinned apt snapshot timestamp, so package versions come
out consistent with the rest of that mind's environment rather than frozen to
whatever this publisher happened to have.

Nothing extra -- runs on the stock workspace environment.

## How to adapt it

Instructions for the NEXT agent -- the one adapting this template into a
new mind. This is the `use-template` skill's template path; in short:

1. Read this entire file first, especially "Requirements" below. It holds two
   kinds of entry and they are handled at different times: the machine-readable
   `requires_` lines are ACTIVATION (set them up before anything runs), and
   the prose bullets are ADAPTATION (decide or rewire them afterwards).
2. Present the template to the user in plain, non-technical language: what
   it is, what it does, and what it needs from them (name the activation
   requirements).
3. Ask whether they want to use the same connectors (e.g. their own Slack).
   If YES: ACTIVATE FIRST -- initiate every `requires_permission` line NOW
   via a latchkey permission request (see the `latchkey` skill; the request
   opens the approval/login flow in the minds app), wire up any
   `requires_secret` values, start the services, and get the app showing
   THE USER'S OWN DATA. Done for a data-backed app means the user can open it
   and see their own data -- NOT that a service starts or an endpoint returns
   200. Then tell them it is live and to take a look.
4. Only AFTER that (or immediately, if they chose different connectors -- the
   swap is then the first adaptation) ask: "How do you want to adapt it?"
5. Work through each requirement interactively, one at a time. Translate each
   into plain language, ask for a decision only when you genuinely need one,
   and resolve the obvious ones yourself.
6. When done, append a dated entry to "Adaptation history" below (never
   rewrite earlier entries) and commit.

## Publication history

This template's changelog: what each published version changed. The PUBLISHER
appends one entry per version (newest last); earlier entries are never rewritten.
This is distinct from "Adaptation history" below, which is the ADOPTERS' log.

### v3 (2026-08-26) -- a standalone app with a one-line opt-in

Red Scribble runs as an ordinary workspace app on its own origin, and any app
joins it by adding one line to its own page. That makes it compose with whatever
you build next, and keeps it independent of the platform's internals.

New in this version:

- **`enable-red-scribble`** -- a skill that turns Red Scribble on for a named app
  and points feedback at the chat that ran it.
- **Marks land where you put them.** Positions are recorded against the page, not
  the window, so a scrolled page annotates the right line.
- **Screenshots ship with the template.** The capture library is vendored, so
  screenshots need nothing from the network.
- **Each mark records the display scale it was drawn at**, so a reader never has
  to guess how the screenshot maps to the marks.
- **Callers are checked against the workspace's own service registry.**
- Cut on a current template base.

## Adaptation history

Each mind that adapts this template appends one dated entry below. Earlier
entries are never rewritten.
