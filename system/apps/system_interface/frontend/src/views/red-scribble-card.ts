/**
 * The Red Scribble batch card: renders one `<red-scribble-feedback>` message
 * (parsed into a `RedScribbleBatch` by red-scribble.ts) as a bordered card with
 * a red accent, a header, and a wrapping row of compact scribble tiles.
 *
 * Each tile shows a kind glyph and a short label; hovering a tile reveals a
 * floating detail card (kind, point, anchor, page, id, raw path) rendered on
 * `document.body` via `attachHoverTooltip` rather than as an in-flow child --
 * message rows live in scroll/overflow containers that would clip an absolutely
 * positioned child, so the detail must escape to the body layer.
 *
 * This is the mithril half; the parse half (no mithril) is red-scribble.ts.
 */

import m from "mithril";
import type { HoverTooltip } from "./hoverTooltip";
import { attachHoverTooltip } from "./hoverTooltip";
import type { IconName } from "./icons";
import { icon } from "./icons";
import type { RedScribbleBatch, Scribble, ScribbleKind } from "./red-scribble";

/** Glyph + colour-class per scribble kind; an unrecognised kind falls back to
 *  the neutral "text" styling so it still renders as a tile. */
const KIND_META: Record<ScribbleKind, { icon: IconName; cls: string }> = {
  stroke: { icon: "scribble-stroke", cls: "rs-kind--stroke" },
  voice: { icon: "scribble-voice", cls: "rs-kind--voice" },
  text: { icon: "scribble-text", cls: "rs-kind--text" },
};

function kindMeta(kind: string): { icon: IconName; cls: string } {
  return KIND_META[kind as ScribbleKind] ?? KIND_META.text;
}

/** Collapse whitespace and clip to `max` characters with an ellipsis. */
function ellipsize(text: string, max: number): string {
  const collapsed = text.replace(/\s+/g, " ").trim();
  return collapsed.length <= max ? collapsed : `${collapsed.slice(0, max - 1).trimEnd()}…`;
}

/** The tile's short label: "N stroke(s)" for a stroke group, an ellipsized
 *  quoted snippet for a note, and the kind name as a last resort. */
export function tileLabel(scribble: Scribble): string {
  if (scribble.kind === "stroke") {
    const count = scribble.strokes ?? 1;
    return `${count} ${count === 1 ? "stroke" : "strokes"}`;
  }
  if (scribble.note) {
    return `“${ellipsize(scribble.note, 30)}”`;
  }
  return scribble.kind || "scribble";
}

/** The floating detail card's body: a definition list of the scribble's fields,
 *  omitting any that are absent. Built as a DOM node (not a mithril vnode)
 *  because it is mounted on `document.body` by the hover tooltip, outside the
 *  mithril tree. */
function detailNode(scribble: Scribble): HTMLElement {
  const dl = document.createElement("dl");
  const addRow = (label: string, value: string | null): void => {
    if (!value) {
      return;
    }
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value;
    dl.append(dt, dd);
  };
  addRow("Kind", scribble.kind || null);
  addRow("Point", scribble.point);
  addRow("Anchor", scribble.anchor);
  addRow("Page", scribble.page);
  addRow("Id", scribble.id);
  addRow("Raw", scribble.raw);
  return dl;
}

/** One scribble tile. Attaches a body-level hover tooltip carrying the detail
 *  card on create, and disposes it on removal so nothing leaks when the
 *  virtualized row is recycled. */
function ScribbleTile(): m.Component<{ scribble: Scribble }> {
  let tooltip: HoverTooltip | null = null;
  return {
    oncreate(vnode) {
      tooltip = attachHoverTooltip(vnode.dom as HTMLElement, { className: "rs-tip", align: "left" });
      tooltip.setContent(detailNode(vnode.attrs.scribble));
    },
    onupdate(vnode) {
      tooltip?.setContent(detailNode(vnode.attrs.scribble));
    },
    onremove() {
      tooltip?.dispose();
      tooltip = null;
    },
    view(vnode) {
      const scribble = vnode.attrs.scribble;
      const meta = kindMeta(scribble.kind);
      return m("div", { class: "rs-tile" }, [
        m("span", { class: `rs-kind ${meta.cls}` }, m.trust(icon(meta.icon, { size: 14 }))),
        m("span", { class: "rs-tile-label" }, tileLabel(scribble)),
      ]);
    },
  };
}

/** The mode badge: a coloured pill for the known `batch`/`live` modes, a neutral
 *  pill for anything else. */
function renderModeBadge(mode: string): m.Vnode {
  const known = mode === "batch" || mode === "live";
  const cls = known ? `rs-batch-badge rs-batch-badge--${mode}` : "rs-batch-badge";
  return m("span", { class: cls }, mode);
}

/** "N scribbles · app-name", the header's summary line. */
function batchSummary(batch: RedScribbleBatch): string {
  const count = batch.scribbles.length;
  return `${count} ${count === 1 ? "scribble" : "scribbles"} · ${batch.app}`;
}

/** Render a parsed batch as the card. */
export function renderRedScribbleBatch(batch: RedScribbleBatch): m.Vnode {
  return m("div", { class: "rs-batch" }, [
    m("div", { class: "rs-batch-header" }, [
      m("span", { class: "rs-batch-logo" }, "R"),
      m("span", { class: "rs-batch-title" }, "Red Scribble"),
      renderModeBadge(batch.mode),
      m("span", { class: "rs-batch-app" }, batchSummary(batch)),
      batch.screenshot ? m("span", { class: "rs-batch-shot", title: batch.screenshot }, "screenshot") : null,
    ]),
    m(
      "div",
      { class: "rs-tiles" },
      batch.scribbles.map((scribble, index) => m(ScribbleTile, { key: index, scribble })),
    ),
  ]);
}
