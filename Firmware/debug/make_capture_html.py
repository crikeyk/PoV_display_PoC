#!/usr/bin/env python3
"""Turn a wand capture dump into a CSV and a self-contained HTML viewer.

The wand prints the block between 'POV> CAPTURE kept=' and 'POV> CAPTURE end'
on the serial console after you stop swinging. This reads the newest block
from the serial log (or a capture file) and writes:

    Firmware/debug/capture/capture.csv
    Firmware/debug/capture/view.html
"""
import argparse, json, math, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "capture")

HEADER_RE = re.compile(
    r"CAPTURE kept=(\d+) total=(\d+) mg=([-\d.]+) bias=([-\d.]+) sign=(-?\d+) shift=([-\d.]+)"
)


def parse_capture(text):
    start = text.rfind("POV> CAPTURE kept=")
    if start < 0:
        return None
    block = text[start:]
    end = block.find("POV> CAPTURE end")
    if end >= 0:
        block = block[:end]
    hdr = HEADER_RE.search(block)
    if not hdr:
        raise SystemExit("capture header found but could not be read")
    meta = {
        "kept": int(hdr.group(1)),
        "total": int(hdr.group(2)),
        "mg": float(hdr.group(3)),
        "bias": float(hdr.group(4)),
        "sign": int(hdr.group(5)),
        "shift": float(hdr.group(6)),
    }
    samples = []
    events = []
    for line in block.splitlines():
        if "POV> D" in line:
            payload = line.split("POV> D", 1)[1]
            for tok in payload.split():
                parts = tok.split(",")
                if len(parts) != 4:
                    continue
                samples.append(tuple(int(p) for p in parts))
        elif "POV> E" in line:
            payload = line.split("POV> E", 1)[1]
            for tok in payload.split():
                parts = tok.split(",")
                if len(parts) != 3:
                    continue
                events.append(tuple(int(p) for p in parts))
    if len(samples) != meta["kept"]:
        meta["kept"] = len(samples)
    return meta, samples, events


def build_series(meta, samples, events):
    g_per_count = meta["mg"] / 1000.0
    sign = meta["sign"]
    bias = meta["bias"]
    t = 0.0
    rows = []
    for i, (dt10, raw, ph_mrad, w_x100) in enumerate(samples):
        if i:
            t += dt10 * 1e-5
        locked = w_x100 > 0
        phase = (ph_mrad / 1000.0) if locked else None
        omega = (w_x100 / 100.0) if locked else 0.0
        pos = (-math.cos(phase)) if locked else None
        pace = (omega / (2.0 * math.pi)) if locked else None
        accel = sign * raw * g_per_count - bias
        rows.append({
            "t": t,
            "raw": raw,
            "g": accel,
            "phase": phase,
            "pos": pos,
            "omega": omega,
            "pace": pace,
            "locked": locked,
        })
    ev_by_i = {}
    for rel, code, ok in events:
        if 0 <= rel < len(rows):
            ev_by_i.setdefault(rel, []).append((code, ok))
    return rows, ev_by_i


def write_csv(path, rows, ev_by_i):
    names = {2: "left_end", -2: "right_end", 1: "centre_right", -1: "centre_left"}
    with open(path, "w") as f:
        f.write("t_s,raw_counts,accel_g,phase_rad,position,omega_rad_s,pace_hz,locked,event\n")
        for i, r in enumerate(rows):
            evs = ev_by_i.get(i, [])
            label = " ".join(
                ("%s%s" % (names.get(code, str(code)), "" if ok else "?"))
                for code, ok in evs
            )
            phase = "" if r["phase"] is None else "%.5f" % r["phase"]
            pos = "" if r["pos"] is None else "%.5f" % r["pos"]
            pace = "" if r["pace"] is None else "%.4f" % r["pace"]
            f.write("%.5f,%d,%.5f,%s,%s,%.4f,%s,%d,%s\n" % (
                r["t"], r["raw"], r["g"], phase, pos, r["omega"], pace,
                1 if r["locked"] else 0, label))


def fit_amp(rows):
    num = den = 0.0
    for r in rows:
        if r["phase"] is None:
            continue
        c = math.cos(r["phase"])
        num += r["g"] * c
        den += c * c
    if den < 1e-6:
        return 0.0
    return num / den


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PoV swing capture</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; background: #0e1116; color: #d7dbe3;
    font: 14px/1.4 ui-sans-serif, system-ui, sans-serif; }
  body { display: flex; flex-direction: column; }
  header { padding: 14px 18px 8px; display: flex; flex-wrap: wrap; gap: 8px 18px;
    align-items: baseline; border-bottom: 1px solid #232833; }
  h1 { font-size: 16px; font-weight: 650; margin: 0; letter-spacing: 0.01em; }
  .meta { color: #8b93a3; font-size: 13px; }
  .bar { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center;
    padding: 8px 18px; color: #c5cad3; }
  button, label.chk { background: #1a1f29; color: #d7dbe3; border: 1px solid #313846;
    border-radius: 6px; padding: 5px 10px; font: inherit; cursor: pointer; }
  button:hover { background: #232a36; }
  label.chk { display: inline-flex; gap: 6px; align-items: center; }
  .swatch { width: 11px; height: 11px; border-radius: 2px; display: inline-block; }
  #readout { margin-left: auto; color: #9aa3b2; font-variant-numeric: tabular-nums; min-height: 1.4em; }
  #stage { flex: 1; min-height: 0; }
  canvas { width: 100%; height: 100%; display: block; cursor: crosshair; }
  .foot { margin: 0; padding: 4px 18px 8px; color: #6d7582; font-size: 12px; }
</style>
</head>
<body>
<header>
  <h1>Raw swing and oscillator</h1>
  <div class="meta" id="meta"></div>
</header>
<div class="bar">
  <button id="reset" type="button">Whole recording</button>
  <label class="chk"><input type="checkbox" id="model" checked> oscillator shape on the accel</label>
  <label class="chk"><input type="checkbox" id="resid"> leftover (accel minus that shape)</label>
  <label class="chk"><input type="checkbox" id="events" checked> turn markers</label>
  <span id="readout">Scroll to zoom, drag to move. Drag the strip at the top to jump.</span>
</div>
<div id="stage"><canvas id="c"></canvas></div>
<p class="foot">Blue is the accelerometer along the swing. Amber is the shape the oscillator expects, scaled to the same size. Violet is where it thinks the wand is. Green is how fast that clock is running.</p>
<script>
const CAP = __DATA__;
const C = {
  bg: "#0e1116", grid: "#262c38", text: "#8b93a3", zero: "#3a4250",
  accel: "#7eb6ff", model: "#ffb020", resid: "#e07a72",
  pos: "#b79bff", pace: "#3dcc8a", left: "#ff6b81", right: "#5ddeaf",
  shade: "rgba(255,255,255,0.035)", band: "rgba(183,155,255,0.10)"
};
const rows = [];
const evAt = new Map();
(function () {
  let t = 0;
  const gpc = CAP.meta.mg / 1000;
  for (let i = 0; i < CAP.raw.length; i++) {
    if (i) t += CAP.dt[i] * 1e-5;
    const w = CAP.w[i];
    const locked = w > 0;
    const phase = locked ? CAP.ph[i] / 1000 : null;
    const pos = locked ? -Math.cos(phase) : null;
    const pace = locked ? (w / 100) / (2 * Math.PI) : null;
    rows.push({ t, raw: CAP.raw[i], g: CAP.meta.sign * CAP.raw[i] * gpc - CAP.meta.bias,
      phase, pos, pace, locked });
  }
  for (const [rel, code, ok] of CAP.ev) evAt.set(rel, (evAt.get(rel) || []).concat([{code, ok}]));
})();
const T0 = rows.length ? rows[0].t : 0;
const T1 = rows.length ? rows[rows.length - 1].t : 1;
let amp = 0;
(function () {
  let num = 0, den = 0;
  for (const r of rows) {
    if (r.phase == null) continue;
    const c = Math.cos(r.phase);
    num += r.g * c; den += c * c;
  }
  amp = den > 1e-6 ? num / den : 0;
})();
const lockedN = rows.reduce((n, r) => n + (r.locked ? 1 : 0), 0);
const metaEl = document.getElementById("meta");
metaEl.textContent = rows.length
  ? ( (T1 - T0).toFixed(1) + " s kept, " + rows.length + " samples, "
      + (lockedN / rows.length * 100).toFixed(0) + "% locked, scale "
      + CAP.meta.mg.toFixed(2) + " mg/count, shift " + CAP.meta.shift.toFixed(1) + " ms"
      + (CAP.meta.total > CAP.meta.kept ? ", showing the latest part of " + (CAP.meta.total / 400).toFixed(0) + " s recorded" : "") )
  : "no samples";

const canvas = document.getElementById("c");
const ctx = canvas.getContext("2d");
let view0 = T0, view1 = T1;
let drag = null;

function clampView() {
  const span = Math.max(0.05, view1 - view0);
  const full = Math.max(0.05, T1 - T0);
  if (span >= full) { view0 = T0; view1 = T1; return; }
  if (view0 < T0) { view1 += T0 - view0; view0 = T0; }
  if (view1 > T1) { view0 -= view1 - T1; view1 = T1; }
  if (view0 < T0) view0 = T0;
}
function idxAt(t) {
  let lo = 0, hi = rows.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (rows[mid].t < t) lo = mid + 1; else hi = mid;
  }
  if (lo > 0 && Math.abs(rows[lo - 1].t - t) < Math.abs(rows[lo].t - t)) return lo - 1;
  return lo;
}
function layout() {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = Math.max(1, Math.floor(w * dpr));
  canvas.height = Math.max(1, Math.floor(h * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const L = 58, R = w - 58;
  const overview = { x: L, y: 16, w: Math.max(10, R - L), h: 36 };
  const gap = 16;
  const paceH = 64;
  const bottom = 20;
  const rest = h - (overview.y + overview.h + gap) - paceH - gap - bottom;
  const mainH = Math.max(70, Math.round(rest * 0.56));
  const main = { x: L, y: overview.y + overview.h + gap, w: overview.w, h: mainH };
  const pos = { x: L, y: main.y + main.h + gap, w: overview.w, h: Math.max(56, rest - mainH) };
  const pace = { x: L, y: pos.y + pos.h + gap, w: overview.w, h: paceH };
  return { w, h, overview, main, pos, pace };
}
function xOf(box, t) { return box.x + (t - view0) / (view1 - view0) * box.w; }
function tOf(box, x) { return view0 + (x - box.x) / box.w * (view1 - view0); }
function niceStep(span, px, minPx) {
  const rough = span / Math.max(1, px / minPx);
  const p10 = Math.pow(10, Math.floor(Math.log10(Math.max(1e-9, rough))));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p10 >= rough) return m * p10;
  return 10 * p10;
}
function yRange(box, pick, pad) {
  let lo = Infinity, hi = -Infinity, n = 0;
  const i0 = idxAt(view0), i1 = idxAt(view1);
  for (let i = i0; i <= i1 && i < rows.length; i++) {
    const v = pick(rows[i]);
    if (v == null || !isFinite(v)) continue;
    if (v < lo) lo = v; if (v > hi) hi = v; n++;
  }
  if (!n) return [-1, 1];
  if (hi - lo < 1e-6) { lo -= 1; hi += 1; }
  const p = (hi - lo) * pad;
  return [lo - p, hi + p];
}
function decimate(i0, i1, box, pick) {
  const out = [];
  const n = Math.max(1, i1 - i0);
  const bucket = Math.max(1, Math.floor(n / Math.max(1, box.w)));
  if (bucket <= 1) {
    for (let i = i0; i <= i1 && i < rows.length; i++) {
      const v = pick(rows[i]);
      if (v == null || !isFinite(v)) { out.push(null); continue; }
      out.push([rows[i].t, v]);
    }
    return out;
  }
  for (let i = i0; i <= i1; i += bucket) {
    let j1 = Math.min(i1, i + bucket - 1);
    let mn = Infinity, mx = -Infinity, tn = null, tx = null, any = false;
    for (let j = i; j <= j1 && j < rows.length; j++) {
      const v = pick(rows[j]);
      if (v == null || !isFinite(v)) continue;
      any = true;
      if (v < mn) { mn = v; tn = rows[j].t; }
      if (v > mx) { mx = v; tx = rows[j].t; }
    }
    if (!any) { out.push(null); continue; }
    if (tn <= tx) { out.push([tn, mn]); out.push([tx, mx]); }
    else { out.push([tx, mx]); out.push([tn, mn]); }
  }
  return out;
}
function strokeSeries(box, y0, y1, series, color, width) {
  ctx.beginPath();
  let pen = false;
  for (const p of series) {
    if (!p) { pen = false; continue; }
    const x = xOf(box, p[0]);
    const y = box.y + (y1 - p[1]) / (y1 - y0) * box.h;
    if (!pen) { ctx.moveTo(x, y); pen = true; }
    else ctx.lineTo(x, y);
  }
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.stroke();
}
function gridY(box, y0, y1, fmt, minPx) {
  const step = niceStep(y1 - y0, box.h, minPx || 42);
  const start = Math.ceil(y0 / step) * step;
  ctx.font = "11px ui-sans-serif, system-ui, sans-serif";
  ctx.fillStyle = C.text;
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let v = start; v <= y1 + step * 0.01; v += step) {
    const y = box.y + (y1 - v) / (y1 - y0) * box.h;
    if (y < box.y - 2 || y > box.y + box.h + 2) continue;
    ctx.strokeStyle = Math.abs(v) < step * 0.01 ? C.zero : C.grid;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(box.x, y); ctx.lineTo(box.x + box.w, y); ctx.stroke();
    ctx.fillText(fmt(v), box.x - 6, y);
  }
}
function gridX(box, labels) {
  const span = view1 - view0;
  const step = niceStep(span, box.w, 90);
  const start = Math.ceil(view0 / step) * step;
  ctx.font = "11px ui-sans-serif, system-ui, sans-serif";
  ctx.fillStyle = C.text;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  for (let v = start; v <= view1 + step * 0.01; v += step) {
    const x = xOf(box, v);
    if (x < box.x || x > box.x + box.w) continue;
    ctx.strokeStyle = C.grid;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, box.y); ctx.lineTo(x, box.y + box.h); ctx.stroke();
    if (labels) ctx.fillText(v.toFixed(step < 0.1 ? 2 : step < 1 ? 1 : 0) + "s", x, box.y + box.h + 4);
  }
}
function shadeLock(box) {
  ctx.fillStyle = C.shade;
  let run = null;
  function flush(t1) {
    if (run == null) return;
    const x0 = xOf(box, Math.max(run, view0));
    const x1 = xOf(box, Math.min(t1, view1));
    if (x1 > x0) ctx.fillRect(x0, box.y, x1 - x0, box.h);
    run = null;
  }
  for (let i = 0; i < rows.length; i++) {
    if (!rows[i].locked) {
      if (run == null) run = rows[i].t;
    } else flush(rows[i].t);
  }
  if (run != null) flush(T1);
}
function drawEvents(box, letters) {
  if (!document.getElementById("events").checked) return;
  const i0 = idxAt(view0), i1 = idxAt(view1);
  const marks = [];
  for (let i = i0; i <= i1; i++) {
    const evs = evAt.get(i);
    if (!evs) continue;
    for (const ev of evs) {
      if (ev.code !== 2 && ev.code !== -2) continue;
      marks.push([xOf(box, rows[i].t), ev]);
    }
  }
  if (!marks.length) return;
  const gap = box.w / marks.length;
  if (gap < 5) return;
  const showLetters = letters && gap > 22;
  ctx.lineWidth = 1;
  ctx.font = "11px ui-sans-serif, system-ui, sans-serif";
  ctx.textBaseline = "top";
  ctx.textAlign = "left";
  let lastLabel = -100;
  for (const [x, ev] of marks) {
    ctx.strokeStyle = ev.code > 0 ? C.left : C.right;
    ctx.globalAlpha = ev.ok ? 0.45 : 0.2;
    ctx.beginPath();
    ctx.moveTo(x, box.y); ctx.lineTo(x, box.y + box.h); ctx.stroke();
    if (showLetters && x - lastLabel > 14) {
      ctx.globalAlpha = ev.ok ? 1 : 0.45;
      ctx.fillStyle = ctx.strokeStyle;
      ctx.fillText(ev.code > 0 ? "L" : "R", x + 3, box.y + 3);
      lastLabel = x;
    }
  }
  ctx.globalAlpha = 1;
}
function drawOverview(box) {
  ctx.fillStyle = "#141820";
  ctx.fillRect(box.x, box.y, box.w, box.h);
  const saved0 = view0, saved1 = view1;
  view0 = T0; view1 = T1;
  const yr = yRange(box, r => r.g, 0.08);
  strokeSeries(box, yr[0], yr[1], decimate(0, rows.length - 1, box, r => r.g), C.accel, 1);
  view0 = saved0; view1 = saved1;
  const x0 = box.x + (saved0 - T0) / (T1 - T0) * box.w;
  const x1 = box.x + (saved1 - T0) / (T1 - T0) * box.w;
  ctx.fillStyle = "rgba(126,182,255,0.16)";
  ctx.fillRect(x0, box.y, Math.max(2, x1 - x0), box.h);
  ctx.strokeStyle = "#9eb6d6";
  ctx.strokeRect(x0, box.y, Math.max(2, x1 - x0), box.h);
  ctx.font = "11px ui-sans-serif, system-ui, sans-serif";
  ctx.fillStyle = C.text;
  ctx.textAlign = "left";
  ctx.textBaseline = "bottom";
  ctx.fillText("whole recording", box.x, box.y - 1);
}
function drawMain(box) {
  shadeLock(box);
  const showM = document.getElementById("model").checked;
  const showR = document.getElementById("resid").checked;
  const i0 = idxAt(view0), i1 = idxAt(view1);
  const picks = [r => r.g];
  if (showM) picks.push(r => r.phase == null ? null : amp * Math.cos(r.phase));
  if (showR) picks.push(r => r.phase == null ? null : r.g - amp * Math.cos(r.phase));
  let lo = Infinity, hi = -Infinity;
  for (let i = i0; i <= i1 && i < rows.length; i++) {
    for (const p of picks) {
      const v = p(rows[i]);
      if (v == null || !isFinite(v)) continue;
      if (v < lo) lo = v; if (v > hi) hi = v;
    }
  }
  if (!isFinite(lo)) { lo = -1; hi = 1; }
  const pad = (hi - lo) * 0.08 || 1;
  lo -= pad; hi += pad;
  gridX(box, false); gridY(box, lo, hi, v => (Math.abs(v) >= 10 ? v.toFixed(0) : v.toFixed(1)));
  ctx.fillStyle = C.text; ctx.textAlign = "left"; ctx.textBaseline = "bottom";
  ctx.font = "12px ui-sans-serif, system-ui, sans-serif";
  ctx.fillText("acceleration (g)", box.x, box.y - 2);
  strokeSeries(box, lo, hi, decimate(i0, i1, box, r => r.g), C.accel, 1.6);
  if (showM) strokeSeries(box, lo, hi, decimate(i0, i1, box, r => r.phase == null ? null : amp * Math.cos(r.phase)), C.model, 1.4);
  if (showR) strokeSeries(box, lo, hi, decimate(i0, i1, box, r => r.phase == null ? null : r.g - amp * Math.cos(r.phase)), C.resid, 1.2);
  drawEvents(box, true);
  box._y0 = lo; box._y1 = hi;
}
function drawPos(box) {
  shadeLock(box);
  const i0 = idxAt(view0), i1 = idxAt(view1);
  gridX(box, false);
  gridY(box, -1.15, 1.15, v => v.toFixed(1));
  ctx.fillStyle = C.text; ctx.textAlign = "left"; ctx.textBaseline = "bottom";
  ctx.font = "12px ui-sans-serif, system-ui, sans-serif";
  ctx.fillText("oscillator position  (−1 left, +1 right)", box.x, box.y - 2);
  strokeSeries(box, -1.15, 1.15, decimate(i0, i1, box, r => r.pos), C.pos, 1.6);
  drawEvents(box, false);
}
function drawPace(box) {
  shadeLock(box);
  const i0 = idxAt(view0), i1 = idxAt(view1);
  let plo = Infinity, phi = -Infinity, n = 0;
  for (let i = i0; i <= i1 && i < rows.length; i++) {
    if (rows[i].pace == null) continue;
    if (rows[i].pace < plo) plo = rows[i].pace;
    if (rows[i].pace > phi) phi = rows[i].pace;
    n++;
  }
  if (!n) { plo = 0; phi = 5; }
  const pp = Math.max(0.25, (phi - plo) * 0.2);
  plo -= pp; phi += pp;
  gridX(box, true);
  gridY(box, plo, phi, v => v.toFixed(1), 22);
  ctx.fillStyle = C.pace; ctx.textAlign = "left"; ctx.textBaseline = "bottom";
  ctx.font = "12px ui-sans-serif, system-ui, sans-serif";
  ctx.fillText("oscillator pace (round trips / s)", box.x, box.y - 2);
  strokeSeries(box, plo, phi, decimate(i0, i1, box, r => r.pace), C.pace, 1.6);
}
function draw() {
  const L = layout();
  ctx.clearRect(0, 0, L.w, L.h);
  ctx.fillStyle = C.bg;
  ctx.fillRect(0, 0, L.w, L.h);
  if (!rows.length) {
    ctx.fillStyle = C.text; ctx.font = "14px ui-sans-serif, system-ui, sans-serif";
    ctx.fillText("No capture in this file.", 24, 40);
    return;
  }
  drawOverview(L.overview);
  drawMain(L.main);
  drawPos(L.pos);
  drawPace(L.pace);
  canvas._layout = L;
}
function readout(ev) {
  const L = canvas._layout;
  const el = document.getElementById("readout");
  if (!L || !rows.length) return;
  const rect = canvas.getBoundingClientRect();
  const x = ev.clientX - rect.left, y = ev.clientY - rect.top;
  const boxes = [L.main, L.pos, L.pace];
  let box = null;
  for (const b of boxes) if (x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h) box = b;
  if (!box) { return; }
  const i = idxAt(tOf(box, x));
  const r = rows[i];
  const bits = [r.t.toFixed(3) + " s", "accel " + r.g.toFixed(2) + " g", "raw " + r.raw];
  if (r.locked) {
    bits.push("position " + r.pos.toFixed(2));
    bits.push("phase " + (r.phase * 180 / Math.PI).toFixed(0) + "°");
    bits.push("pace " + r.pace.toFixed(2) + " Hz");
  } else bits.push("oscillator not locked");
  const evs = evAt.get(i);
  if (evs) bits.push(evs.map(e => (e.code > 0 ? "left end" : "right end") + (e.ok ? "" : " ignored")).join(", "));
  el.textContent = bits.join("   ");
}
canvas.addEventListener("mousemove", readout);
canvas.addEventListener("wheel", function (ev) {
  if (!rows.length) return;
  ev.preventDefault();
  const L = canvas._layout;
  const rect = canvas.getBoundingClientRect();
  const x = ev.clientX - rect.left;
  const box = L.main;
  const frac = Math.min(1, Math.max(0, (x - box.x) / box.w));
  const t = view0 + frac * (view1 - view0);
  const factor = ev.deltaY > 0 ? 1.18 : 1 / 1.18;
  let span = (view1 - view0) * factor;
  const full = T1 - T0;
  if (span > full) span = full;
  if (span < 0.05) span = 0.05;
  view0 = t - frac * span;
  view1 = view0 + span;
  clampView();
  draw();
}, { passive: false });
canvas.addEventListener("pointerdown", function (ev) {
  const L = canvas._layout;
  if (!L) return;
  const rect = canvas.getBoundingClientRect();
  const x = ev.clientX - rect.left, y = ev.clientY - rect.top;
  const o = L.overview;
  if (x >= o.x && x <= o.x + o.w && y >= o.y && y <= o.y + o.h) {
    const span = view1 - view0;
    const t = T0 + (x - o.x) / o.w * (T1 - T0);
    view0 = t - span / 2; view1 = view0 + span; clampView(); draw();
    drag = { kind: "overview", x };
  } else {
    drag = { kind: "pan", x, v0: view0, v1: view1 };
  }
  canvas.setPointerCapture(ev.pointerId);
});
canvas.addEventListener("pointermove", function (ev) {
  if (!drag) return;
  const L = canvas._layout;
  const rect = canvas.getBoundingClientRect();
  const x = ev.clientX - rect.left;
  if (drag.kind === "overview") {
    const span = view1 - view0;
    const t = T0 + (x - L.overview.x) / L.overview.w * (T1 - T0);
    view0 = t - span / 2; view1 = view0 + span; clampView(); draw();
  } else {
    const dt = (drag.x - x) / L.main.w * (drag.v1 - drag.v0);
    view0 = drag.v0 + dt; view1 = drag.v1 + dt; clampView(); draw();
  }
});
canvas.addEventListener("pointerup", function () { drag = null; });
canvas.addEventListener("pointerleave", function () { drag = null; });
document.getElementById("reset").addEventListener("click", function () {
  view0 = T0; view1 = T1; draw();
});
for (const id of ["model", "resid", "events"]) document.getElementById(id).addEventListener("change", draw);
window.addEventListener("resize", draw);
draw();
</script>
</body>
</html>
"""


def write_html(path, meta, samples, events):
    data = {
        "meta": meta,
        "dt": [s[0] for s in samples],
        "raw": [s[1] for s in samples],
        "ph": [s[2] for s in samples],
        "w": [s[3] for s in samples],
        "ev": [list(e) for e in events],
    }
    html = HTML.replace("__DATA__", json.dumps(data, separators=(",", ":")))
    with open(path, "w") as f:
        f.write(html)


def export(meta, samples, events, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    rows, ev_by_i = build_series(meta, samples, events)
    csv_path = os.path.join(out_dir, "capture.csv")
    html_path = os.path.join(out_dir, "view.html")
    write_csv(csv_path, rows, ev_by_i)
    write_html(html_path, meta, samples, events)
    return csv_path, html_path, rows


def demo_capture():
    """A fake swing that speeds up, so the page can be opened before a real dump."""
    samples = []
    events = []
    t = 0.0
    # half-period steps through three paces: 2 Hz, then 3.2 Hz, then 4.2 Hz round-trip
    segments = [(2.0, 2.0), (3.2, 3.0), (4.2, 4.0)]
    phase = 0.0
    raw_bias = 0
    mg = 7.77
    sign = 1
    amp_g = 8.0
    i = 0
    for pace, dur in segments:
        omega = pace * 2 * math.pi
        t_end = t + dur
        half = math.pi / omega
        next_ev = t + half * 0.5
        ev_sign = 2
        while t < t_end:
            dt10 = 0 if not samples else 250
            t = (len(samples)) * 0.0025
            # oscillator lags the true motion by 40 ms at the start of each pace, then catches up
            lag = 0.04 * math.exp(-((t - (t_end - dur)) / 0.45))
            true_phase = omega * t
            osc_phase = (true_phase - omega * lag) % (2 * math.pi)
            true_g = amp_g * math.cos(true_phase)
            raw = int(round((true_g / sign) / (mg / 1000.0)))
            samples.append((dt10, raw, int(round(osc_phase * 1000)) % 6283, int(round(omega * 100))))
            if t >= next_ev:
                events.append((i, ev_sign, 1))
                ev_sign = -2 if ev_sign > 0 else 2
                next_ev += half
            i += 1
            if i > 20000:
                break
    meta = {"kept": len(samples), "total": len(samples), "mg": mg, "bias": 0.0, "sign": sign, "shift": 6.0}
    return meta, samples, events


def self_test():
    meta, samples, events = demo_capture()
    lines = ["POV> CAPTURE kept=%d total=%d mg=%.4f bias=%.4f sign=%d shift=%.2f" % (
        meta["kept"], meta["total"], meta["mg"], meta["bias"], meta["sign"], meta["shift"])]
    for i in range(0, len(samples), 8):
        chunk = samples[i:i + 8]
        lines.append("POV> D " + " ".join("%d,%d,%d,%d" % s for s in chunk))
    for i in range(0, len(events), 10):
        chunk = events[i:i + 10]
        lines.append("POV> E " + " ".join("%d,%d,%d" % e for e in chunk))
    lines.append("POV> CAPTURE end")
    text = "noise\n" + "\n".join(lines) + "\nPOV> ===== end of report =====\n"
    got_m, got_s, got_e = parse_capture(text)
    assert got_s == samples, (len(got_s), len(samples))
    assert got_e == events
    assert abs(got_m["mg"] - meta["mg"]) < 1e-6
    rows, _ = build_series(got_m, got_s, got_e)
    assert abs(rows[-1]["t"] - (len(rows) - 1) * 0.0025) < 1e-6
    assert rows[10]["locked"]
    print("self-test ok", len(samples), "samples", len(events), "events")


def main():
    p = argparse.ArgumentParser(description="Build the swing capture CSV and HTML viewer")
    p.add_argument("log", nargs="?", help="serial log containing a CAPTURE block")
    p.add_argument("--demo", action="store_true", help="write a synthetic capture instead")
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--out", default=OUT_DIR)
    args = p.parse_args()
    if args.self_test:
        self_test()
        return
    if args.demo:
        meta, samples, events = demo_capture()
    else:
        if not args.log:
            p.error("give a log file, or --demo")
        with open(args.log, errors="replace") as f:
            text = f.read()
        parsed = parse_capture(text)
        if not parsed:
            raise SystemExit("no CAPTURE block in %s" % args.log)
        meta, samples, events = parsed
    csv_path, html_path, rows = export(meta, samples, events, args.out)
    dur = rows[-1]["t"] - rows[0]["t"] if rows else 0
    print("wrote %s" % csv_path)
    print("wrote %s" % html_path)
    print("samples=%d duration=%.2fs events=%d" % (len(rows), dur, len(events)))


if __name__ == "__main__":
    main()
