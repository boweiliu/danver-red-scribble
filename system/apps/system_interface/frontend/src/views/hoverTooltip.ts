/**
 * The workspace's tooltip: a single bubble on ``document.body`` rather than
 * next to its target, positioned (fixed) under the target after a hover-intent
 * delay.
 *
 * Tab content in dockview can use neither of the app's usual tooltip
 * mechanisms. Native ``title`` is suppressed: dockview marks every tab
 * ``draggable`` (tab.js sets ``element.draggable = true``, plus
 * ``-webkit-user-drag: element``), and Chromium hides ``title`` tooltips on
 * draggable elements and their descendants. A CSS ``::after`` bubble (the
 * ``data-tooltip`` pattern used elsewhere) is clipped by the tab strip's
 * overflow -- ``.dv-tabs-container`` is ``overflow: auto`` and ``.dv-groupview``
 * is ``overflow: hidden``. A body-level, fixed-position element driven by our
 * own listeners avoids both: it is not a native tooltip, and it is not inside
 * the clipping container.
 *
 * That being the only mechanism that works everywhere in the workspace, it is
 * the one every workspace tooltip uses, and its look and timing are the minds
 * shell's ``.minds-tooltip`` (250ms hover-intent delay, keyboard focus too, no
 * fade, centered under the trigger with a 6px gap, flipped above on bottom
 * overflow, clamped to the viewport, dropped on leave / blur / click / scroll /
 * resize) so a tooltip here is indistinguishable from one in the surrounding
 * chrome. The measuring dance in ``showBubble`` mirrors the shell's
 * ``tooltip_triggers.js`` for the same reason.
 */

import type m from "mithril";

/** Hover-intent delay before a tooltip appears. */
const TOOLTIP_DELAY_MS = 250;
/** Gap between the trigger and the bubble. */
const TOOLTIP_GAP = 6;
/** Minimum gap from the window edges. */
const TOOLTIP_MARGIN = 6;

export interface HoverTooltip {
  /** Set the plain text shown on hover, or ``null`` to disable the tooltip. */
  setText(text: string | null): void;
  /** Set a rich DOM node shown on hover, or ``null`` to disable the tooltip. The
   *  node is adopted by the shared bubble; the caller keeps no reference to it.
   *  (Used by the dormant Red Scribble detail card -- see red-scribble-card.ts.) */
  setContent(node: Node | null): void;
  /** Remove listeners and any visible bubble. */
  dispose(): void;
}

export interface HoverTooltipOptions {
  /** CSS class on the shared bubble while this tooltip is shown. Defaults to
   *  ``minds-tooltip`` (the workspace tooltip look); a rich card can ask for its
   *  own (e.g. ``rs-tip``). */
  className?: string;
  /** ``center`` (default) pins the bubble centered under the target; ``left``
   *  pins its left edge to the target's left edge, clamped to the viewport --
   *  used by a wider rich-content card. */
  align?: "center" | "left";
}

/** The part of a ``DOMRect`` the placement needs. */
export interface TooltipAnchor {
  left: number;
  top: number;
  bottom: number;
  width: number;
}

export interface TooltipSize {
  width: number;
  height: number;
}

export interface TooltipPosition {
  left: number;
  top: number;
}

/**
 * Where the bubble goes: centered under the trigger with a ``TOOLTIP_GAP``
 * gap, flipped above when it would otherwise overflow the bottom (and there is
 * room up there), then clamped ``TOOLTIP_MARGIN`` from the viewport edges.
 */
export function placeTooltip(anchor: TooltipAnchor, bubble: TooltipSize, viewport: TooltipSize): TooltipPosition {
  const centered = anchor.left + anchor.width / 2 - bubble.width / 2;
  const below = anchor.bottom + TOOLTIP_GAP;
  const above = anchor.top - bubble.height - TOOLTIP_GAP;
  const overflowsBottom = below + bubble.height > viewport.height - TOOLTIP_MARGIN;
  const top = overflowsBottom && above >= TOOLTIP_MARGIN ? above : below;
  return {
    left: Math.max(TOOLTIP_MARGIN, Math.min(centered, viewport.width - TOOLTIP_MARGIN - bubble.width)),
    top: Math.max(TOOLTIP_MARGIN, top),
  };
}

// One bubble is enough: only one tooltip is ever visible, so every trigger
// shares it. ``pendingFor`` and ``shownFor`` name the trigger a scheduled or
// visible bubble belongs to, so a trigger only ever dismisses its own.
let bubbleElement: HTMLDivElement | null = null;
let pendingTimer: number | null = null;
let pendingFor: Element | null = null;
let shownFor: Element | null = null;
let isWindowWired = false;

function ensureBubble(): HTMLDivElement {
  if (bubbleElement === null) {
    bubbleElement = document.createElement("div");
    bubbleElement.className = "minds-tooltip";
    bubbleElement.setAttribute("role", "tooltip");
    document.body.appendChild(bubbleElement);
  }
  return bubbleElement;
}

function cancelPending(): void {
  if (pendingTimer !== null) {
    window.clearTimeout(pendingTimer);
    pendingTimer = null;
  }
  pendingFor = null;
}

function hideBubble(): void {
  if (bubbleElement !== null) {
    bubbleElement.style.display = "none";
  }
  shownFor = null;
}

/** Drop the tooltip whoever it belongs to -- what the window-level events do. */
function dropTooltip(): void {
  cancelPending();
  hideBubble();
}

/** What a trigger wants shown: exactly one of ``text``/``content`` is set, plus
 *  the bubble class and alignment the attachment asked for. */
interface BubbleContent {
  text: string | null;
  content: Node | null;
  className: string;
  align: "center" | "left";
}

/** Left-anchored placement (for a wide rich card): the bubble's left edge tracks
 *  the target's left edge, below it with the standard gap, clamped to the
 *  viewport. Distinct from ``placeTooltip``'s centered/flip-above behaviour. */
function placeTooltipLeft(anchor: TooltipAnchor, bubble: TooltipSize, viewport: TooltipSize): TooltipPosition {
  const maxLeft = Math.max(TOOLTIP_MARGIN, viewport.width - bubble.width - TOOLTIP_MARGIN);
  return {
    left: Math.min(Math.max(TOOLTIP_MARGIN, anchor.left), maxLeft),
    top: anchor.bottom + TOOLTIP_GAP,
  };
}

function showBubble(target: Element, payload: BubbleContent): void {
  const element = ensureBubble();
  element.className = payload.className;
  if (payload.content !== null) {
    element.replaceChildren(payload.content);
  } else {
    element.textContent = payload.text;
  }
  // Measure at the natural width: clear the width a previous show fixed, and
  // park the bubble at the origin first, since a stale ``left`` would cap the
  // shrink-to-fit width at (viewport - left) and wrap the label.
  element.style.width = "";
  element.style.left = "0";
  element.style.top = "0";
  element.style.visibility = "hidden";
  element.style.display = "inline-flex";
  // getBoundingClientRect, not offsetWidth: offsetWidth rounds the shrink-to-fit
  // width DOWN (e.g. 132.4 -> 132), and fixing the width to that leaves the
  // content a fraction short and wraps the last word. Ceil instead.
  const measured = element.getBoundingClientRect();
  const size = { width: Math.ceil(measured.width), height: Math.ceil(measured.height) };
  const viewport = { width: window.innerWidth, height: window.innerHeight };
  const anchor = target.getBoundingClientRect();
  const position =
    payload.align === "left" ? placeTooltipLeft(anchor, size, viewport) : placeTooltip(anchor, size, viewport);
  // Fix the width so the bubble does not reflow if the viewport later changes.
  element.style.width = `${size.width}px`;
  element.style.left = `${position.left}px`;
  element.style.top = `${position.top}px`;
  element.style.visibility = "visible";
  shownFor = target;
}

function wireWindowListeners(): void {
  if (isWindowWired) {
    return;
  }
  isWindowWired = true;
  // Any scroll (capture, so nested scrollers count), resize or window blur
  // slides the trigger out from under a shown bubble, so drop it.
  window.addEventListener("scroll", dropTooltip, true);
  window.addEventListener("resize", dropTooltip);
  window.addEventListener("blur", dropTooltip);
}

export function attachHoverTooltip(target: Element, options: HoverTooltipOptions = {}): HoverTooltip {
  const className = options.className ?? "minds-tooltip";
  const align = options.align ?? "center";
  // Exactly one of these is set at a time; the other is null.
  let text: string | null = null;
  let content: Node | null = null;

  wireWindowListeners();

  const hasPayload = (): boolean => text !== null || content !== null;
  const payload = (): BubbleContent => ({ text, content, className, align });

  const dismiss = (): void => {
    if (pendingFor === target) {
      cancelPending();
    }
    if (shownFor === target) {
      hideBubble();
    }
  };

  // Both entry points into a visible bubble: the delay elapsing, and keyboard
  // focus, which skips the delay. Either way whatever else was queued loses.
  const showNow = (): void => {
    cancelPending();
    if (hasPayload()) {
      showBubble(target, payload());
    }
  };

  const onEnter = (): void => {
    if (!hasPayload()) {
      return;
    }
    cancelPending();
    pendingFor = target;
    pendingTimer = window.setTimeout(showNow, TOOLTIP_DELAY_MS);
  };

  // Keyboard focus only -- not focus that came from a mouse click, which would
  // flash the tooltip and then immediately hide it on the click.
  const onFocus = (): void => {
    if (target.matches(":focus-visible")) {
      showNow();
    }
  };

  target.addEventListener("mouseenter", onEnter);
  target.addEventListener("mouseleave", dismiss);
  target.addEventListener("click", dismiss);
  target.addEventListener("focus", onFocus);
  target.addEventListener("blur", dismiss);

  // Re-render in place when the payload changes: drop the bubble when emptied,
  // else refresh it if this trigger's bubble is the one currently shown.
  const refresh = (): void => {
    if (!hasPayload()) {
      dismiss();
    } else if (shownFor === target) {
      showBubble(target, payload());
    }
  };

  return {
    setText(next: string | null): void {
      text = next;
      content = null;
      refresh();
    },
    setContent(node: Node | null): void {
      content = node;
      text = null;
      refresh();
    },
    dispose(): void {
      target.removeEventListener("mouseenter", onEnter);
      target.removeEventListener("mouseleave", dismiss);
      target.removeEventListener("click", dismiss);
      target.removeEventListener("focus", onFocus);
      target.removeEventListener("blur", dismiss);
      dismiss();
    },
  };
}

const tooltipsByElement = new WeakMap<Element, HoverTooltip>();

/**
 * The mithril form: spread into an element's attrs in place of a native
 * ``title``, e.g. ``m("button", { onclick, ...hoverTooltipAttrs("Close") })``.
 * The element keeps its own ``aria-label`` -- the bubble is decoration, not an
 * accessible name.
 */
export function hoverTooltipAttrs(text: string): m.Attributes {
  return {
    oncreate: (vnode: m.VnodeDOM): void => {
      const tooltip = attachHoverTooltip(vnode.dom);
      tooltip.setText(text);
      tooltipsByElement.set(vnode.dom, tooltip);
    },
    onupdate: (vnode: m.VnodeDOM): void => {
      tooltipsByElement.get(vnode.dom)?.setText(text);
    },
    onremove: (vnode: m.VnodeDOM): void => {
      tooltipsByElement.get(vnode.dom)?.dispose();
      tooltipsByElement.delete(vnode.dom);
    },
  };
}
