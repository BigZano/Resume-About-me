/* ============================================================
   Hero fire — the Doom flame algorithm (1993) burning into the
   letterforms of the name.

   Why this is here: the Diablo II title screen is the reason
   Bret got into computers. It runs on a low-resolution grid so
   the pixels stay honest rather than being a blur filter.

   Each column cools at its own rate and is capped at its own
   height, so the flames vary across the name instead of forming
   a flat band. The envelope drifts, so it never repeats.
   ============================================================ */
(function () {
  "use strict";

  var canvas = document.getElementById("hero-fire");
  if (!canvas || !canvas.getContext) return;

  var ctx = canvas.getContext("2d");
  if (!ctx) return;

  /* Uppercase deliberately: lowercase x-height is barely half the cap height,
     so a flame line set as a fraction of cap height engulfs lowercase letters
     entirely while only reaching two-thirds up the capitals. Caps burn evenly. */
  var NAME = (canvas.getAttribute("data-name") || "BRET ZANOTELLI").toUpperCase();

  /* Tuned with Bret 2026-08-05. Do not adjust without asking. */
  var PIXEL     = 1;     /* fire grid cell size, in CSS px      */
  var HEIGHT    = 0.69;  /* max flame height, as × cap height   */
  var VARIATION = 0.7;   /* 0 = flat flame line, 1 = wild       */
  var INTENSITY = 1.2;   /* >1 starts burning additively        */
  var BLOOM     = 4;     /* heat glow radius                    */
  var SPEED     = 17;    /* simulation steps per second         */

  /* classic Doom fire ramp, warmed toward ember and flame */
  var PALETTE = [
    [7,7,7],[31,7,7],[47,15,7],[71,15,7],[87,23,7],[103,31,7],[119,31,7],
    [143,39,7],[159,47,7],[175,63,7],[191,71,7],[199,71,7],[213,79,9],
    [219,85,13],[226,85,31],[228,93,25],[226,97,27],[224,103,29],
    [222,111,31],[224,119,33],[226,127,35],[230,135,37],[233,143,39],
    [236,151,41],[238,159,45],[240,166,59],[242,166,59],[243,174,67],
    [244,180,75],[245,187,85],[246,193,97],[247,200,111],[248,207,127],
    [250,214,146],[251,223,171],[252,232,199],[253,240,224]
  ];
  var HOT = PALETTE.length - 1;

  var fireCv = document.createElement("canvas");
  var fireCx = fireCv.getContext("2d", { willReadFrequently: true });
  var maskCv = document.createElement("canvas");
  var maskCx = maskCv.getContext("2d");
  var compCv = document.createElement("canvas");
  var compCx = compCv.getContext("2d");

  var W = 0, H = 0, DPR = 1;
  var fw = 0, fh = 0, fire = null, imgData = null;
  var decayCol = null, capRows = null;
  var fontPx = 0, baselineY = 0, capH = 0, burnH = 0;
  var envPhase = 0, lastFrame = 0, rafId = null, onScreen = true;

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  function isStatic() { return reduced.matches; }

  function layout() {
    var cssW = canvas.parentElement.clientWidth;
    if (!cssW) return;

    DPR = Math.min(window.devicePixelRatio || 1, 2);
    fontPx = Math.max(26, Math.min(cssW / 8.05, 190));
    var cssH = Math.round(fontPx * 1.34);

    W = Math.round(cssW * DPR);
    H = Math.round(cssH * DPR);
    canvas.style.width = cssW + "px";
    canvas.style.height = cssH + "px";
    canvas.width = W;
    canvas.height = H;

    maskCv.width = compCv.width = W;
    maskCv.height = compCv.height = H;

    baselineY = Math.round(H * 0.86);
    capH = 0.72 * fontPx * DPR;
    burnH = Math.max(10, Math.round(HEIGHT * capH));

    var px = Math.max(1, PIXEL * DPR);
    fw = Math.max(8, Math.ceil(W / px));
    fh = Math.max(6, Math.ceil(burnH / px));
    fireCv.width = fw;
    fireCv.height = fh;
    fire = new Float32Array(fw * fh);
    imgData = fireCx.createImageData(fw, fh);
    decayCol = new Float32Array(fw);
    capRows = new Float32Array(fw);

    updateEnvelope();
    seed();
    drawMask();
  }

  /* ── per-column height envelope ─────────────────────────── */
  function updateEnvelope() {
    for (var x = 0; x < fw; x++) {
      var u = (x / fw) * 6.2832;
      var n = Math.sin(u * 2.3 + envPhase) * 0.42
            + Math.sin(u * 5.1 - envPhase * 1.4) * 0.33
            + Math.sin(u * 11.7 + envPhase * 2.2) * 0.25;
      n = n * 0.5 + 0.5;
      var f = (1 - VARIATION) + VARIATION * (0.18 + 0.82 * n);
      capRows[x] = Math.max(2, f * fh);
      decayCol[x] = (2.15 * HOT) / capRows[x];
    }
    envPhase += 0.09;
  }

  /* ── the fire ───────────────────────────────────────────── */
  function seedRow() {
    var base = (fh - 1) * fw;
    for (var x = 0; x < fw; x++) {
      var n = Math.sin(x * 0.31 + envPhase) * 0.5
            + Math.sin(x * 0.13 - envPhase * 0.6) * 0.35
            + Math.random() * 0.15;
      fire[base + x] = HOT * (0.68 + 0.32 * (n * 0.5 + 0.5));
    }
  }

  function seed() { fire.fill(0); seedRow(); }

  function spread(src, decay) {
    var rand = (Math.random() * 3) | 0;
    var to = src - rand + 1 - fw;
    if (to < 0 || to >= fire.length) return;
    var v = fire[src] - (rand & 1) * decay;
    fire[to] = v > 0 ? v : 0;
  }

  function step() {
    updateEnvelope();
    seedRow();
    for (var x = 0; x < fw; x++) {
      var d = decayCol[x];
      for (var y = 1; y < fh; y++) spread(y * fw + x, d);
    }
  }

  function settle() { seed(); for (var i = 0; i < 120; i++) step(); }

  function paintFire() {
    var d = imgData.data;
    for (var y = 0; y < fh; y++) {
      var fromBottom = fh - 1 - y;
      for (var x = 0; x < fw; x++) {
        var i = y * fw + x;
        var p = i * 4;

        /* soft ceiling — the sideways drift in spread() smears the
           cooling-rate envelope out, so height has to be re-imposed */
        var t = fromBottom / capRows[x];
        if (t >= 1.06) { d[p + 3] = 0; continue; }

        var v = fire[i];
        if (t > 0.72) {
          var k = 1 - (t - 0.72) / 0.34;
          v *= k * k;
        }
        if (v <= 0.02) { d[p + 3] = 0; continue; }

        /* interpolate between steps — 37 hard stops reads as banding */
        var fi = v < HOT ? v : HOT;
        var i0 = fi | 0;
        var i1 = i0 < HOT ? i0 + 1 : i0;
        var m = fi - i0;
        var a = PALETTE[i0], b = PALETTE[i1];
        d[p]     = a[0] + (b[0] - a[0]) * m;
        d[p + 1] = a[1] + (b[1] - a[1]) * m;
        d[p + 2] = a[2] + (b[2] - a[2]) * m;
        d[p + 3] = fi < 6 ? (fi / 6) * 255 : 255;
      }
    }
    fireCx.putImageData(imgData, 0, 0);
  }

  /* ── text ───────────────────────────────────────────────── */
  function setFont(c) {
    c.font = '800 ' + (fontPx * DPR) + 'px "Bricolage Grotesque", system-ui, sans-serif';
    if ("letterSpacing" in c) c.letterSpacing = (-0.015 * fontPx * DPR) + "px";
    c.textAlign = "left";
    c.textBaseline = "alphabetic";
  }

  function drawMask() {
    maskCx.clearRect(0, 0, W, H);
    setFont(maskCx);
    maskCx.fillStyle = "#fff";
    maskCx.fillText(NAME, 0, baselineY);
  }

  /* ── compose ────────────────────────────────────────────── */
  function render() {
    paintFire();
    var flameTop = baselineY - burnH;

    compCx.clearRect(0, 0, W, H);
    compCx.globalCompositeOperation = "source-over";
    compCx.imageSmoothingEnabled = false;
    compCx.drawImage(fireCv, 0, 0, fw, fh, 0, flameTop, W, burnH);
    compCx.globalCompositeOperation = "destination-in";
    compCx.drawImage(maskCv, 0, 0);
    compCx.globalCompositeOperation = "source-over";

    ctx.clearRect(0, 0, W, H);

    /* charred at the baseline, clean above the flame line — without
       this the fire's hot end vanishes into light-coloured type */
    setFont(ctx);
    var lg = ctx.createLinearGradient(0, baselineY, 0, flameTop);
    lg.addColorStop(0, "#150F0C");
    lg.addColorStop(0.55, "#3B2318");
    lg.addColorStop(1, "#EDE4D8");
    ctx.fillStyle = lg;
    ctx.fillText(NAME, 0, baselineY);

    ctx.save();
    ctx.globalCompositeOperation = "source-atop";
    ctx.globalAlpha = Math.min(1, INTENSITY);
    ctx.drawImage(compCv, 0, 0);
    ctx.restore();

    if (INTENSITY > 1) {
      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      ctx.globalAlpha = Math.min(1, INTENSITY - 1);
      ctx.drawImage(compCv, 0, 0);
      ctx.restore();
    }

    if (BLOOM > 0) {
      ctx.save();
      ctx.globalCompositeOperation = "destination-over";
      ctx.filter = "blur(" + (BLOOM * DPR) + "px)";
      ctx.globalAlpha = 0.85;
      ctx.drawImage(compCv, 0, 0);
      ctx.restore();
    }
  }

  /* ── run loop ───────────────────────────────────────────── */
  function loop(ts) {
    rafId = requestAnimationFrame(loop);
    if (ts - lastFrame < 1000 / SPEED) return;
    lastFrame = ts;
    step();
    render();
  }

  function stop() {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = null;
  }

  function start() {
    stop();
    if (!fire) return;
    if (isStatic()) { settle(); render(); return; }
    if (!onScreen || document.hidden) { settle(); render(); return; }
    seed();
    for (var i = 0; i < 60; i++) step();   /* open already lit */
    rafId = requestAnimationFrame(loop);
  }

  /* ── wiring ─────────────────────────────────────────────── */
  var resizeTimer;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () { layout(); start(); }, 150);
  });

  reduced.addEventListener("change", start);
  document.addEventListener("visibilitychange", start);

  /* don't burn CPU on a hero nobody is looking at */
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(function (entries) {
      onScreen = entries[0].isIntersecting;
      start();
    }, { threshold: 0 }).observe(canvas);
  }

  function boot() { layout(); start(); }

  if (document.fonts && document.fonts.load) {
    document.fonts.load('800 100px "Bricolage Grotesque"').then(boot).catch(boot);
  } else {
    boot();
  }
})();
