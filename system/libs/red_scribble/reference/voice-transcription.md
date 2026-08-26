# On-device streaming speech-to-text: the single-mechanism design

This is the authoritative design for Red Scribble's voice-capture transcription (the
double-click-and-hold feedback mechanism), and for any on-device streaming STT in this workspace.
It is distilled from a from-first-principles rebuild that fixed a family of recurring bugs. Build
the voice pipeline to *this* design; do not invent a second one.

Per Red Scribble's remixability constraint, Red Scribble carries its **own** copy of this
pipeline (same libraries and approach, its own asset files) -- it must not import another app's
transcription code.

## The core mandate: one mechanism, not two

A single streaming transcriber powers BOTH the live caption and the saved transcript. They are the
**same text read at different times**. The saved result is simply the transcriber's committed state
when the capture ends.

The bugs all came from having **two** transcription paths braided together -- a live "interim" path
plus a separate whole-utterance re-transcription at the end -- and trying to reconcile them. Do not
build that. There is one internal model; the display and the server-save both **read from it**;
neither re-derives text on its own.

## The five requirements

1. **One mechanism, not two.** One streaming transcriber; the saved turn is the model's state at
   end-of-capture. No separate interim path, no end-of-capture whole-utterance re-transcription, no
   "reconcile the two" floor/patch/window logic.
2. **The internal model IS the transcript.** A DOM-free module holds the running committed
   transcript for the current capture. Display and save both read from that one model.
3. **The live caption never freezes, at any length.** It always shows
   `[all committed text so far] + [the current ~20-second window being actively transcribed]` --
   minutes of history plus the live tail. It must not stop updating after the window length.
4. **Model input stays bounded (~20s).** Only a rolling ~20-second window of audio is ever handed
   to the ASR at once, so the worker never chokes. As the front of the window becomes committed,
   that audio is dropped and the window slides forward (**commit-and-advance**). Committed words
   accumulate without bound in the model; the *audio* buffer does not.
5. **Nothing lost, at any length; no duplicated or clipped words.** Everything spoken lands in the
   committed transcript regardless of capture length. Live and final are the same text.

## The mechanism: silence-anchored commit-and-slice

The state of the art ("commit-and-slice", as in Whisper-Streaming) trims the active audio buffer at
the **end-timestamp of the last committed word**. But on-device ASR here (Moonshine via
transformers.js) exposes **no word or segment timestamps** -- its streaming callback returns only
`{text}`. So use the timestamp-free adaptation, which anchors the cut on **silence** instead:

- Keep one rolling audio buffer for the current capture.
- Periodically transcribe the buffer and confirm a **stable prefix** via **LocalAgreement-2** (the
  prefix that two successive transcriptions agree on is "committed").
- When the buffer exceeds the ~20s cap, find a genuine **pause** near the front of the buffer and
  **slice there**: transcribe the head up to the pause, fold its text into the committed model,
  drop that head audio, keep the tail, and continue. Because the cut lands in silence (between
  words), no word is split.
- **Live caption** = `[committed model text] + [LocalAgreement tentative tail of the active window]`.
- **Saved capture** = the committed model text when the capture ends (flush the remaining buffer's
  head into the model first).
- A "capture" is one segment. Its boundaries are app-defined: in a hands-free interviewer it is one
  VAD speech segment (speech-start -> speech-end); **in Red Scribble it is one press-and-hold**
  (pointer-down on double-click-hold -> pointer-up). The sliding window operates *within* a segment,
  so a multi-minute continuous segment still streams and saves fully.

## Two hard requirements (these are what prevent duplicated/clipped words)

1. **Minimum-pause-duration cut.** A cut point must be a **contiguous low-energy run of at least
   ~200ms** (a real inter-word/phrase pause), NOT merely the single lowest-energy frame. A
   stop-consonant closure (the silent part of a /p/, /t/, /k/) is only ~50-100ms; cutting there
   splits a word. If no qualifying pause exists in the search zone, **do not cut yet** -- let the
   buffer grow toward a hard cap (e.g. ~30s) waiting for one. Only at the hard cap do a **forced
   cut**, protected by requirement 2.
2. **Word-level seam de-dup backstop.** When folding a head fragment's new words into the committed
   model, drop any overlap where the new **leading** words repeat the model's **trailing** committed
   words (normalize case + punctuation before comparing). This removes duplication even in the rare
   forced-cut case.

Use the **per-frame audio energy** you already compute for the mic level meter as the signal for
pause detection -- you have the raw frames; do not add a second analysis path.

## Architecture and testability (this split is the point)

- The **pure logic** lives in a DOM-free module and is unit-tested with `node --test`:
  buffer/window management, the "where to slice given an energy array" decision, commit accrual via
  LocalAgreement-2, the seam de-dup, and the normalization helpers (`normWord`/`normText`/
  `collapseRepeats`-style).
- The **DOM / Web Worker / mic wiring** stays out of that module (in the injected plug-in code).
- Run the **ASR in a Web Worker**, one job at a time, async via `postMessage`. **Copy** audio
  buffers when handing them off (don't transfer/detach the buffer you still retain). Keep a
  `worker.onerror` recovery handler.
- You cannot run a real mic + the ASR model in CI, so make the pure logic **deterministically
  testable**: feed synthetic frame/energy arrays and fake transcription results, and prove the
  invariants there; then `node --check` the wiring code for syntax.

## Prior regressions -- make these UNREPRESENTABLE, not merely avoided

The single-mechanism design must make each of these impossible by construction:

1. A repetition collapser cleaned the *display* while a whole-audio final still looped.
2. A multi-window final **discarded the committed streaming text**, losing the first stretch of a
   long capture.
3. An exact-containment "reconcile" truncated long captures to ~one window (~20s).
4. Unbounded interim audio choked the worker -> the pipeline stalled and everything after "went
   nowhere"; and the live caption froze at the window length.

With one model that is the sole source of both live and saved text, and a bounded audio buffer that
only ever grows the *committed words* (not the audio), none of these states can be represented.

## Invariants to prove with deterministic tests

At minimum, `node --test` cases proving:

- Committed text accumulates **without bound** across many window slides (arbitrary length).
- A word straddling a would-be cut is never split, duplicated, or dropped when the cut is forced to
  a real pause; and the seam de-dup removes duplication on a forced (no-pause) cut.
- The live view = `committed + active tail` and keeps advancing **past** the window length (does
  not freeze).
- The saved capture equals the committed model text at end-of-capture.
- **No-loss**: for a synthetic stream, the concatenated committed output equals the intended
  transcript (modulo the fake ASR you feed).

## Server-side durability and safety net

- Always upload the **full raw audio** of the capture as the durable record, **independent of
  transcription** (never fetch-transform-discard). Transcription can be re-run later from it.
- Keep a **server-side runaway-repetition collapser** as a backstop on the saved text -- the
  client design prevents loops, but the server stays a safety net.

## Do not rely on

- Word or segment **timestamps** from the on-device ASR -- Moonshine / transformers.js do not
  provide them. The silence anchor exists precisely because timestamps are unavailable.

## Implementation in Red Scribble (adopted from Local Vocal)

Red Scribble does not reimplement the above from scratch -- it **adopts the Local Vocal inspiration**
(https://github.com/DanverImbue/local-vocal), which crystallizes exactly this design, and carries
its **own copies** of two modules under `assets/`:

- `voice_session.js` -- the DOM-free model: `StreamingTurn` (the silence-anchored commit-and-slice
  transcriber), `Transcript`, and the helpers (`normWord`/`normText`/`collapseRepeats`/`cleanAsrText`
  /`dropSeamOverlap`/`frameRms`). Node-testable; its invariants are proven in
  `assets/voice_session.test.mjs` (run via `voice_session_js_test.py`).
- `voice_capture.js` -- the `window.LocalVocal` driver: it owns the Silero VAD, the Moonshine ASR
  Web Worker (singleton, with `onerror` reload recovery), the `StreamingTurn` pipeline, and Kokoro
  TTS. API: `init` / `whenReady` / `listen({onCaption,onTurn,onLevel,onError})` / `speak` /
  `stopSpeaking` / `encodeWav`. `onTurn(text, wavBlob)` yields both the committed transcript and the
  exact captured audio; `onCaption(stable, tentative)` is the live caption.

**Push-to-talk adaptation.** Local Vocal's `listen()` is hands-free (VAD segments speech
continuously). Red Scribble's voice mechanism is **double-click-and-hold**: on hold-start call
`LocalVocal.listen(...)`, show `onCaption` near the click point, accumulate `onTurn` text (and its
WAV) for the hold's duration, and on release call `stop()` (which seals the active segment). The
accumulated transcript + the WAV(s) + the x/y point and DOM anchor become the voice feedback packet.
The StreamingTurn sliding window still applies within a long hold, so even a minute-long spoken note
streams and saves fully.

Because Red Scribble carries its own copies, it depends only on itself plus the CDN model fetches --
it stays a self-contained, remixable inspiration.
