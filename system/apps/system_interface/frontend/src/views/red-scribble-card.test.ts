import { describe, expect, it, vi } from "vitest";

// Mithril captures `requestAnimationFrame` at import time to schedule redraws;
// vitest's node environment has none, so polyfill it before the import below.
vi.hoisted(() => {
  globalThis.requestAnimationFrame ??= ((cb: FrameRequestCallback): number =>
    setTimeout(() => cb(0), 0) as unknown as number) as typeof globalThis.requestAnimationFrame;
});

import type { RedScribbleBatch, Scribble } from "./red-scribble";
import { renderRedScribbleBatch, tileLabel } from "./red-scribble-card";

type VnodeLike = { tag?: unknown; attrs?: Record<string, unknown>; children?: unknown; text?: unknown };

function* walk(node: unknown): Generator<VnodeLike> {
  if (Array.isArray(node)) {
    for (const child of node) yield* walk(child);
    return;
  }
  if (node !== null && typeof node === "object") {
    const vnode = node as VnodeLike;
    yield vnode;
    if (vnode.children !== undefined) yield* walk(vnode.children);
  }
}

// Mithril rewrites a `class` attr to `className` at construction time.
function classOf(v: VnodeLike): string | null {
  return typeof v.attrs?.className === "string" ? v.attrs.className : null;
}

function withClass(tree: unknown, cls: string): VnodeLike | null {
  for (const v of walk(tree)) {
    if (classOf(v) === cls) return v;
  }
  return null;
}

function withClassPrefix(tree: unknown, prefix: string): VnodeLike | null {
  for (const v of walk(tree)) {
    if (classOf(v)?.startsWith(prefix)) return v;
  }
  return null;
}

// Mithril normalizes a text child into a `{ tag: "#", children: <string> }`
// vnode at construction time, so read the first such string under a node.
function textOf(node: unknown): string | null {
  for (const v of walk(node)) {
    if (v.tag === "#" && typeof v.children === "string") return v.children;
  }
  return null;
}

function scribble(overrides: Partial<Scribble>): Scribble {
  return {
    id: "fbk-1",
    kind: "text",
    point: "1,2",
    anchor: "body",
    page: "https://x",
    raw: "/r.json",
    strokes: null,
    note: "a note",
    ...overrides,
  };
}

function batch(overrides: Partial<RedScribbleBatch>): RedScribbleBatch {
  return {
    mode: "batch",
    app: "scribble-box",
    screenshot: null,
    scribbles: [],
    ...overrides,
  };
}

describe("tileLabel", () => {
  it("labels a stroke by its (pluralized) count, defaulting a null count to one", () => {
    expect(tileLabel(scribble({ kind: "stroke", strokes: 1 }))).toBe("1 stroke");
    expect(tileLabel(scribble({ kind: "stroke", strokes: 3 }))).toBe("3 strokes");
    expect(tileLabel(scribble({ kind: "stroke", strokes: null }))).toBe("1 stroke");
  });

  it("quotes a short note verbatim", () => {
    expect(tileLabel(scribble({ kind: "voice", note: "I want an earthquake" }))).toBe("“I want an earthquake”");
  });

  it("ellipsizes a long note to about 30 characters", () => {
    const label = tileLabel(scribble({ kind: "text", note: "this note is definitely much longer than thirty chars" }));
    expect(label.startsWith("“")).toBe(true);
    expect(label.endsWith("”")).toBe(true);
    expect(label).toContain("…");
    // The visible text between the quotes stays around the 30-char budget.
    expect(label.length).toBeLessThanOrEqual(33);
  });

  it("falls back to the kind name for a note kind with no text", () => {
    expect(tileLabel(scribble({ kind: "text", note: null }))).toBe("text");
  });
});

describe("renderRedScribbleBatch", () => {
  const three = batch({
    screenshot: "/abs/shot.png",
    scribbles: [
      scribble({ kind: "stroke", strokes: 1, note: null }),
      scribble({ kind: "voice", note: "I want an earthquake" }),
      scribble({ kind: "text", note: "earthquake button" }),
    ],
  });

  it("heads the card with the brand, a batch badge, and an 'N scribbles · app' summary", () => {
    const tree = renderRedScribbleBatch(three);
    expect(textOf(withClass(tree, "rs-batch-title"))).toBe("Red Scribble");
    const badge = withClassPrefix(tree, "rs-batch-badge");
    expect(badge?.attrs?.className).toContain("rs-batch-badge--batch");
    expect(textOf(badge)).toBe("batch");
    expect(textOf(withClass(tree, "rs-batch-app"))).toBe("3 scribbles · scribble-box");
  });

  it("renders one tile per scribble", () => {
    const tiles = withClass(renderRedScribbleBatch(three), "rs-tiles");
    expect(Array.isArray(tiles?.children)).toBe(true);
    expect((tiles?.children as unknown[]).length).toBe(3);
  });

  it("shows the screenshot affordance carrying the path as its title", () => {
    const shot = withClass(renderRedScribbleBatch(three), "rs-batch-shot");
    expect(shot).not.toBeNull();
    expect(shot?.attrs?.title).toBe("/abs/shot.png");
  });

  it("omits the screenshot affordance when there is no screenshot", () => {
    const one = batch({ mode: "live", scribbles: [scribble({})] });
    expect(withClass(renderRedScribbleBatch(one), "rs-batch-shot")).toBeNull();
  });

  it("gives the live mode its own badge modifier and singularizes a lone scribble", () => {
    const one = batch({ mode: "live", app: "notes", scribbles: [scribble({})] });
    const tree = renderRedScribbleBatch(one);
    expect(withClassPrefix(tree, "rs-batch-badge")?.attrs?.className).toContain("rs-batch-badge--live");
    expect(textOf(withClass(tree, "rs-batch-app"))).toBe("1 scribble · notes");
  });

  it("uses a neutral badge (no modifier) for an unrecognised mode", () => {
    const odd = batch({ mode: "weird", scribbles: [scribble({})] });
    expect(withClassPrefix(renderRedScribbleBatch(odd), "rs-batch-badge")?.attrs?.className).toBe("rs-batch-badge");
  });
});
