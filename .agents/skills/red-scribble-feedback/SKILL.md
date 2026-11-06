---
name: red-scribble-feedback
description: "The playbook for acting on Red Scribble UI feedback: scribbles (a freehand stroke, typed note, or voice note the user drew/typed/spoke on top of a rendered app) delivered to this chat. Activate this once when you receive a 'Red Scribble feedback' message. Covers live vs batch mode, how to interpret a stroke, when to WAIT instead of acting, the dedicated-branch workflow, and closing scribbles."
---

# Acting on Red Scribble feedback

Red Scribble delivers UI feedback to this chat as **scribbles**. A scribble is one user-entered
feedback item, of one of three kinds: a **stroke** (freehand drawing), a **text** entry
(double-click), or a **voice** note (double-click-and-hold, transcribed). Each delivered message
**envelopes one send operation** -- everything the user had gathered when the send fired (the
live-mode gather window, or their Send Pending Scribbles click) -- as one tagged document:

```
<red-scribble-feedback mode="batch|live" app="<app>" count="N" screenshot="<path, if any>">
Act per the /red-scribble-feedback skill. ...
<scribble id="fbk-..." kind="stroke" point="x,y" anchor="<css>" strokes="1" page="<url>" raw="<packet path>"/>
<scribble id="fbk-..." kind="text|voice" ... raw="...">the typed or spoken note</scribble>
</red-scribble-feedback>
```

Metadata rides in attributes; a typed/spoken note is the element's text content. Act on all
scribbles in the document as one turn of feedback. (The chat view renders this same document as a
card, so never quote it back verbatim -- speak about the scribbles in plain words.) This skill is
the full playbook; you only need to read it once per session.

## Delivery modes

- **Live** -- rapid prototyping. Make the quickest change that most likely satisfies
  the feedback, right now. Quick-and-dirty is fine; **speed over perfection**, and rough work can be
  cleaned up later. You **cannot** ask the user for more information in this mode -- take your best
  guess and act; if you guess wrong, they will simply send more feedback. **Work on a dedicated
  branch** named `red-scribble-live-<short-description>` (create and switch to it if you are not
  already on one) and commit there, so the rapid work can be reviewed and merged into `main` later.
  Do not work directly on `main`.
- **Batch** -- you may make substantial changes and harden them (normal quality bar). The mode is
  the root tag's `mode` attribute.

## After a live edit, reload so the diff renders (live mode)

In live mode the point is a tight, visible loop, so when you finish an edit **reload the app** --
don't leave the user staring at stale output. The `App:` field names the service; reload every
page of it:

```
uv run --no-sync workspace-layout refresh --app <app>
```

If the app needs a build step or a service restart to serve the change, do that first, then refresh.
For an app that serves its assets fresh per request (no build), the refresh alone shows the diff.

## Interpreting the feedback

- It was gathered on a **sketch-based surface**, so expect roughness: on-screen coordinates and
  typed/spoken descriptions may be imprecise. **Distill the user's intent** rather than executing
  the words legalistically.
- Typed and voice notes carry their text directly.
- **Read the cheap signals first; treat the screenshot as a fallback.** Working with the
  screenshot (fetching, scaling, compositing) is *slow*, so before touching it, try to distill
  each scribble's intent from what the document and raw packet already give you: the surrounding
  chat context, the other scribbles in the same send, the **DOM anchor** (which element it sits
  on), the **point** (x/y), and for strokes the **vector points** (their shape and extent often
  read as an X, a circle, or an arrow straight from the numbers). Most sends are decidable from
  these alone.
- **Coordinates are CSS pixels in DOCUMENT space** -- measured from the top of the page, not the
  top of the window -- so they line up with the screenshot directly however far the page was
  scrolled. Do not apply a scroll offset; there is none to apply.
- The send carries at most **one screenshot, shared by every scribble in it** (its path is the
  root tag's `screenshot` attribute; captured with the plug-in's own chrome hidden, so it does *not*
  include the red strokes). Reach for it only when the cheap signals leave real ambiguity. To see
  what was drawn **and where**, composite the strokes onto it:
  1. The screenshot is the whole document at `packet["device_pixel_ratio"]` scale (a 2x capture
     of a 583px-wide page is a 1166px-wide PNG). Divide the image's pixel width by that ratio to
     get the CSS width the coordinates are in.
  2. Overlay the stroke polylines (from `packet["strokes"]`) on the screenshot scaled to that CSS
     size (an HTML `<img>` + an absolutely-positioned `<svg>` with a matching `viewBox`,
     screenshotted headlessly, works well), then look at the result.
  3. If the marks look plausible but sit a line or two off the thing they must mean, do **not**
     nudge them until they fit. They are already in the screenshot's own space; a mismatch means
     the reading is wrong, not the alignment.
- A **clear** signal is actionable: an X over a button (delete it), an arrow pointing at a target, a
  circle around an element, or a note typed/spoken right next to the thing it refers to.

## When a stroke is unclear, WAIT -- do not over-act  (the norm)

Freehand strokes are often ambiguous -- that is expected.

- If you cannot **confidently** distill the intent of a stroke, do **not** guess or make a
  speculative change. A doodle in empty space with no UI target under it is **not** actionable.
- **Prefer to wait.** Leave the scribble open and take no action; clearer instructions will almost
  always follow -- the user will draw directly on the element, or type/speak a note next to it.
  Acting on a misread stroke is worse than doing nothing, because the user then has to notice and
  undo it.
- This restraint is the intended behaviour even in live mode: "best guess and act" applies to
  feedback whose intent you can actually read, not to genuinely unclear marks.

## Closing scribbles

Every scribble has a stable **scribble id**. When you have acted on it -- or decided, per the rule
above, that there is nothing clear to act on -- close it so it stops rendering on the user's screen:

```
uv run --no-sync --project system/libs/red_scribble red-scribble close <id>            # from the repo root; several ids allowed
uv run --no-sync --project system/libs/red_scribble red-scribble list                  # show open scribbles
```

Closing an actioned scribble is how "draw an X on a button -> delete it -> the X disappears" works.
**Do not** close a scribble you are intentionally waiting on -- leave it open until it is
addressed or clearly superseded by a clearer instruction.

## Exclusion: the Scribble Box is never committed

The `scribble-box` app (`system/apps/scribble_box/`, the "Scribble Box" tab) is a
dedicated scratchpad for *testing* Red Scribble itself. Special rule:

- Red Scribble feedback on the Scribble Box may be acted on freely for demo purposes --
  edit its files, show the change, iterate.
- But changes to Scribble Box files that result from Red Scribble feedback are **NEVER
  committed**. This applies in both live and batch mode, and overrides the live-mode
  "commit on a dedicated branch" workflow above.
- Any such changes MUST be **reverted** (`git checkout -- system/apps/scribble_box/`)
  before any other commit is made, so they can never ride along in an unrelated commit.
- Each Scribble Box file carries a reminder header to this effect; keep it intact.

## Note on routing

Feedback goes to whichever chat Red Scribble is currently targeting (`red-scribble on --agent <id>`
/ the plug-in's long-press menu). If a message concerns an app whose code this workspace does not
own, say so rather than editing code you don't control.
