// The parser uses the browser's DOMParser (text/xml), absent in vitest's default
// node environment; run this file under jsdom -- the DOM environment the other
// DOM-needing tests here use (appIcon.test.ts, Sidebar.test.ts) -- so DOMParser
// and its parsererror behaviour are available exactly as in the browser.
// @vitest-environment jsdom

import { describe, expect, it } from "vitest";
import { classifyUserMessage } from "./message-classification";
import { UserMessageKind } from "./message-kinds";
import { looksLikeRedScribbleFeedback, parseRedScribbleFeedback } from "./red-scribble";

// A genuine document, matching what build_feedback_message emits (see
// system/libs/red_scribble/src/red_scribble/dispatch.py): the root envelope with
// mode/app/count/screenshot, an instructional line, a self-closing stroke, and
// two note scribbles carrying their text as element content. Attribute values
// are escaped (quoteattr) and note text is escaped (escape) upstream, so the
// anchor's ">" arrives as "&gt;".
const BATCH_DOC = `<red-scribble-feedback mode="batch" app="scribble-box" count="3" screenshot="/abs/shot.png">
Act per the /red-scribble-feedback skill. Distill intent from the fields below before reaching for the shared screenshot (it is slow).
<scribble id="fbk-7e32aba5" kind="stroke" point="534.19,86.38" anchor="html &gt; body &gt; main" strokes="1" page="https://example/app" raw="/abs/1.json"/>
<scribble id="fbk-fc180304" kind="voice" point="590.61,116.48" anchor="main &gt; div" page="https://example/app" raw="/abs/2.json">I want an earthquake</scribble>
<scribble id="fbk-48285e2e" kind="text" point="618.27,159.35" anchor="main &gt; div" page="https://example/app" raw="/abs/3.json">earthquake button</scribble>
</red-scribble-feedback>`;

describe("looksLikeRedScribbleFeedback", () => {
  it("matches only when the message starts with the root tag", () => {
    expect(looksLikeRedScribbleFeedback(BATCH_DOC)).toBe(true);
    expect(looksLikeRedScribbleFeedback("  \n<red-scribble-feedback mode='x'>")).toBe(true);
    // Prose that merely mentions the tag is not a document.
    expect(looksLikeRedScribbleFeedback("how does <red-scribble-feedback> render?")).toBe(false);
    expect(looksLikeRedScribbleFeedback("just a normal message")).toBe(false);
  });
});

describe("parseRedScribbleFeedback", () => {
  it("parses the header fields and every scribble of a real batch", () => {
    const batch = parseRedScribbleFeedback(BATCH_DOC);
    expect(batch).not.toBeNull();
    if (batch === null) return; // narrow for the compiler
    expect(batch.mode).toBe("batch");
    expect(batch.app).toBe("scribble-box");
    expect(batch.screenshot).toBe("/abs/shot.png");
    expect(batch.scribbles).toHaveLength(3);
  });

  it("reads a self-closing stroke's count and leaves its note empty", () => {
    const stroke = parseRedScribbleFeedback(BATCH_DOC)?.scribbles[0];
    expect(stroke).toMatchObject({
      id: "fbk-7e32aba5",
      kind: "stroke",
      point: "534.19,86.38",
      strokes: 1,
      page: "https://example/app",
      raw: "/abs/1.json",
      note: null,
    });
    // The escaped ">" in the anchor is decoded back by the XML parser.
    expect(stroke?.anchor).toBe("html > body > main");
  });

  it("reads a note scribble's text as its content and no stroke count", () => {
    const voice = parseRedScribbleFeedback(BATCH_DOC)?.scribbles[1];
    expect(voice).toMatchObject({
      id: "fbk-fc180304",
      kind: "voice",
      point: "590.61,116.48",
      strokes: null,
      note: "I want an earthquake",
    });
  });

  it("omits an absent screenshot (screenshot is optional)", () => {
    const doc = `<red-scribble-feedback mode="live" app="notes" count="1">
<scribble id="fbk-1" kind="text" point="1,2" anchor="body" page="p" raw="/r.json">hi</scribble>
</red-scribble-feedback>`;
    const batch = parseRedScribbleFeedback(doc);
    expect(batch?.screenshot).toBeNull();
    expect(batch?.mode).toBe("live");
  });

  it("parses every scribble even when the count attribute is absent", () => {
    const doc = `<red-scribble-feedback mode="batch" app="x">
<scribble id="a" kind="text" raw="/r">one</scribble>
<scribble id="b" kind="text" raw="/r">two</scribble>
</red-scribble-feedback>`;
    expect(parseRedScribbleFeedback(doc)?.scribbles).toHaveLength(2);
  });

  it("does not match a truncated (malformed) document", () => {
    // Cut off mid-way, as a partial send might arrive: not well-formed XML.
    const truncated = BATCH_DOC.slice(0, BATCH_DOC.length - 40);
    expect(parseRedScribbleFeedback(truncated)).toBeNull();
  });

  it("does not match when the root tag is wrong", () => {
    const wrong = `<other-feedback mode="batch" app="x"><scribble id="a" raw="/r"/></other-feedback>`;
    expect(parseRedScribbleFeedback(wrong)).toBeNull();
  });

  it("does not match when app or mode is missing", () => {
    const noApp = `<red-scribble-feedback mode="batch"><scribble id="a" kind="text" raw="/r">x</scribble></red-scribble-feedback>`;
    const noMode = `<red-scribble-feedback app="x"><scribble id="a" kind="text" raw="/r">x</scribble></red-scribble-feedback>`;
    expect(parseRedScribbleFeedback(noApp)).toBeNull();
    expect(parseRedScribbleFeedback(noMode)).toBeNull();
  });

  it("does not match a document with no scribbles", () => {
    const empty = `<red-scribble-feedback mode="batch" app="x" count="0">no scribbles here</red-scribble-feedback>`;
    expect(parseRedScribbleFeedback(empty)).toBeNull();
  });

  it("does not match plain prose that only mentions the tag name", () => {
    expect(parseRedScribbleFeedback("what is <red-scribble-feedback>?")).toBeNull();
    expect(parseRedScribbleFeedback("a normal message")).toBeNull();
  });
});

// The detector lives in message-classification but needs DOMParser, so its
// tests belong here under jsdom rather than in message-classification.test.ts
// (which runs in the DOM-less node environment).
describe("classifyUserMessage: Red Scribble feedback", () => {
  it("classifies a well-formed feedback document as RedScribbleFeedback, body unchanged", () => {
    const c = classifyUserMessage({ content: BATCH_DOC });
    expect(c.kind).toBe(UserMessageKind.RedScribbleFeedback);
    expect(c.label).toBeNull();
    // The body stays the raw document so the card renderer re-parses it.
    expect(c.body).toBe(BATCH_DOC);
  });

  it("falls back to a plain UserPrompt for a truncated feedback document", () => {
    const truncated = BATCH_DOC.slice(0, BATCH_DOC.length - 40);
    expect(classifyUserMessage({ content: truncated }).kind).toBe(UserMessageKind.UserPrompt);
  });
});
