# Red Scribble

A lightweight, framework-agnostic browser plug-in that lets a Minds user give **visual/UI
feedback by scribbling, typing, or speaking directly on top of a rendered app**, instead of
describing UI problems in the chat box. Feedback is packaged (screenshot + strokes + text +
voice transcript + location) and delivered to a specific chat's agent for fast iteration.

Red Scribble is packaged as a **shareable template**: another feature-builder can adapt it into
their own Minds workspace via `use-template`, and this workspace can publish it via
`publish-template`. (These were called "Inspirations" when this document was first written.)

> Status: **built and in use.** This document describes what exists.

> Build status (implemented): the `red_scribble` lib (config, origins, embed, dispatch, scribble
> registry, CLI, plug-in) and the `red-scribble` service that serves it are built and tested.
> The "Architecture as built" section below records how that design was replaced. Voice capture
> uses Local Vocal's adopted modules with a live-transcription box. Scribbles get stable ids in
> a scribble registry; the agent closes them (`red-scribble close <id>`) and the plug-in stops
> rendering them. Live mode instructs the agent to prototype fast, guess intent, ask no
> questions, and work on a `red-scribble-live-<desc>` branch. Turn on/off with `red-scribble on
> --agent <id> [--mode batch|live]` / `red-scribble off`.

> Simplification note (de-complect pass): "Red Scribble is on" is **derived** from whether a
> target agent is set -- it is not a separate stored flag, so the two can never disagree. A
> screenshot is stored **once** (a `.png` referenced from the packet JSON). The dispatcher owns
> its own config file rather than taking read/write callbacks from the host. These un-braidings are
> reflected below.

## Relationship to this workspace

Red Scribble is a **separate product** from BlogPod (the interview bot). Per the user's
decision it lives in **its own folder on the same branch**, so BlogPod is available as a live
app to test/hack Red Scribble against.

## Enablement and feature flag

- **Off by default.** The user asks their agent to "turn on Red Scribble" when they want to
  iterate on UI. Enabling is an agent action that flips a runtime flag.
- **Apps opt in individually.** An app carries one line in its own template that emits the
  plug-in's `<script>` tag while Red Scribble is on. An app that never adds the line never gets
  Red Scribble, including apps someone else wrote.
- **Chat tagging for routing.** The chat that most recently turned Red Scribble on is recorded
  as the **target agent**. With multiple concurrent chats, feedback routes to that uniquely
  identified chat/agent. The target can be changed from the plug-in's long-press menu.

## The floating logo and the state machine

Enabling shows a floating **red-scribble circle logo, lower-right**.

- **Click** toggles **Active <-> Inactive**.
- **Long-press** opens the **menu** (mode + target agent + send).

Confirmed state flow:

```
Inactive
  -- click --> Active            (overlay intercepts ALL page interaction; you draw/annotate)
  -- long-press --> menu         (toggle Live, pick target agent, Send Pending Scribbles)
  -- click --> Inactive          (scribbles HIDE; NOT sent; page becomes interactive again)
      ... user clicks links, types, navigates pages normally ...
  -- click --> Active            (scribbles RETURN, re-anchored to their original elements)
      ... collect more feedback ...
  -- click --> Inactive
  -- long-press --> Send         (explicit send of the pending scribbles)
```

Key implications:
- **Active = the app is NOT interactive.** An overlay/canvas intercepts all
  clicks/keys/pointer events so they become scribbles, not app interaction. The app keeps
  *running* (its own JS is untouched); only input is captured. To interact with the app, toggle
  Inactive.
- **Inactive = the app IS interactive.** Annotations are hidden but retained. You navigate,
  type, change pages freely; retained scribbles do not interfere.
- Scribbles are **anchored to DOM elements** so they can disappear on deactivate and
  reappear (re-anchored) on reactivate. Best-effort anchoring is sufficient (see below).
- Toggling Inactive does **not** send. Sending a batch is an explicit long-press menu action.

## Terminology

A **scribble** is one user-entered feedback item, of one of three kinds: a **stroke** (freehand
drawing), a **text** entry, or a **voice** note.

## The three feedback mechanisms (combinable, not mutually exclusive)

1. **Stroke** (draw freehand) -> capture the strokes as vector data; the send operation takes
   ONE **screenshot** of the screen shared by every scribble in that send.
2. **Double-click** -> open a **text box** at that x/y (the box is well-behaved and never
   renders off-screen, but the exact x/y point and the **DOM element under the click** are
   saved) -> free typing -> submit.
3. **Double-click-and-hold** -> **record audio** until mouse release -> **speech-to-text**
   transcription (streaming if possible); the x/y point and the DOM element under the click are
   saved alongside the transcript.

**Stroke rendering is hand-rolled on a plain `<canvas>`, with no library.** Strokes are captured
as serializable vector point-lists, which is what the model consumes.

Screenshots use **html2canvas-pro** (DOM-based, no permission prompt), **vendored** into
`assets/html2canvas.js` and served from Red Scribble's own origin, so an adopted template has no
public-CDN dependency for screenshots. The UMD build is what is vendored, deliberately:
cross-origin *module* scripts are fetched without credentials, which the workspace forwarder
rejects, while a classic script carries the session cookie.

**Anchoring trick (confirmed):** the *first* stroke in a group is anchored to the DOM element
under it; every subsequent stroke within a **grouping window (3-5s)** is anchored *relatively* to
that first element. (The grouping window and the live-mode send window are two separate knobs --
one is about visual anchoring, the other about delivery latency.)

## The two delivery modes (long-press menu toggles them + the target agent)

- **Live:** feedback is auto-sent shortly after it lands (a ~2s gather window -- the same
  scale as one agent-delivery round trip). The agent is **primed** with a heavy prompt,
  paraphrased:
  > "Live feedback is incoming -- this is an iteration. Do NOT commit any of this. Delegate
  > all work to subagents. You will be interrupted. Do not harden; make changes as fast as
  > possible. This is lightweight prototyping."
- **Batch:** feedback accumulates until the user explicitly sends it (long-press -> **Send Pending
  Scribbles**). The agent is prompted **less heavily** -- batch mode does **not** restrict to
  simple changes; **hardening the changes IS allowed**.

**Enveloping (one send = one message).** Both modes share ONE send operation: it gathers every
pending scribble and delivers the whole set as a single envelope -- one ``POST feedback`` with
``{"scribbles": [...]}``, one ``<red-scribble-feedback>`` tagged document (metadata in
attributes, notes as element text -- a contract shared with the chat view's batch-card renderer),
one ``send_message_to_agent`` call (which has real per-call latency). The modes differ only in what *triggers* the send: the live-mode gather
window firing, or the user clicking Send Pending Scribbles. Each scribble in the envelope keeps its own stable
id, raw packet, and closeable registry entry. If the send contains any stroke, the plug-in
captures ONE screenshot at send time (capturing is slow) and the whole envelope shares it; the
delivered message names its path once and hints the agent to distill intent from the cheap
signals (context, x/y, DOM anchor, stroke vectors) before reaching for it.

Every feedback packet also carries a note that it was **gathered on a sketch-based surface**, so
the agent should **expect roughness** (x/y coordinates or typed descriptions may be inaccurate)
and aim to **distill the user's intent** rather than execute instructions legalistically.

Menu shape (from the user's sketch, revised 2026-08-06):

```
Live                       [on/off switch]
Send Pending Scribbles (n) (disabled if n = 0 or live is on)
-----------------------------
chats                      (non-clickable section label)
Agent 1
interview-box              (check)
Administrator
```

"Live" renders the one mode fact as a switch (on = live, off = batch).
Toggling it ON immediately flushes any pending feedback (the invariant: while live, pending
never lingers), with the mode persisted first so the flushed send is labeled live.

## Live-editing mode = live delivery + a pre-check

Live-editing mode is **not a separate mode**. It is exactly **live delivery entered through a
one-time pre-check**: before switching to live, the agent **confirms there is no other
hardening-class job or agent at work in the repository** (live "do not harden" feedback would
clash with a hardening pass). **If the pre-check fails, live mode is not entered** and the
user stays in their current mode. Once in live mode, feedback from the three mechanisms is
handed to the agent as it lands, so the user sees results quickly.

So there is one delivery axis -- live vs batch -- plus one entry guard on live; no
third mode.

## Architecture as built (supersedes the original same-origin plan)

The original design served everything **same-origin** through `system_interface`'s
`/service/<name>/` proxy, via two one-line seams in that app: a script injection and a reserved
`__red_scribble/` sub-path. App serving then moved upstream out of `system_interface` into the
vendored `mngr_forward`, both seams were deleted with the file that held them, and Red Scribble's
capture half stopped working. It was rebuilt so that it can never depend on an upstream file
again:

- **Red Scribble is an ordinary workspace app.** `system/apps/red_scribble/` registers a port
  like any other service and owns the origin `red-scribble-<rand>.<workspace-domain>`, serving
  `plugin.js`, `config`, `scribbles`, `feedback`, and `close`. Nothing upstream changes, ever.
- **An app opts in with one line** -- `{{ red_scribble_tag() }}` in its own template
  (`embed.py`). The cost of that: an app that never adds the line never gets Red Scribble. The
  gain: the whole feature lives here and composes with apps anyone writes later.
- **Cross-origin, not a new protocol.** The app's origin and Red Scribble's origin sit in one
  workspace origin family covered by a single domain-scoped session cookie (see
  `mngr_forward/server.py`), so the plug-in's requests are already authenticated. What is needed
  is CORS: the service reflects an `Origin` only when it is a service **registered in this
  workspace** -- an unguessable origin label sitting on a coordinate-shaped host -- never `*`, and
  refuses everything else outright, since the feedback endpoint messages the user's chat and must
  not be callable from an arbitrary page. Note what this test is *not*: "is the caller in the same
  origin family as me?" cannot be asked at all, because the forwarder rewrites `Host` to the
  backend's own address and the service never learns its own public origin. That is also why the
  coordinate is only checked for its `host-<hex>` shape and not for being *ours*: it bars a
  registered label pinned straight onto someone's own domain, but someone who owns a domain can
  add a `host-<hex>` label to it. The unguessable label carries the security.
- **Provenance** (which app a scribble came from) is resolved server-side from the `Origin`
  header's label through the service registry, so a page cannot claim to be another app.
- **Feedback delivery to the agent:** the backend calls the mngr Python API
  `send_message_to_agent(<target agent id>, <message>)` (the same call the chat box uses;
  messages are picked up at the agent's next turn boundary -- **queue-between-turns**, which the
  user confirmed is acceptable). The agent list for the menu comes from the existing
  `/api/agents`.
- **Enable/config:** enabling writes `data/.apps/red_scribble/config.json`
  (`{target_agent_id, mode}` -- "on" is derived from `target_agent_id` being set, not stored); the
  plug-in reads `<red-scribble origin>/config` for the target agent, mode, and agent list. The
  same file is what `embed.py` consults, so an app emits no tag at all while Red Scribble is off
  -- except for a surface that opts in with `always_on=True` (see below).
- **Voice STT:** reuse the *approach* BlogPod proved (Moonshine ASR + Silero VAD via
  `@ricky0123/vad-web`, streaming where possible) but as Red Scribble's **own** asset -- it must
  not import interview_bot's files, or the two products braid and Red Scribble stops being a
  self-contained, remixable template. The **mandatory design** (single-mechanism
  silence-anchored commit-and-slice, with the two hard safety requirements and the test invariants)
  is in `libs/red_scribble/reference/voice-transcription.md`.

  **Decided 2026-08-25: the voice models load from a public CDN and are not vendored.** Unlike
  html2canvas, the speech/VAD models (`vad-web`, `onnxruntime-web`,
  `@huggingface/transformers`, `kokoro-js`) stay as CDN URLs in `assets/voice_capture.js`. This
  is a standing decision, not an open question: it keeps hundreds of megabytes out of the repo
  and out of any published template, at the cost of voice notes needing public internet at
  runtime. Do not propose vendoring them.
- **Raw data preservation (workspace default):** every feedback packet -- vector strokes, text,
  voice audio + transcript, x/y, DOM anchor, page URL, app name, target agent, timestamp -- is
  persisted durably under `data/.apps/red_scribble/` (not fetch-transform-discard), with a way to view
  the raw packet, per the workspace's preserve/surface rule. The screenshot is stored once as a
  `.png` (native format) referenced by name from the packet JSON.

## Components

- **The plug-in (`plugin.js`)** -- extremely lightweight, framework-agnostic, no build step
  required in the host app. Owns the floating logo, the state machine, the interaction-intercept
  overlay + stroke canvas, the double-click text box, the double-click-hold voice capture,
  html2canvas screenshots, DOM-anchored scribble persistence, the long-press menu, and the
  debounce/auto-send logic. Every URL it uses is absolute against the origin it was served from.
- **Backend handler (in the `red_scribble` lib)** -- serves `plugin.js` + static assets + config,
  ingests feedback packets, persists raw packets, and forwards packaged feedback to the target
  agent via the mngr API. Framework-neutral; the service adapts it to Flask.
- **The `red-scribble` service** (`system/apps/red_scribble/`) -- an ordinary workspace app that
  serves the above on its own origin, enforces the CORS boundary, resolves provenance, and shows
  a status page listing every captured scribble with its raw packet.
- **The opt-in (`embed.py`)** -- the one line a participating app puts in its own template.
  `always_on=True` is the variant for a surface that exists to exercise Red Scribble: it emits
  the tag even while Red Scribble is globally off, so the test surface does not go dark exactly
  when someone is debugging Red Scribble itself. **The Scribble Box uses it; ordinary apps must
  not.** It overrides the switch, not the absence of the service -- with Red Scribble
  uninstalled there is no origin to point at, so the tag is still empty.
- **Enable/config mechanism** -- agent-writable runtime config recording the target agent and
  delivery mode (on/off is derived from whether a target is set). The `enable-red-scribble`
  skill drives both halves: the code opt-in and the runtime switch.
- **Template packaging** -- structured so `publish-template` yields a clean, adaptable snapshot.

## Out of scope (initial)

- Freezing/pausing the underlying app's own JS execution (only *input* is intercepted while
  Active).
- Perfect pixel-accurate screenshots of cross-origin images / WebGL / canvas (html2canvas
  limitation; acceptable).
- Rock-solid scribble re-anchoring across arbitrary SPA re-renders (best-effort only, with the
  screenshot as ground truth).
- True mid-turn interruption of a busy agent (queue-between-turns instead).

## Still open

1. Whether the built-in services (terminal/ttyd, browser) should opt in too, or only user-built
   apps. Neither does today.

Settled since this document was first written, and recorded above rather than here: the voice
models come from a CDN (decided 2026-08-25); the feedback-packet schema and the raw-packet
viewer exist (the service's status page); and the agent enables Red Scribble through the
`enable-red-scribble` skill.
