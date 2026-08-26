/**
 * Parsing for a Red Scribble feedback message: the single tagged
 * `<red-scribble-feedback>` document one send operation delivers to the chat
 * agent (see `system/libs/red_scribble/src/red_scribble/dispatch.py::build_feedback_message`
 * -- that builder is the contract). The document envelopes every scribble in the
 * send: metadata rides in attributes, spoken/typed notes are element content, a
 * stroke is a self-closing `<scribble .../>` with a `strokes` count.
 *
 * This module is the pure-data half (no mithril): it turns the raw text into a
 * `RedScribbleBatch`, or `null` when the text isn't a well-formed feedback
 * document. The detector in message-classification.ts calls it to decide whether
 * to classify the message as `RedScribbleFeedback`, and the card renderer in
 * red-scribble-card.ts calls it to get the structured batch to draw. A message
 * that fails to parse (truncated, wrong root, no scribbles) yields `null` and
 * falls through to the normal user-prompt rendering.
 *
 * Parsing is via the browser's `DOMParser` in `text/xml` mode -- XML (not HTML)
 * because the format uses self-closing tags for strokes, which HTML parsing
 * would mis-nest. A malformed document surfaces a `<parsererror>`, which we
 * treat as "don't match".
 */

/** The three kinds a scribble can be; anything else is rendered generically. */
export type ScribbleKind = "stroke" | "voice" | "text";

/** One scribble in the batch -- a stroke group, a voice note, or a typed note. */
export interface Scribble {
  /** Stable packet id (e.g. `fbk-7e32aba5`), or null if absent. */
  id: string | null;
  /** The raw `kind` attribute (`stroke` | `voice` | `text`, or something else). */
  kind: string;
  /** `"x,y"` viewport point the scribble was placed at, or null. */
  point: string | null;
  /** CSS-path anchor of the element under the scribble, or null. */
  anchor: string | null;
  /** URL of the page the scribble was made on, or null. */
  page: string | null;
  /** Path to the raw persisted packet, or null. */
  raw: string | null;
  /** Number of strokes in a stroke group; null for note kinds. */
  strokes: number | null;
  /** The typed/spoken note text (text/voice kinds); null for a bare stroke. */
  note: string | null;
}

/** One send operation's worth of feedback: the header fields plus its scribbles.
 *  The document's `count` attribute is intentionally not carried here -- the card
 *  shows `scribbles.length` (what actually rendered), and the raw attribute stays
 *  available in the original message text. */
export interface RedScribbleBatch {
  /** Delivery mode label: `batch` or `live` (or an unrecognised passthrough). */
  mode: string;
  /** The app the feedback was made in (e.g. `scribble-box`). */
  app: string;
  /** Path to the shared screenshot for the send, or null when none was taken. */
  screenshot: string | null;
  /** The scribbles, in document order. Always at least one when non-null. */
  scribbles: Scribble[];
}

const ROOT_TAG = "red-scribble-feedback";

/** Anchored to the root tag so a normal prompt that merely quotes the tag name
 *  in prose is never treated as a feedback document. */
const ROOT_TAG_RE = new RegExp(`^\\s*<${ROOT_TAG}\\b`);

/** A quick, DOM-free pre-check the detector can run before parsing. */
export function looksLikeRedScribbleFeedback(content: string): boolean {
  return ROOT_TAG_RE.test(content);
}

function parseStrokes(value: string | null): number | null {
  if (value === null) {
    return null;
  }
  const n = Number(value);
  return Number.isInteger(n) && n >= 0 ? n : null;
}

function parseScribble(el: Element): Scribble {
  // A self-closing stroke element has no child nodes, so textContent is "".
  const note = el.textContent !== null && el.textContent.trim().length > 0 ? el.textContent.trim() : null;
  return {
    id: el.getAttribute("id"),
    kind: el.getAttribute("kind") ?? "",
    point: el.getAttribute("point"),
    anchor: el.getAttribute("anchor"),
    page: el.getAttribute("page"),
    raw: el.getAttribute("raw"),
    strokes: parseStrokes(el.getAttribute("strokes")),
    note,
  };
}

/**
 * Parse a Red Scribble feedback document into a `RedScribbleBatch`, or `null`
 * when the text is not a well-formed one. Returns `null` (never throws) for:
 * text that doesn't start with the root tag, a `DOMParser` that isn't available
 * (a non-browser environment), an XML parse error (e.g. a truncated document),
 * a wrong or missing root element, a missing `app`/`mode`, or a document with no
 * scribbles -- every one of which should render as a plain prompt instead.
 */
export function parseRedScribbleFeedback(content: string): RedScribbleBatch | null {
  if (!looksLikeRedScribbleFeedback(content)) {
    return null;
  }
  if (typeof DOMParser === "undefined") {
    return null;
  }
  let doc: Document;
  try {
    doc = new DOMParser().parseFromString(content.trim(), "text/xml");
  } catch {
    return null;
  }
  // A malformed document parses into a <parsererror> tree rather than throwing.
  if (doc.querySelector("parsererror") !== null) {
    return null;
  }
  const root = doc.documentElement;
  if (!root || root.tagName !== ROOT_TAG) {
    return null;
  }
  const app = root.getAttribute("app");
  const mode = root.getAttribute("mode");
  if (!app || !mode) {
    return null;
  }
  const scribbles = Array.from(root.getElementsByTagName("scribble"), parseScribble);
  if (scribbles.length === 0) {
    return null;
  }
  return {
    mode,
    app,
    screenshot: root.getAttribute("screenshot"),
    scribbles,
  };
}
