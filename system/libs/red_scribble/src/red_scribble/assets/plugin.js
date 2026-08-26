/*
 * Red Scribble -- framework-agnostic UI-feedback plug-in.
 *
 * An app opts in with one <script> tag pointing at Red Scribble's own service origin (see
 * red_scribble/embed.py). The plug-in then runs inside the app's document but talks back to the
 * origin it was served from:
 *   - config   GET  <red-scribble origin>/config
 *   - feedback POST <red-scribble origin>/feedback   (one envelope of scribbles per send)
 *
 * That is cross-origin, so every request is credentialed: the workspace's session cookie is
 * scoped to the whole origin family, and Red Scribble reflects only origins inside it. It is
 * intentionally dependency-light: scribbles render on a plain <canvas> (no dependency);
 * html2canvas (screenshots) and the voice modules are served from the same origin and pulled on
 * demand, so the host app needs no build step and no CDN.
 *
 * State machine (see system/libs/red_scribble/docs/concise.md):
 *   Inactive --click--> Active (overlay intercepts ALL page input; you draw/scribble)
 *   Active   --click--> Inactive (scribbles hide but are retained; page is interactive again)
 *   Active   --long-press--> menu (Live toggle, target agent, send pending)
 *   reactivating re-renders retained scribbles, re-anchored to their DOM elements.
 */
(function () {
  "use strict";
  if (window.__RED_SCRIBBLE_LOADED__) return;
  window.__RED_SCRIBBLE_LOADED__ = true;

  // Every Red Scribble URL is absolute against the origin this script came from. Read
  // document.currentScript now, while the script is still executing -- it is null inside every
  // later callback.
  var RS = (function () {
    var script = document.currentScript;
    return script && script.src ? new URL(script.src, location.href).origin : location.origin;
  })();

  var Z = 2147483000; // sit above essentially everything the host app renders
  var LONG_PRESS_MS = 500;
  var GROUP_DEBOUNCE_MS = 4000; // strokes within this window share one anchor (spec: 3-5s)
  var VOICE_HOLD_MS = 350;      // a double-click held beyond this starts voice capture
  var SEND_DEBOUNCE_MS = 2000;  // live-mode gather window; same scale as one agent-delivery round trip
  var H2C_URL = RS + "/html2canvas.js";   // vendored: no public-CDN dependency

  var state = {
    active: false,
    config: { target_agent_id: null, mode: "batch", agents: [] },
    scribbles: [], // {points:[{x,y}], anchor:{selector,originX,originY}|null, kind:"stroke"}
    pending: [], // scribbles awaiting the next send operation (both modes)
    currentGroupAnchor: null,
    lastStrokeAt: 0,
  };

  // small DOM helpers
  function el(tag, style, attrs) {
    var node = document.createElement(tag);
    if (style) node.style.cssText = style;
    if (attrs) for (var k in attrs) node.setAttribute(k, attrs[k]);
    return node;
  }

  // A best-effort, reasonably stable CSS selector for an element, so a scribble can be
  // re-anchored on reactivation even after some DOM churn. Falls back to nth-child paths.
  function cssPath(node) {
    if (!(node instanceof Element)) return null;
    if (node.id) return "#" + CSS.escape(node.id);
    var parts = [];
    var cur = node;
    while (cur && cur.nodeType === 1 && parts.length < 6) {
      var sel = cur.nodeName.toLowerCase();
      if (cur.parentElement) {
        var siblings = Array.prototype.filter.call(
          cur.parentElement.children,
          function (c) { return c.nodeName === cur.nodeName; }
        );
        if (siblings.length > 1) sel += ":nth-of-type(" + (siblings.indexOf(cur) + 1) + ")";
      }
      parts.unshift(sel);
      if (cur.id) { parts[0] = "#" + CSS.escape(cur.id); break; }
      cur = cur.parentElement;
    }
    return parts.join(" > ");
  }

  // config
  function loadConfig() {
    return fetch(RS + "/config", { credentials: "include" })
      .then(function (r) { return r.json(); })
      .then(function (cfg) { state.config = cfg; return cfg; })
      .catch(function () { return state.config; });
  }

  // the floating logo
  var logo, overlay, canvas, ctx, menu, notesLayer;
  var _noteBoxes = [];

  function buildLogo() {
    logo = el(
      "div",
      "position:fixed;right:20px;bottom:20px;width:56px;height:56px;border-radius:50%;" +
        "background:#e11d2a;box-shadow:0 4px 14px rgba(0,0,0,.35);cursor:pointer;z-index:" +
        (Z + 1) + ";display:flex;align-items:center;justify-content:center;" +
        "transition:transform .12s ease,box-shadow .12s ease;",
      { title: "Red Scribble" }
    );
    logo.innerHTML =
      '<svg width="40" height="40" viewBox="0 0 120 120" fill="none" stroke="#fff" ' +
      'stroke-width="9" stroke-linecap="round" stroke-linejoin="round">' +
      '<path d="M 16.00 95.84 C 16.03 95.84 16.05 95.84 16.17 95.84 C 16.28 95.84 16.24 95.84 16.68 95.84 C 17.12 95.84 18.39 95.84 18.81 95.84 C 19.22 95.84 18.91 95.84 19.17 95.84 C 19.43 95.84 20.11 95.84 20.37 95.84 C 20.63 95.84 20.57 95.84 20.72 95.84 C 20.87 95.84 21.03 95.84 21.26 95.84 C 21.48 95.84 21.78 95.88 22.05 95.84 C 22.32 95.81 22.63 95.74 22.89 95.64 C 23.15 95.54 23.38 95.35 23.62 95.22 C 23.87 95.09 24.11 94.98 24.35 94.86 C 24.59 94.75 24.83 94.64 25.06 94.50 C 25.30 94.36 25.13 97.56 25.78 94.03 C 26.43 90.50 29.19 77.14 28.95 73.31 C 28.72 69.48 25.39 71.46 24.37 71.04 C 23.35 70.62 23.20 70.84 22.83 70.80 C 22.46 70.76 20.41 69.19 22.15 70.80 C 23.89 72.41 30.54 78.61 33.27 80.46 C 36.00 82.31 37.17 81.43 38.52 81.90 C 39.87 82.37 40.70 82.92 41.39 83.26 C 42.08 83.61 42.26 83.69 42.66 83.96 C 43.07 84.24 43.29 84.40 43.80 84.93 C 44.30 85.45 42.27 86.41 45.72 87.10 C 49.16 87.80 61.01 89.67 64.48 89.09 C 67.95 88.50 66.01 85.27 66.55 83.59 C 67.09 81.91 67.41 80.60 67.72 79.01 C 68.04 77.42 68.22 75.73 68.42 74.05 C 68.62 72.36 68.84 70.68 68.92 68.90 C 69.00 67.12 68.92 64.67 68.92 63.36 C 68.92 62.04 68.92 62.41 68.92 61.02 C 68.92 59.63 68.97 56.49 68.92 55.02 C 68.87 53.56 68.78 53.28 68.63 52.25 C 68.48 51.22 68.43 50.47 68.02 48.84 C 67.62 47.22 66.72 44.08 66.22 42.51 C 65.72 40.95 65.43 40.47 65.03 39.45 C 64.63 38.44 64.18 37.27 63.81 36.42 C 63.44 35.56 63.18 34.98 62.83 34.32 C 62.48 33.66 62.09 33.08 61.72 32.45 C 61.35 31.82 60.97 31.10 60.61 30.54 C 60.26 29.97 59.95 29.55 59.58 29.05 C 59.21 28.55 58.78 27.99 58.39 27.55 C 58.01 27.11 57.63 26.74 57.27 26.41 C 56.90 26.09 56.73 25.91 56.19 25.60 C 55.65 25.30 54.51 24.79 54.02 24.59 C 53.53 24.39 53.55 24.45 53.23 24.39 C 52.92 24.34 52.52 24.28 52.12 24.24 C 51.72 24.21 51.28 24.21 50.84 24.20 C 50.39 24.19 49.91 24.18 49.48 24.17 C 49.04 24.17 48.62 24.17 48.23 24.16 C 47.84 24.16 47.52 24.12 47.14 24.16 C 46.75 24.20 46.31 24.23 45.92 24.39 C 45.53 24.55 45.15 24.84 44.80 25.12 C 44.44 25.39 44.12 25.71 43.78 26.03 C 43.45 26.34 43.07 26.65 42.79 26.99 C 42.50 27.33 42.29 27.68 42.08 28.06 C 41.87 28.44 41.68 28.87 41.52 29.27 C 41.35 29.67 41.19 30.10 41.10 30.47 C 41.01 30.83 41.00 31.10 40.98 31.46 C 40.96 31.82 40.98 32.10 40.98 32.63 C 40.98 33.15 40.98 34.12 40.98 34.58 C 40.98 35.04 40.91 35.04 40.98 35.36 C 41.05 35.69 40.98 35.94 41.42 36.51 C 41.86 37.08 43.01 38.26 43.63 38.79 C 44.25 39.33 44.59 39.44 45.13 39.73 C 45.67 40.02 45.85 40.16 46.87 40.52 C 47.89 40.88 50.10 41.53 51.24 41.87 C 52.38 42.20 52.84 42.34 53.70 42.53 C 54.56 42.73 55.49 42.88 56.40 43.06 C 57.31 43.24 58.29 43.39 59.17 43.59 C 60.06 43.79 60.87 44.06 61.69 44.25 C 62.52 44.44 63.29 44.57 64.14 44.74 C 64.99 44.90 65.63 44.96 66.77 45.23 C 67.92 45.50 69.99 46.09 71.01 46.36 C 72.03 46.63 71.80 46.54 72.88 46.86 C 73.95 47.17 76.30 47.85 77.47 48.23 C 78.64 48.62 79.13 48.84 79.92 49.15 C 80.71 49.46 81.53 49.80 82.21 50.09 C 82.89 50.38 83.44 50.62 84.00 50.87 C 84.56 51.12 84.88 51.27 85.56 51.61 C 86.23 51.96 87.29 52.51 88.05 52.93 C 88.81 53.34 89.54 53.75 90.13 54.10 C 90.72 54.45 91.07 54.68 91.60 55.04 C 92.13 55.41 92.78 55.87 93.32 56.27 C 93.86 56.68 94.36 57.08 94.83 57.47 C 95.30 57.86 95.71 58.21 96.15 58.63 C 96.59 59.04 97.04 59.48 97.48 59.95 C 97.93 60.42 98.44 60.99 98.83 61.44 C 99.22 61.90 99.53 62.33 99.81 62.70 C 100.10 63.07 100.31 63.31 100.54 63.65 C 100.78 63.99 100.98 64.34 101.22 64.74 C 101.45 65.15 101.64 65.45 101.95 66.08 C 102.27 66.71 102.86 67.90 103.11 68.54 C 103.36 69.17 103.32 69.21 103.46 69.90 C 103.60 70.59 103.86 71.98 103.94 72.68 C 104.03 73.38 103.97 73.65 103.98 74.09 C 103.99 74.53 103.99 74.92 104.00 75.32 C 104.00 75.73 104.00 76.14 104.00 76.55 C 104.00 76.96 104.02 77.37 104.00 77.78 C 103.98 78.20 104.01 78.54 103.87 79.02 C 103.72 79.50 103.43 80.15 103.11 80.65 C 102.80 81.14 102.38 81.62 101.96 81.98 C 101.53 82.35 101.35 82.50 100.55 82.82 C 99.76 83.14 98.20 83.69 97.19 83.93 C 96.18 84.16 95.60 84.12 94.49 84.21 C 93.39 84.29 91.78 84.40 90.57 84.43 C 89.36 84.46 88.34 84.53 87.22 84.37 C 86.11 84.21 85.10 83.91 83.89 83.48 C 82.68 83.05 80.60 82.06 79.94 81.78 "/></svg>';

    var pressTimer = null;
    var longPressed = false;
    logo.addEventListener("pointerdown", function () {
      longPressed = false;
      pressTimer = setTimeout(function () { longPressed = true; openMenu(); }, LONG_PRESS_MS);
    });
    var cancel = function () { if (pressTimer) { clearTimeout(pressTimer); pressTimer = null; } };
    logo.addEventListener("pointerup", function () {
      cancel();
      if (!longPressed) toggleActive();
    });
    logo.addEventListener("pointerleave", cancel);
    document.body.appendChild(logo);
    reflectLogo();
  }

  function reflectLogo() {
    logo.style.transform = state.active ? "scale(1.12)" : "scale(1)";
    logo.style.boxShadow = state.active
      ? "0 0 0 4px rgba(225,29,42,.35), 0 4px 14px rgba(0,0,0,.35)"
      : "0 4px 14px rgba(0,0,0,.35)";
  }

  // active/inactive
  function toggleActive() { state.active ? deactivate() : activate(); }

  // Activate/deactivate drive ONE lifecycle: the overlay (with the scribble canvas) and the notes
  // layer are both built on activate and torn down on deactivate, so strokes and notes show and
  // hide together. Scribbles persist in state.scribbles and are re-rendered on reactivation.
  function activate() {
    state.active = true;
    buildOverlay();
    buildNotesLayer();
    renderStrokes();
    renderNotes();
    reflectLogo();
    // Warm the on-device voice model now, in the background, so the first hold-to-talk doesn't
    // lose the opening words while it loads.
    ensureVoice().catch(function () {});
  }

  function deactivate() {
    state.active = false;
    if (overlay) { overlay.remove(); overlay = null; canvas = null; ctx = null; }
    if (notesLayer) { notesLayer.remove(); notesLayer = null; }
    _noteBoxes = [];
    closeMenu();
    reflectLogo();
  }

  function buildOverlay() {
    overlay = el(
      "div",
      "position:fixed;inset:0;z-index:" + Z + ";cursor:crosshair;background:rgba(0,0,0,0.02);" +
        "touch-action:none;"
    );
    canvas = el("canvas", "position:absolute;inset:0;width:100%;height:100%;");
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    ctx = canvas.getContext("2d");
    overlay.appendChild(canvas);
    document.body.appendChild(overlay);
    wireDrawing();
  }

  // Draw a scribble as a round-capped polyline (no external dependency). STROKE_SIZE is the pen size.
  var STROKE_SIZE = 2;
  function drawStroke(points) {
    if (!ctx || !points.length) return;
    ctx.strokeStyle = "#e11d2a";
    ctx.lineWidth = STROKE_SIZE;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    for (var i = 1; i < points.length; i++) ctx.lineTo(points[i].x, points[i].y);
    ctx.stroke();
  }

  // The element under a screen point, looked up *through* our capture overlay (which otherwise
  // absorbs the hit). The single place that toggles overlay pointer-events for a hit-test.
  function elementUnder(x, y) {
    if (overlay) overlay.style.pointerEvents = "none";
    var target = document.elementFromPoint(x, y);
    if (overlay) overlay.style.pointerEvents = "auto";
    return target;
  }

  function anchorFor(x, y) {
    var now = Date.now();
    if (state.currentGroupAnchor && now - state.lastStrokeAt < GROUP_DEBOUNCE_MS) {
      state.lastStrokeAt = now;
      return state.currentGroupAnchor;
    }
    // Start a new group: anchor to the element under the first point.
    var target = elementUnder(x, y);
    var selector = target ? cssPath(target) : null;
    var rect = target ? target.getBoundingClientRect() : { left: 0, top: 0 };
    state.currentGroupAnchor = { selector: selector, originX: rect.left, originY: rect.top };
    state.lastStrokeAt = now;
    return state.currentGroupAnchor;
  }

  function wireDrawing() {
    var drawing = false;
    var points = [];
    var lastTap = 0;
    var lastTapPt = null;
    var pendingDouble = null;   // a double-click awaiting release (text) vs hold (voice)
    var holdTimer = null;

    canvas.addEventListener("pointerdown", function (e) {
      // Double-click opens a text box; double-click-AND-HOLD starts voice capture. On the second
      // tap we wait: released quickly -> text box; still held past VOICE_HOLD_MS -> voice.
      var now = Date.now();
      var isDouble = now - lastTap < 300 && lastTapPt &&
        Math.abs(e.clientX - lastTapPt.x) < 24 && Math.abs(e.clientY - lastTapPt.y) < 24;
      if (isDouble) {
        lastTap = 0;
        var px = e.clientX, py = e.clientY;
        pendingDouble = { x: px, y: py };
        holdTimer = setTimeout(function () {
          holdTimer = null; pendingDouble = null;
          startVoice(px, py);
        }, VOICE_HOLD_MS);
        try { canvas.setPointerCapture(e.pointerId); } catch (_) {}
        return;
      }
      lastTap = now;
      lastTapPt = { x: e.clientX, y: e.clientY };

      drawing = true;
      points = [{ x: e.clientX, y: e.clientY }];
      canvas.setPointerCapture(e.pointerId);
    });

    canvas.addEventListener("pointermove", function (e) {
      if (!drawing) return;
      points.push({ x: e.clientX, y: e.clientY });
      // Live feedback: clear + redraw retained strokes + the in-progress stroke.
      renderStrokes();
      drawStroke(points);
    });

    var finish = function () {
      if (!drawing) return;
      drawing = false;
      if (points.length > 1) {
        var anchor = anchorFor(points[0].x, points[0].y);
        var scribble = { kind: "stroke", points: points.slice(), anchor: anchor, id: null };
        state.scribbles.push(scribble);
        queueStroke(scribble);
      }
      points = [];
    };
    var onUp = function () {
      if (voiceState) { stopVoice(); return; }        // release ends a voice recording
      if (pendingDouble) {                             // released before the hold threshold -> text
        if (holdTimer) { clearTimeout(holdTimer); holdTimer = null; }
        var pd = pendingDouble; pendingDouble = null;
        openTextBox(pd.x, pd.y);
        return;
      }
      finish();
    };
    canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("pointercancel", onUp);
  }

  // The canvas renderer draws only stroke scribbles; text/voice scribbles are drawn by renderNotes.
  // (Both read the one state.scribbles list and each filters to the kinds it owns.)
  function renderStrokes() {
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    state.scribbles.forEach(function (a) {
      if (a.kind !== "stroke") return;
      var pts = repositionPoints(a);
      drawStroke(pts);
    });
  }

  // Re-anchor a retained scribble to its element's current position (best-effort).
  function repositionPoints(a) {
    if (!a.anchor || !a.anchor.selector) return a.points;
    var elm = null;
    try { elm = document.querySelector(a.anchor.selector); } catch (e) { elm = null; }
    if (!elm) return a.points;
    var rect = elm.getBoundingClientRect();
    var dx = rect.left - a.anchor.originX;
    var dy = rect.top - a.anchor.originY;
    if (!dx && !dy) return a.points;
    return a.points.map(function (p) { return { x: p.x + dx, y: p.y + dy }; });
  }

  // persistent notes (text + voice)
  // Written and dictated notes stay on screen as fixed-size, scrollable boxes anchored to their
  // element, visible whether or not Red Scribble is active, until the agent closes them.

  // A single-point anchor: which element is under (x,y) and where it sat, so the pin can follow it.
  function elementAnchor(x, y) {
    var target = elementUnder(x, y);
    var rect = target ? target.getBoundingClientRect() : { left: 0, top: 0 };
    return { selector: target ? cssPath(target) : null, originX: rect.left, originY: rect.top };
  }

  function buildNotesLayer() {
    notesLayer = el("div", "position:fixed;inset:0;pointer-events:none;z-index:" + (Z + 1) + ";");
    document.body.appendChild(notesLayer);
  }

  // The note's current on-screen point, re-anchored to its element (best-effort).
  function anchoredPoint(a) {
    var p = a.point || { x: 0, y: 0 };
    if (a.anchor && a.anchor.selector) {
      var elm = null;
      try { elm = document.querySelector(a.anchor.selector); } catch (e) { elm = null; }
      if (elm) {
        var r = elm.getBoundingClientRect();
        return { x: p.x + (r.left - a.anchor.originX), y: p.y + (r.top - a.anchor.originY) };
      }
    }
    return p;
  }

  var NOTE_W = 240, NOTE_MAXH = 110;   // fixed footprint; longer notes scroll within the box
  function renderNotes() {
    if (!notesLayer) return;
    notesLayer.innerHTML = "";
    _noteBoxes = [];
    state.scribbles.forEach(function (a) {
      if (a.kind !== "text" && a.kind !== "voice") return;
      var noteBox = el("div",
        "position:absolute;width:" + NOTE_W + "px;max-height:" + NOTE_MAXH + "px;overflow-y:auto;" +
        "background:#fff;border:2px solid #e11d2a;border-radius:8px;padding:8px 10px;" +
        "font:13px system-ui;color:#222;line-height:1.35;white-space:pre-wrap;word-break:break-word;" +
        "box-shadow:0 4px 14px rgba(0,0,0,.3);pointer-events:auto;");
      noteBox.textContent = a.text || "";
      notesLayer.appendChild(noteBox);
      _noteBoxes.push({ el: noteBox, ann: a });
    });
    positionNotes();
  }

  function positionNotes() {
    if (!notesLayer) return;   // only positioned while active (scroll/resize can fire when inactive)
    _noteBoxes.forEach(function (nb) {
      var pos = anchoredPoint(nb.ann);
      nb.el.style.left = Math.max(8, Math.min(pos.x, window.innerWidth - NOTE_W - 8)) + "px";
      nb.el.style.top = Math.max(8, Math.min(pos.y, window.innerHeight - 40)) + "px";
    });
  }

  // double-click text box
  function openTextBox(x, y) {
    var anchor = elementAnchor(x, y);

    var box = el(
      "div",
      "position:fixed;z-index:" + (Z + 2) + ";background:#fff;border:2px solid #e11d2a;" +
        "border-radius:8px;padding:8px;box-shadow:0 6px 20px rgba(0,0,0,.3);width:260px;"
    );
    // Keep the box on-screen even though the saved point is the true click location.
    var left = Math.min(x, window.innerWidth - 280);
    var top = Math.min(y, window.innerHeight - 130);
    box.style.left = Math.max(8, left) + "px";
    box.style.top = Math.max(8, top) + "px";

    var ta = el("textarea",
      "width:100%;height:64px;border:1px solid #ccc;border-radius:4px;padding:6px;" +
      "font:14px system-ui;resize:none;box-sizing:border-box;");
    ta.placeholder = "Describe this...";
    var row = el("div", "display:flex;gap:6px;justify-content:flex-end;margin-top:6px;");
    var submit = el("button",
      "background:#e11d2a;color:#fff;border:0;border-radius:4px;padding:5px 12px;cursor:pointer;");
    submit.textContent = "Add";
    var cancel = el("button",
      "background:#eee;border:0;border-radius:4px;padding:5px 12px;cursor:pointer;");
    cancel.textContent = "Cancel";
    row.appendChild(cancel); row.appendChild(submit);
    box.appendChild(ta); box.appendChild(row);
    overlay.appendChild(box);
    ta.focus();

    cancel.addEventListener("click", function () { box.remove(); });
    submit.addEventListener("click", function () {
      var text = ta.value.trim();
      box.remove();
      if (text) queueText(text, { x: x, y: y }, anchor);
    });
  }

  // voice capture (double-click-and-hold)
  // Adopted Local Vocal driver: on-device Silero VAD + Moonshine ASR (voice_capture.js ->
  // voice_session.js). We load it on first use, listen for the duration of the hold, show a live
  // caption, and package the transcript + captured WAV(s) on release. See
  // reference/voice-transcription.md.

  var voiceState = null;       // the in-progress recording, if any
  var _voiceLibPromise = null;

  function loadScriptOnce(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src; s.async = false;
      s.onload = function () { resolve(); };
      s.onerror = function () { reject(new Error("failed to load " + src)); };
      document.head.appendChild(s);
    });
  }

  // Load our own copies of the voice modules (session before capture) and kick off model loading.
  function ensureVoice() {
    if (window.LocalVocal) return Promise.resolve(window.LocalVocal);
    if (_voiceLibPromise) return _voiceLibPromise;
    _voiceLibPromise = loadScriptOnce(RS + "/voice_session.js")
      .then(function () { return loadScriptOnce(RS + "/voice_capture.js"); })
      .then(function () {
        if (!window.LocalVocal) throw new Error("LocalVocal missing after load");
        window.LocalVocal.init();
        return window.LocalVocal;
      });
    return _voiceLibPromise;
  }

  // A live-transcription box anchored at (x,y): a header status line plus a body that fills with
  // the caption as you talk (stable text solid, tentative tail dimmed), capped at ~5 lines then
  // scrolling to keep the latest words in view.
  function voiceBox(x, y) {
    var box = el("div",
      "position:fixed;z-index:" + (Z + 2) + ";background:#fff;border:2px solid #e11d2a;" +
      "border-radius:8px;box-shadow:0 6px 20px rgba(0,0,0,.3);width:300px;font:14px system-ui;" +
      "color:#222;overflow:hidden;");
    box.style.left = Math.max(8, Math.min(x, window.innerWidth - 320)) + "px";
    box.style.top = Math.max(8, Math.min(y, window.innerHeight - 180)) + "px";

    // Recording indicator: a red dot at the box's upper-left that pulses with the mic energy.
    var dot = el("span",
      "width:10px;height:10px;border-radius:50%;background:#e11d2a;display:inline-block;flex:0 0 auto;" +
      "transition:transform .08s ease-out,opacity .08s ease-out;");
    var headerText = el("span", "color:#e11d2a;font-size:12px;font-weight:600;");
    headerText.textContent = "Listening...";
    var header = el("div",
      "display:flex;align-items:center;gap:8px;padding:7px 10px;border-bottom:1px solid #f0d3d6;");
    header.appendChild(dot); header.appendChild(headerText);

    var body = el("div",
      "padding:8px 10px;line-height:1.35;max-height:6.75em;min-height:1.35em;overflow-y:auto;" +
      "white-space:pre-wrap;word-break:break-word;");
    box.appendChild(header); box.appendChild(body);
    (overlay || document.body).appendChild(box);

    return {
      el: box,
      set: function (stable, tentative) {
        body.textContent = "";
        var s = document.createElement("span");
        s.textContent = stable || "";
        var t = document.createElement("span");
        t.style.color = "#aaa";
        t.textContent = (stable && tentative ? " " : "") + (tentative || "");
        body.appendChild(s); body.appendChild(t);
        body.scrollTop = body.scrollHeight;   // keep the newest words visible past 5 lines
      },
      status: function (txt) { headerText.textContent = txt; },
      level: function (v) {
        var lvl = Math.min(1, v || 0);
        dot.style.transform = "scale(" + (0.7 + lvl * 1.1).toFixed(2) + ")";
        dot.style.opacity = (0.55 + lvl * 0.45).toFixed(2);
      },
      remove: function () { box.remove(); },
    };
  }

  function startVoice(x, y) {
    if (voiceState) return;
    var st = {
      anchor: elementAnchor(x, y),
      point: { x: x, y: y },
      turns: [], wavs: [], box: voiceBox(x, y),
      session: null, settleTimer: null, finalized: false, stopped: false,
    };
    voiceState = st;
    ensureVoice().then(function (lv) {
      if (voiceState !== st) return;   // released before the model was ready
      st.session = lv.listen({
        onCaption: function (stable, tentative) {
          if (!st.box || st.stopped) return;   // after release, freeze the box (no blanking flash)
          // Show finalized segments of this hold plus the current segment's live caption, so the
          // box fills cumulatively as you talk (stable solid, tentative dimmed).
          var prefix = st.turns.join(" ");
          st.box.set((prefix + " " + (stable || "")).trim(), tentative);
          st.box.status("Listening...");
        },
        onTurn: function (text, wavBlob) {
          if (text) st.turns.push(text);
          if (wavBlob) blobToBase64(wavBlob).then(function (b64) { if (b64) st.wavs.push(b64); });
          if (st !== voiceState && !st.finalized) scheduleVoiceFinalize(st);  // a late final turn after release
        },
        onLevel: function (level) { if (st.box) st.box.level(level); },
        onError: function () {},
      });
    }).catch(function () { if (voiceState === st) stopVoice(); });
  }

  function stopVoice() {
    var st = voiceState;
    if (!st) return;
    voiceState = null;   // no longer the active recorder; a late turn still finalizes st
    st.stopped = true;   // freeze the recording box's caption; the note box replaces it on finalize
    if (st.box) st.box.status("Transcribing...");
    try { if (st.session) st.session.stop(); } catch (_) {}
    scheduleVoiceFinalize(st);
  }

  // Give any in-flight final transcription a moment to fold in, then package the packet once.
  function scheduleVoiceFinalize(st) {
    if (st.settleTimer) clearTimeout(st.settleTimer);
    st.settleTimer = setTimeout(function () { finalizeVoice(st); }, 1500);
  }

  function finalizeVoice(st) {
    if (st.finalized) return;
    st.finalized = true;
    if (st.settleTimer) { clearTimeout(st.settleTimer); st.settleTimer = null; }
    var transcript = st.turns.join(" ").trim();
    // Render the persistent note box BEFORE removing the recording box, so there is no gap where
    // neither is on screen (that gap was the "box invisible" flash).
    if (transcript || st.wavs.length) queueVoice(transcript, st.wavs.slice(), st.point, st.anchor);
    if (st.box) { st.box.remove(); st.box = null; }
  }

  function blobToBase64(blob) {
    return new Promise(function (resolve) {
      var r = new FileReader();
      r.onloadend = function () {
        var s = String(r.result || "");
        var comma = s.indexOf(",");
        resolve(comma >= 0 ? s.slice(comma + 1) : "");
      };
      r.onerror = function () { resolve(""); };
      r.readAsDataURL(blob);
    });
  }

  function queueVoice(transcript, wavsB64, point, anchor) {
    var scribble = { kind: "voice", text: transcript, point: point, anchor: anchor, id: null };
    state.scribbles.push(scribble);
    renderNotes();   // the transcription box stays on screen
    var pkt = basePacket("voice");
    pkt.transcript = transcript;
    pkt.point = point;
    pkt.anchor = anchor ? anchor.selector : null;
    if (wavsB64.length) pkt.audio_wav_base64 = wavsB64;
    enqueue(pkt, scribble);
  }

  // feedback packets
  function basePacket(kind) {
    return { kind: kind, page_url: location.href, created_at: new Date().toISOString() };
  }

  function queueStroke(scribble) {
    var pkt = basePacket("stroke");
    pkt.strokes = [scribble.points];
    pkt.anchor = scribble.anchor ? scribble.anchor.selector : null;
    pkt.point = scribble.points[0];
    enqueue(pkt, scribble);
  }

  function queueText(text, point, anchor) {
    var scribble = { kind: "text", text: text, point: point, anchor: anchor, id: null };
    state.scribbles.push(scribble);
    renderNotes();   // the box stays on screen
    var pkt = basePacket("text");
    pkt.text = text;
    pkt.point = point;
    pkt.anchor = anchor ? anchor.selector : null;
    enqueue(pkt, scribble);
  }

  // ONE send path for both modes: every scribble gathers in state.pending, and a "send
  // operation" flushes ALL of it as one envelope (one POST, one message to the agent). The modes
  // differ only in the trigger: live mode debounces (SEND_DEBOUNCE_MS after the first gathered
  // scribble), batch mode waits for the menu's Send Pending Scribbles click.
  // Everything the plug-in draws with is in viewport coordinates, but everything that LEAVES it
  // is read against the screenshot -- and html2canvas captures the whole document, not the
  // viewport. Shipping viewport coordinates made the two disagree by however far the page
  // happened to be scrolled, silently: the marks land on the wrong lines and nothing says so.
  // Convert once, here, because every packet passes through enqueue. Recording the scroll offset
  // instead would leave every future reader to remember to apply it.
  function toDocumentSpace(pkt) {
    var dx = window.scrollX || 0;
    var dy = window.scrollY || 0;
    if (pkt.point) pkt.point = { x: pkt.point.x + dx, y: pkt.point.y + dy };
    if (pkt.strokes) {
      pkt.strokes = pkt.strokes.map(function (stroke) {
        return stroke.map(function (p) { return { x: p.x + dx, y: p.y + dy }; });
      });
    }
    // The screenshot is captured at this ratio, so it is what converts these CSS pixels into
    // screenshot pixels. Without it a reader has to guess the scale from the image dimensions.
    pkt.device_pixel_ratio = window.devicePixelRatio || 1;
    return pkt;
  }

  function enqueue(pkt, scribble) {
    state.pending.push({ pkt: toDocumentSpace(pkt), scribble: scribble || null });
    if (state.config.mode === "live") {
      scheduleSend();
    } else if (menu) {
      renderMenu(); // keep the Send-count fresh if the menu is open
    }
  }

  var _sendTimer = null;
  function scheduleSend() {
    if (_sendTimer) return;   // a window is already open; this scribble rides along
    _sendTimer = setTimeout(function () {
      _sendTimer = null;
      sendPending();
    }, SEND_DEBOUNCE_MS);
  }

  var _h2c = null;
  // ONE screenshot per send operation (capturing is slow): taken at send time, attached to the
  // envelope, and shared by every scribble in it.
  function captureScreenshot() {
    var loader = _h2c
      ? Promise.resolve(_h2c)
      : loadScriptOnce(H2C_URL).then(function () { _h2c = window.html2canvas; return _h2c; });
    // Hide our own overlay/logo so the screenshot shows the app, not our chrome.
    var hidden = [];
    [overlay, logo, menu].forEach(function (n) { if (n) { hidden.push([n, n.style.visibility]); n.style.visibility = "hidden"; } });
    return loader
      .then(function (h2c) { return h2c(document.body, { logging: false, useCORS: true }); })
      .then(function (cv) { return cv.toDataURL("image/png").split(",")[1]; })
      .catch(function () { return null; })
      .then(function (b64) { hidden.forEach(function (pair) { pair[0].style.visibility = pair[1]; }); return b64; });
  }

  // The send operation: flush ALL gathered scribbles as ONE envelope in ONE POST. The backend
  // answers with packet_ids in the same order; each is tagged onto its scribble so a later agent
  // "close" can drop it by id.
  function sendPending() {
    var items = state.pending.splice(0);
    if (!items.length) return Promise.resolve(null);
    var hasStroke = items.some(function (item) { return item.pkt.kind === "stroke"; });
    var shot = hasStroke ? captureScreenshot() : Promise.resolve(null);
    return shot.then(function (b64) {
      var envelope = { scribbles: items.map(function (item) { return item.pkt; }) };
      if (b64) envelope.screenshot_png_base64 = b64;
      return fetch(RS + "/feedback", {
        method: "POST",
        // text/plain keeps this a CORS "simple request" so the browser sends it directly.
        // A preflight would be sent WITHOUT cookies, and the workspace forwarder rejects an
        // unauthenticated request before it ever reaches Red Scribble -- so the POST could never
        // succeed. The body is still JSON; the backend parses bytes and ignores the type.
        headers: { "Content-Type": "text/plain;charset=UTF-8" },
        credentials: "include",
        body: JSON.stringify(envelope),
      });
    })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (res && res.packet_ids) {
          items.forEach(function (item, i) {
            if (item.scribble && res.packet_ids[i]) item.scribble.id = res.packet_ids[i];
          });
        }
        return res;
      })
      .catch(function () { return null; });
  }

  // Poll the scribble registry; drop any scribble the agent has closed so it stops rendering.
  function pollScribbles() {
    fetch(RS + "/scribbles", { credentials: "include" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data || !data.scribbles) return;
        var closed = {};
        data.scribbles.forEach(function (a) { if (a.status === "closed") closed[a.id] = true; });
        var before = state.scribbles.length;
        state.scribbles = state.scribbles.filter(function (a) { return !(a.id && closed[a.id]); });
        if (state.scribbles.length !== before) { renderStrokes(); renderNotes(); }
      })
      .catch(function () {});
  }

  // long-press menu
  function openMenu() {
    loadConfig().then(renderMenu);
  }

  function renderMenu() {
    closeMenu();
    menu = el(
      "div",
      "position:fixed;right:20px;bottom:88px;z-index:" + (Z + 3) + ";background:#fff;" +
        "border-radius:10px;box-shadow:0 8px 28px rgba(0,0,0,.32);min-width:220px;overflow:hidden;" +
        "font:14px system-ui;color:#222;"
    );
    var cfg = state.config;
    var live = cfg.mode === "live";

    // "Live" is the one mode fact rendered as a switch.
    var liveItem = menuItem("Live", null, function () { setLive(!live); });
    liveItem.appendChild(switchControl(live));
    menu.appendChild(liveItem);

    // Explicit send exists only for the off (batch) state; live mode drains pending by itself.
    var sendEnabled = !live && state.pending.length > 0;
    var sendItem = menuItem("Send Pending Scribbles (" + state.pending.length + ")", null, function () {
      if (!sendEnabled) return;
      sendPending().then(function () { closeMenu(); });
    });
    if (!sendEnabled) { sendItem.style.opacity = "0.45"; sendItem.style.cursor = "default"; }
    menu.appendChild(sendItem);
    menu.appendChild(divider());

    menu.appendChild(sectionLabel("chats"));
    (cfg.agents || []).forEach(function (a) {
      menu.appendChild(menuItem(a.name, a.id === cfg.target_agent_id, function () {
        setTargetAgent(a.id);
      }));
    });

    document.body.appendChild(menu);
  }

  function menuItem(label, checked, onClick) {
    var item = el("div",
      "padding:9px 14px;cursor:pointer;display:flex;justify-content:space-between;" +
      "align-items:center;gap:12px;white-space:nowrap;");
    item.onmouseenter = function () { item.style.background = "#f3f3f3"; };
    item.onmouseleave = function () { item.style.background = "#fff"; };
    var text = el("span"); text.textContent = label;
    item.appendChild(text);
    if (checked !== null) {
      // The check mark is drawn, not typed. A U+2713 character renders as a missing-glyph box
      // wherever the host page's font stack has no glyph for it -- and Red Scribble is meant to
      // drop into apps whose fonts it has never seen. Two strokes of SVG look the same
      // everywhere and keep this asset pure-ASCII besides.
      var mark = el("span", "width:14px;flex:0 0 auto;display:flex;align-items:center;");
      if (checked) {
        mark.innerHTML =
          '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="#e11d2a" ' +
          'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
          '<path d="M2.5 7.5 L5.5 10.5 L11.5 3.5"/></svg>';
      }
      item.appendChild(mark);
    }
    item.addEventListener("click", onClick);
    return item;
  }

  function switchControl(on) {
    var track = el("span",
      "width:34px;height:20px;border-radius:999px;flex:0 0 auto;position:relative;" +
      "transition:background .15s ease;background:" + (on ? "#e11d2a" : "#c9c2c2") + ";");
    var knob = el("span",
      "position:absolute;top:2px;width:16px;height:16px;border-radius:50%;background:#fff;" +
      "box-shadow:0 1px 3px rgba(0,0,0,.35);transition:left .15s ease;left:" + (on ? "16px" : "2px") + ";");
    track.appendChild(knob);
    return track;
  }

  function sectionLabel(text) {
    var label = el("span",
      "display:block;padding:7px 14px 3px;font-size:11px;letter-spacing:.06em;" +
      "text-transform:uppercase;color:#9a8f8d;pointer-events:none;user-select:none;");
    label.textContent = text;
    return label;
  }

  function divider() {
    return el("div", "height:1px;background:#e5e5e5;margin:2px 0;");
  }

  function closeMenu() { if (menu) { menu.remove(); menu = null; } }

  // Flip the one mode fact. The config write must land before the flush so the delivered
  // document carries the mode the user just chose.
  function setLive(on) {
    var mode = on ? "live" : "batch";
    state.config.mode = mode;
    fetch(RS + "/config", {
      method: "POST",
      // text/plain keeps this a CORS "simple request" -- see the note on the feedback POST.
      headers: { "Content-Type": "text/plain;charset=UTF-8" },
      credentials: "include",
      body: JSON.stringify({ mode: mode }),
    })
      .catch(function () {})
      .then(function () {
        // Turning live ON means "pending never lingers": flush the backlog immediately.
        if (on && state.pending.length) return sendPending();
      })
      .then(renderMenu);
    renderMenu();
  }

  function setTargetAgent(id) {
    state.config.target_agent_id = id;
    fetch(RS + "/config", {
      method: "POST",
      // text/plain keeps this a CORS "simple request" -- see the note on the feedback POST.
      headers: { "Content-Type": "text/plain;charset=UTF-8" },
      credentials: "include",
      body: JSON.stringify({ target_agent_id: id }),
    }).catch(function () {});
    renderMenu();
  }

  // boot
  function boot() {
    buildLogo();
    loadConfig();
    pollScribbles();
    setInterval(pollScribbles, 3000);   // drop agent-closed scribbles as they are closed
    window.addEventListener("resize", function () {
      if (canvas) { canvas.width = window.innerWidth; canvas.height = window.innerHeight; renderStrokes(); }
      positionNotes();
    });
    window.addEventListener("scroll", positionNotes, true);   // keep note boxes anchored while scrolling
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
