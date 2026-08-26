# Red Scribble note lifecycle (design)

> Status: **design** (not yet implemented). Defines an explicit state machine for feedback boxes
> (text + voice scribbles), with per-state controls. Led by a de-complect memo showing the braids the naive
> design would carry and how this one avoids them.

## The instruction (state machine)

- **Text:** Editing (typing) → click **Create** → Pending
- **Voice:** Speaking → release mouse → Pending
- **Pending** → batch send *or* debounce fires → **Sent**
- **Sent** → agent marks closed → **disappears**

Controls, **only while Pending**:
- Both kinds: **trash** button → delete the box (never sent).
- Text: **edit** button → drop back to Editing (alter the text).
- Voice: **mic** button → resume recording and **append** to the note.

(Icons are small inline SVGs -- trash / pencil / mic -- never emoji.)

## Simplification memo (de-complect)

The naive implementation would grow several braids; each is cut below.

| # | Braid (radar) | Cut → survivor |
|---|---|---|
| 1 | **value+time / data+repr:** a `state.pending` array *and* the note object both encode "is this pending" -- two sources that can disagree. | One `status` field on the scribble is the single source of truth; **`state.pending` is deleted** -- "pending" is `scribbles.filter(s => s.status === "pending")`. Send-Batch count derives from it. → *survivor: `status`.* |
| 2 | **fused / what+how:** the pre-commit editing UIs (`openTextBox`, `voiceBox`) are separate transient elements with their own lifecycle, *plus* a second render path for the committed note box -- two ways to draw one note. | **One status-driven box.** "Editing/Speaking" is just the box in its first status; `renderNotes` renders the box per `(kind, status)`. `openTextBox`/`voiceBox` fold into that. → *survivor: the single `renderNotes` switch.* |
| 3 | **variants nobody branches on at that level:** "Editing" (text) and "Speaking" (voice) are two names for the same lifecycle slot (pre-commit). | One status **`drafting`**, rendered per kind (textarea+Create for text; live caption+record dot for voice). The *trigger* out of it differs by kind (Create vs mouse-release) -- that's input, not state. → *survivor: one status, kind at render.* |
| 4 | **value+time:** storing a `"closed"` status client-side duplicates closed-ness, which already lives in the scribble registry (the agent closes it; the plug-in polls). | **No `closed` status.** Closed = removed from `state.scribbles` by the existing poll. The box disappearing *is* the closed state. → *survivor: the store + poll (already built).* |
| 5 | **policy scattered:** "live sends immediately" and "batch sends on click" are two send code paths. | **One `send(scribble)`** (POST feedback, set id, `status = "sent"`). Two *triggers* call it: a per-note debounce timer (live) or the Send-Pending-Scribbles action (batch). → *survivor: `send()`.* |
| 6 | **fused / modular:** each kind (stroke/text/voice) growing its own create→send→close flow. | **One lifecycle for all scribbles** (`pending → sent → closed`); `drafting` + box controls are the text/voice-only overlay. Strokes enter at `pending` and ride the same send path (no box UI). → *survivor: one `status` across kinds.* |

**Preserved as intentional (not braids):** the kind-specific Pending controls (text **edit** vs voice **mic** are genuinely different actions a caller branches on); the debounce timer (a real mechanism, not duplicated state); stroke canvas rendering (inherent -- a stroke is not a box).

## The de-complected design

### One model, one status

Each scribble carries a single lifecycle field:

```
status: "drafting" | "pending" | "sent"
```

- `closed` is **not** a value here -- a closed scribble is removed from `state.scribbles` (the poll already does this).
- `state.pending` is **removed**; pending items are derived: `state.scribbles.filter(s => s.status === "pending")`.
- Content stays per kind: `points` (stroke), `text` (text), `text`=transcript + `audio` (voice); plus `point`, `anchor`, and `id` (assigned only when it reaches `sent`).

### Transitions (the single state table)

```
text:    (new)         -> drafting
         drafting  --Create-->        pending
         pending   --edit-->          drafting        (re-open the textarea, prefilled)
voice:   (hold)         -> drafting   (recording, live caption)
         drafting  --release-->       pending
         pending   --mic-->           drafting        (resume recording, append) --release--> pending
both:    pending   --trash-->         (removed)
         pending   --send/debounce--> sent
         sent      --agent close-->   (removed)
stroke:  (finish)       -> pending    -> ... -> sent -> (removed)   [no drafting, no box controls]
```

One `transition(scribble, next)` helper owns status changes (and cancels any pending debounce timer on leaving `pending`), so the table lives in exactly one place.

### Rendering (by kind × status, in `renderNotes` / canvas)

- **text · drafting** → box with an editable `<textarea>` + a **Create** button.
- **voice · drafting** → box showing the live caption + a recording indicator (release ends it).
- **text|voice · pending** → box showing the content + a control row: **trash**, and **edit** (text) or **mic** (voice).
- **text|voice · sent** → box showing the content, no controls, a subtle "sent" affordance; stays until the agent closes it.
- **stroke** → drawn on the canvas as today; `status` only governs its send timing (no inline controls).

All of this still renders only while Red Scribble is **active** (the one active-state lifecycle already unifies overlay/strokes/notes; these boxes hide on deactivate and return on reactivate).

### Sending (one path, two triggers; already built as the envelope)

```
send():      gather ALL pending scribbles; POST __red_scribble/feedback with
             {"scribbles": [...]} (ONE envelope, ONE delivered message);
             on success set each scribble's id and transition it to "sent"; re-render.
```
- **Live:** entering `pending` opens the send gather window (`SEND_DEBOUNCE_MS`, ~2s --
  the scale of one agent-delivery round trip) if none is open. Trash / edit / mic pull a note back
  out of `pending` before the window fires; on fire it calls `send`.
- **Batch:** the long-press **Send Pending Scribbles** calls `send`. Its count is the derived pending list's
  length.

Nothing is POSTed until `sent`, so `pending` notes are purely client-side (the agent never sees a note the user is still editing or about to trash) -- and only `sent` notes have an id and are closeable by the agent.

### What changes in the code (for when we implement)

- `state.pending` removed; add `status` to every scribble; add `transition()` and `send()`.
- `openTextBox`/`voiceBox` become the `drafting` rendering inside `renderNotes`; `queueText`/`queueVoice`/`queueStroke` create the scribble at `drafting` (text/voice) or `pending` (stroke) instead of calling `enqueue`.
- `enqueue`/`sendPending` collapse into `send()` + the gather-window/Send-Batch triggers.
- `renderNotes` switches on `(kind, status)` and wires the control buttons to `transition`/`send`/trash.

No backend change: the dispatcher already receives one envelope per send and stores each scribble / delivers one message.
