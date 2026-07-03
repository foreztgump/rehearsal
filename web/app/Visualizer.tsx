"use client";

import { useEffect, useRef } from "react";

import { useVoiceAssistant } from "@livekit/components-react";

import { getTheme, type RGB, type Theme } from "./ui/themes";
import { useTheme } from "./ui/ThemeProvider";
import { speechLevelFromTimeDomain } from "./visualizerLevel";

// Canvas orb visualizer ported from design-mockups/v4 (one renderer per theme).
//
// The mockups drove a synthetic audio "level" from sine functions gated by the
// conversation state. We keep that exact level engine — it matches the approved
// visuals — but gate it on the REAL agent state from useVoiceAssistant() instead
// of a scripted demo, so the orb genuinely reacts to listening/thinking/speaking.
//
// Must render inside <LiveKitRoom>. Pure 2D canvas (no WebGL, no extra deps); the
// rAF loop animates the bitmap only, never layout — same GPU-friendly discipline
// as the CSS. All per-mode mutable state lives in refs so the single effect owns
// one rAF loop for the component's life.

// SPEECH_LEVEL_GAIN + the RMS helpers live in ./visualizerLevel (pure, allocation-free
// so the per-frame time-domain buffer can be hoisted — O8 — and unit-tested).

// rgba() string from an RGB triplet + alpha.
function rgba([r, g, b]: RGB, a: number): string {
  return `rgba(${r},${g},${b},${a})`;
}
function hsl(h: number, s: number, l: number, a: number): string {
  return `hsla(${h},${s}%,${l}%,${a})`;
}

// Persistent per-mode buffers (allocated once, reused each frame).
type VizBuffers = {
  // bloom
  parts: { a: number; r: number; sp: number; sz: number; ph: number }[];
  // sonar
  bars: number[];
  pings: { r: number; a: number }[];
  pingT: number;
  // prism
  amps: number[];
};

function makeBuffers(): VizBuffers {
  const parts = Array.from({ length: 70 }, () => ({
    a: Math.random() * Math.PI * 2,
    r: 0.3 + Math.random() * 0.7,
    sp: 0.2 + Math.random() * 0.8,
    sz: 0.6 + Math.random() * 1.8,
    ph: Math.random() * Math.PI * 2,
  }));
  return {
    parts,
    bars: new Array(64).fill(0),
    pings: [],
    pingT: 0,
    amps: new Array(120).fill(0),
  };
}

type Flags = { speaking: boolean; listening: boolean };

// ---- Per-mode renderers (faithful ports) ----------------------------------

function drawBloom(
  ctx: CanvasRenderingContext2D,
  W: number,
  H: number,
  level: number,
  t: number,
  { speaking, listening }: Flags,
  theme: Theme,
  buf: VizBuffers,
) {
  const { p1, p2, p3 } = theme.viz;
  const cx = W / 2,
    cy = H / 2,
    base = W * 0.16;
  const lerp = (a: RGB, b: RGB, k: number): RGB => [
    a[0] + (b[0] - a[0]) * k,
    a[1] + (b[1] - a[1]) * k,
    a[2] + (b[2] - a[2]) * k,
  ];
  const mix = lerp(p3, p1, Math.min(1, level * 1.4));
  const accent = speaking ? p1 : p3;
  const g = ctx.createRadialGradient(cx, cy, base * 0.4, cx, cy, base * (2.6 + level));
  g.addColorStop(0, rgba(mix, 0.22 + level * 0.4));
  g.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(cx, cy, base * (2.6 + level), 0, 7);
  ctx.fill();
  const petals = 6;
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(t * 0.25);
  ctx.globalCompositeOperation = "lighter";
  for (let k = 0; k < petals; k++) {
    ctx.rotate((Math.PI * 2) / petals);
    const len = base * (1.5 + level * 1.3 + 0.15 * Math.sin(t * 2 + k));
    const wid = base * (0.55 + level * 0.3);
    const pg = ctx.createLinearGradient(0, 0, 0, -len);
    pg.addColorStop(0, rgba(accent, 0));
    pg.addColorStop(0.5, rgba(p2, 0.18 + level * 0.3));
    pg.addColorStop(1, rgba(accent, 0.35 + level * 0.5));
    ctx.fillStyle = pg;
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.quadraticCurveTo(wid, -len * 0.5, 0, -len);
    ctx.quadraticCurveTo(-wid, -len * 0.5, 0, 0);
    ctx.fill();
  }
  ctx.restore();
  ctx.save();
  ctx.translate(cx, cy);
  ctx.globalCompositeOperation = "lighter";
  for (const p of buf.parts) {
    const ang = p.a + t * p.sp * (0.4 + level);
    const rad = base * (1.2 + p.r * (1 + level * 0.8)) + Math.sin(t * 2 + p.ph) * 6;
    const x = Math.cos(ang) * rad,
      y = Math.sin(ang) * rad;
    const al = (0.3 + level * 0.6) * (0.5 + 0.5 * Math.sin(t * 3 + p.ph));
    ctx.fillStyle = rgba(accent, al);
    ctx.beginPath();
    ctx.arc(x, y, p.sz * (1 + level), 0, 7);
    ctx.fill();
  }
  ctx.restore();
  const og = ctx.createRadialGradient(cx - base * 0.25, cy - base * 0.25, base * 0.05, cx, cy, base * (0.95 + level * 0.2));
  og.addColorStop(0, "rgba(255,255,255,0.95)");
  og.addColorStop(0.4, rgba(p1, 0.9));
  og.addColorStop(1, rgba(p3, 0.85));
  ctx.fillStyle = og;
  ctx.beginPath();
  ctx.arc(cx, cy, base * (0.9 + level * 0.18), 0, 7);
  ctx.fill();
  ctx.fillStyle = "rgba(255,255,255,0.5)";
  ctx.beginPath();
  ctx.arc(cx - base * 0.28, cy - base * 0.3, base * 0.16, 0, 7);
  ctx.fill();
}

function drawSonar(
  ctx: CanvasRenderingContext2D,
  W: number,
  H: number,
  level: number,
  t: number,
  { speaking, listening }: Flags,
  theme: Theme,
  buf: VizBuffers,
) {
  const { p1, p2, p3 } = theme.viz;
  const cx = W / 2,
    cy = H / 2,
    base = W * 0.16;
  const accent = speaking ? p1 : p2;
  buf.pingT += 0.016 * (0.6 + level * 2.5);
  if (buf.pingT > 0.5) {
    buf.pingT = 0;
    buf.pings.push({ r: base * 0.8, a: 0.5 + level * 0.5 });
  }
  ctx.lineWidth = 2;
  for (let i = buf.pings.length - 1; i >= 0; i--) {
    const p = buf.pings[i];
    p.r += W * 0.006;
    p.a *= 0.975;
    if (p.a < 0.02) {
      buf.pings.splice(i, 1);
      continue;
    }
    ctx.strokeStyle = rgba(accent, p.a);
    ctx.beginPath();
    ctx.arc(cx, cy, p.r, 0, 7);
    ctx.stroke();
  }
  ctx.save();
  ctx.translate(cx, cy);
  ctx.globalCompositeOperation = "lighter";
  const NB = 64;
  for (let i = 0; i < NB; i++) {
    const target = speaking
      ? (0.3 + Math.random() * 0.7) * level + 0.05
      : (0.05 + 0.04 * Math.sin(t * 2 + i * 0.5)) * (listening ? 1 : 0.5);
    buf.bars[i] += (target - buf.bars[i]) * 0.3;
    const ang = (i / NB) * Math.PI * 2 + t * 0.15;
    const r0 = base * 1.05,
      r1 = r0 + buf.bars[i] * base * 1.6 + 4;
    const x0 = Math.cos(ang) * r0,
      y0 = Math.sin(ang) * r0,
      x1 = Math.cos(ang) * r1,
      y1 = Math.sin(ang) * r1;
    const grd = ctx.createLinearGradient(x0, y0, x1, y1);
    grd.addColorStop(0, rgba(accent, 0.15));
    grd.addColorStop(1, rgba(p1, 0.6 + level * 0.4));
    ctx.strokeStyle = grd;
    ctx.lineWidth = 3;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.lineTo(x1, y1);
    ctx.stroke();
  }
  ctx.restore();
  const g = ctx.createRadialGradient(cx, cy, base * 0.3, cx, cy, base * (1.8 + level));
  g.addColorStop(0, rgba(accent, 0.25 + level * 0.4));
  g.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(cx, cy, base * (1.8 + level), 0, 7);
  ctx.fill();
  const og = ctx.createRadialGradient(cx - base * 0.25, cy - base * 0.25, base * 0.05, cx, cy, base * (0.9 + level * 0.18));
  og.addColorStop(0, "rgba(255,255,255,0.95)");
  og.addColorStop(0.45, rgba(p1, 0.92));
  og.addColorStop(1, rgba(p3, 0.85));
  ctx.fillStyle = og;
  ctx.beginPath();
  ctx.arc(cx, cy, base * (0.85 + level * 0.16), 0, 7);
  ctx.fill();
  ctx.fillStyle = "rgba(255,255,255,0.5)";
  ctx.beginPath();
  ctx.arc(cx - base * 0.26, cy - base * 0.28, base * 0.15, 0, 7);
  ctx.fill();
}

function drawBlob(
  ctx: CanvasRenderingContext2D,
  W: number,
  H: number,
  level: number,
  t: number,
  _flags: Flags,
  theme: Theme,
) {
  const { p1, p2, p3 } = theme.viz;
  const cx = W / 2,
    cy = H / 2,
    base = W * 0.22;
  const amp = base * (0.05 + level * 0.32);
  const blob = (baseR: number, a: number, freqs: [number, number, number], phase: number) => {
    const N = 80;
    ctx.beginPath();
    for (let i = 0; i <= N; i++) {
      const ang = (i / N) * Math.PI * 2;
      let r = baseR;
      r += Math.sin(ang * freqs[0] + phase) * a;
      r += Math.sin(ang * freqs[1] - phase * 1.3) * a * 0.6;
      r += Math.sin(ang * freqs[2] + phase * 0.7) * a * 0.4;
      const x = cx + Math.cos(ang) * r,
        y = cy + Math.sin(ang) * r;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.closePath();
  };
  ctx.globalCompositeOperation = "lighter";
  const g = ctx.createRadialGradient(cx, cy, base * 0.3, cx, cy, base * (1.7 + level));
  g.addColorStop(0, rgba(p1, 0.22 + level * 0.35));
  g.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = g;
  blob(base * 1.25, amp * 1.4, [3, 5, 7], t * 0.5);
  ctx.fill();
  const mg = ctx.createLinearGradient(cx - base, cy - base, cx + base, cy + base);
  mg.addColorStop(0, rgba(p3, 0.5 + level * 0.3));
  mg.addColorStop(1, rgba(p2, 0.5 + level * 0.3));
  ctx.fillStyle = mg;
  blob(base * 0.95, amp, [4, 6, 3], t * 0.8);
  ctx.fill();
  ctx.globalCompositeOperation = "source-over";
  const og = ctx.createRadialGradient(cx - base * 0.3, cy - base * 0.3, base * 0.05, cx, cy, base * 0.85);
  og.addColorStop(0, "rgba(255,255,255,0.98)");
  og.addColorStop(0.4, rgba(p1, 0.95));
  og.addColorStop(1, rgba(p2, 0.9));
  ctx.fillStyle = og;
  blob(base * 0.62, amp * 0.5, [5, 3, 6], t * 1.2);
  ctx.fill();
  ctx.fillStyle = "rgba(255,255,255,0.55)";
  ctx.beginPath();
  ctx.ellipse(cx - base * 0.2, cy - base * 0.25, base * 0.16, base * 0.1, -0.5, 0, 7);
  ctx.fill();
}

function drawPrism(
  ctx: CanvasRenderingContext2D,
  W: number,
  H: number,
  level: number,
  t: number,
  { speaking, listening }: Flags,
  theme: Theme,
  buf: VizBuffers,
) {
  const cx = W / 2,
    cy = H / 2,
    base = W * 0.17;
  const hueBase = speaking ? 252 : listening ? 244 : theme.viz.hueBase ?? 250;
  ctx.globalCompositeOperation = "lighter";
  const g = ctx.createRadialGradient(cx, cy, base * 0.4, cx, cy, base * (2.4 + level));
  g.addColorStop(0, hsl(hueBase, 46, 58, 0.18 + level * 0.32));
  g.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(cx, cy, base * (2.4 + level), 0, 7);
  ctx.fill();
  const NP = 120;
  for (let i = 0; i < NP; i++) {
    const target = speaking
      ? Math.pow(Math.abs(Math.sin(i * 0.4 + t * 4) * Math.sin(i * 0.13 - t * 2)), 2) * level * 1.4 + level * 0.2
      : listening
        ? 0.06 + 0.05 * Math.sin(i * 0.5 + t * 2)
        : 0.03 + 0.02 * Math.sin(i * 0.3 + t);
    buf.amps[i] += (target - buf.amps[i]) * 0.25;
  }
  const layers = [
    { off: 0, hue: hueBase, a: 0.9, w: 2.5 },
    { off: 6, hue: hueBase + 12, a: 0.5, w: 2 },
    { off: -6, hue: hueBase - 10, a: 0.5, w: 2 },
  ];
  ctx.globalCompositeOperation = "lighter";
  for (const L of layers) {
    ctx.beginPath();
    for (let i = 0; i <= NP; i++) {
      const idx = i % NP;
      const a = (i / NP) * Math.PI * 2 - Math.PI / 2;
      const r = base * 1.05 + buf.amps[idx] * base * 1.7 + L.off;
      const x = cx + Math.cos(a) * r,
        y = cy + Math.sin(a) * r;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.strokeStyle = hsl(L.hue, 48, 64, L.a);
    ctx.lineWidth = L.w;
    ctx.lineJoin = "round";
    ctx.shadowColor = hsl(L.hue, 48, 58, 0.8);
    ctx.shadowBlur = 12;
    ctx.stroke();
  }
  ctx.shadowBlur = 0;
  ctx.globalCompositeOperation = "source-over";
  const og = ctx.createRadialGradient(cx - base * 0.25, cy - base * 0.25, base * 0.05, cx, cy, base * (0.9 + level * 0.18));
  og.addColorStop(0, "rgba(255,255,255,0.97)");
  og.addColorStop(0.45, hsl(hueBase, 50, 68, 0.95));
  og.addColorStop(1, hsl(hueBase + 10, 46, 56, 0.9));
  ctx.fillStyle = og;
  ctx.beginPath();
  ctx.arc(cx, cy, base * (0.85 + level * 0.16), 0, 7);
  ctx.fill();
  ctx.fillStyle = "rgba(255,255,255,0.5)";
  ctx.beginPath();
  ctx.arc(cx - base * 0.26, cy - base * 0.28, base * 0.15, 0, 7);
  ctx.fill();
}

const AURORA_BANDS = [
  { hue: 342, base: 1.18, amp: 0.1, sp: 0.5, fr: 3, a: 0.5 },
  { hue: 328, base: 1.32, amp: 0.14, sp: -0.4, fr: 4, a: 0.4 },
  { hue: 356, base: 1.46, amp: 0.18, sp: 0.3, fr: 2, a: 0.3 },
];

function drawAurora(
  ctx: CanvasRenderingContext2D,
  W: number,
  H: number,
  level: number,
  t: number,
  _flags: Flags,
  _theme: Theme,
) {
  const cx = W / 2,
    cy = H / 2,
    base = W * 0.16;
  ctx.globalCompositeOperation = "lighter";
  const g = ctx.createRadialGradient(cx, cy, base * 0.4, cx, cy, base * (2.6 + level));
  g.addColorStop(0, hsl(342, 44, 54, 0.16 + level * 0.3));
  g.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(cx, cy, base * (2.6 + level), 0, 7);
  ctx.fill();
  for (const B of AURORA_BANDS) {
    const N = 100;
    ctx.beginPath();
    for (let i = 0; i <= N; i++) {
      const a = (i / N) * Math.PI * 2;
      const wob = Math.sin(a * B.fr + t * B.sp * 2) * B.amp + Math.sin(a * (B.fr + 2) - t * B.sp * 1.5) * B.amp * 0.5;
      const r = base * (B.base + wob * (0.5 + level * 1.4));
      const x = cx + Math.cos(a) * r,
        y = cy + Math.sin(a) * r;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.strokeStyle = hsl(B.hue, 44, 58, B.a + level * 0.4);
    ctx.lineWidth = base * (0.12 + level * 0.12);
    ctx.shadowColor = hsl(B.hue, 44, 52, 0.7);
    ctx.shadowBlur = 18;
    ctx.stroke();
  }
  ctx.shadowBlur = 0;
  ctx.globalCompositeOperation = "source-over";
  const og = ctx.createRadialGradient(cx - base * 0.25, cy - base * 0.25, base * 0.05, cx, cy, base * (0.9 + level * 0.18));
  og.addColorStop(0, "rgba(255,255,255,0.97)");
  og.addColorStop(0.45, hsl(342, 48, 62, 0.95));
  og.addColorStop(1, hsl(330, 44, 48, 0.9));
  ctx.fillStyle = og;
  ctx.beginPath();
  ctx.arc(cx, cy, base * (0.82 + level * 0.16), 0, 7);
  ctx.fill();
  ctx.fillStyle = "rgba(255,255,255,0.5)";
  ctx.beginPath();
  ctx.arc(cx - base * 0.25, cy - base * 0.27, base * 0.14, 0, 7);
  ctx.fill();
}

// Eclipse Aurora "halo": rotating arcs + glossy orb (mockup 1 used DOM rings;
// rendered here on the canvas for parity with the other five modes).
function drawHalo(
  ctx: CanvasRenderingContext2D,
  W: number,
  H: number,
  level: number,
  t: number,
  { speaking }: Flags,
  theme: Theme,
) {
  const { p1, p2, p3 } = theme.viz;
  const cx = W / 2,
    cy = H / 2,
    base = W * 0.16;
  const g = ctx.createRadialGradient(cx, cy, base * 0.4, cx, cy, base * (2.4 + level));
  g.addColorStop(0, rgba(p1, 0.2 + level * 0.34));
  g.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(cx, cy, base * (2.4 + level), 0, 7);
  ctx.fill();
  ctx.save();
  ctx.translate(cx, cy);
  ctx.globalCompositeOperation = "lighter";
  const rings = [
    { rad: 1.55, hue: p1, speed: 1, span: 1.4, w: 3 },
    { rad: 1.85, hue: p2, speed: -0.7, span: 1.0, w: 2.4 },
    { rad: 2.15, hue: p3, speed: 0.35, span: 0.7, w: 2 },
  ];
  for (const r of rings) {
    const start = t * r.speed * (0.6 + level * 1.6);
    const rad = base * r.rad;
    ctx.strokeStyle = rgba(r.hue, 0.5 + level * 0.4);
    ctx.lineWidth = r.w + level * 2;
    ctx.lineCap = "round";
    ctx.shadowColor = rgba(r.hue, 0.6);
    ctx.shadowBlur = 14;
    ctx.beginPath();
    ctx.arc(0, 0, rad, start, start + r.span);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(0, 0, rad, start + Math.PI, start + Math.PI + r.span * 0.6);
    ctx.stroke();
  }
  ctx.shadowBlur = 0;
  ctx.restore();
  const og = ctx.createRadialGradient(cx - base * 0.25, cy - base * 0.25, base * 0.05, cx, cy, base * (0.9 + level * 0.18));
  og.addColorStop(0, "rgba(255,255,255,0.96)");
  og.addColorStop(0.45, rgba(p1, 0.92));
  og.addColorStop(1, rgba(p3, 0.85));
  ctx.fillStyle = og;
  ctx.beginPath();
  ctx.arc(cx, cy, base * (0.85 + level * 0.16) * (speaking ? 1.02 : 1), 0, 7);
  ctx.fill();
  ctx.fillStyle = "rgba(255,255,255,0.5)";
  ctx.beginPath();
  ctx.arc(cx - base * 0.26, cy - base * 0.28, base * 0.15, 0, 7);
  ctx.fill();
}

const RENDERERS = {
  halo: drawHalo,
  bloom: drawBloom,
  sonar: drawSonar,
  blob: drawBlob,
  prism: drawPrism,
  aurora: drawAurora,
} as const;

/**
 * Audio-reactive orb for the talking screen. Reads the live agent state and
 * renders the active theme's visualizer onto a square canvas that fills its
 * parent. Always rendered inside <LiveKitRoom>.
 */
export default function Visualizer() {
  const { themeId } = useTheme();
  const { state, audioTrack } = useVoiceAssistant();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  // Latest state/theme for the rAF loop without re-subscribing the effect.
  const stateRef = useRef(state);
  const themeRef = useRef(themeId);
  stateRef.current = state;
  themeRef.current = themeId;
  // Read-only analyser on the agent's inbound audio track (AVTR-09). Lets the orb
  // pulse to real speech amplitude when speaking; null => synthetic envelope only.
  const analyserRef = useRef<AnalyserNode | null>(null);

  useEffect(() => {
    const mediaTrack = audioTrack?.publication?.track?.mediaStreamTrack;
    if (!mediaTrack) return;
    let ctx: AudioContext | null = null;
    try {
      ctx = new AudioContext();
      const source = ctx.createMediaStreamSource(new MediaStream([mediaTrack]));
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser); // read-only: never connected to ctx.destination
      // Autoplay policy can leave a fresh context suspended; a suspended graph
      // halts the analyser (all-128 samples → flat orb). Resume best-effort — the
      // user has already gestured (Start) by the time the agent speaks.
      if (ctx.state === "suspended") void ctx.resume().catch(() => {});
      analyserRef.current = analyser;
    } catch {
      // Web Audio unavailable / autoplay-locked: orb stays state-reactive (graceful).
      analyserRef.current = null;
    }
    const closing = ctx;
    return () => {
      analyserRef.current = null;
      closing?.close().catch(() => {});
    };
  }, [audioTrack]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const DPR = Math.min(2, window.devicePixelRatio || 1);
    const buf = makeBuffers();
    // O8: hoist the analyser time-domain buffer out of the rAF loop. The analyser's
    // fftSize is fixed at 512 (set once above), so one reusable Uint8Array serves every
    // frame — the old `new Uint8Array(analyser.fftSize)` per frame churned ~30 KB/s of
    // GC garbage during speech. getByteTimeDomainData overwrites it in place each call.
    const timeDomain = new Uint8Array(512);
    let W = 0,
      H = 0;
    let level = 0,
      t = 0,
      raf = 0,
      last = performance.now();

    // Largest square that fits the parent box on BOTH axes (capped), so the orb
    // scales to fit a short/wide cell instead of overflowing when width alone drives it.
    const ORB_MAX_PX = 340;
    const resize = () => {
      const parent = canvas.parentElement;
      if (!parent) return;
      const s = Math.min(parent.clientWidth, parent.clientHeight, ORB_MAX_PX);
      if (!s) return;
      W = s;
      H = s;
      canvas.style.width = `${s}px`;
      canvas.style.height = `${s}px`;
      canvas.width = s * DPR;
      canvas.height = s * DPR;
      ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    };
    resize();
    const ro = new ResizeObserver(resize);
    if (canvas.parentElement) ro.observe(canvas.parentElement);

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const frame = (now: number) => {
      now = now || performance.now();
      last = now;
      t += 0.016;
      const s = stateRef.current;
      const speaking = s === "speaking";
      const listening = s === "listening";
      // Synthetic level envelope keyed to the real agent state (mockup parity).
      const noisy = speaking
        ? 0.45 + 0.4 * Math.abs(Math.sin(t * 2.0)) + 0.16 * Math.sin(t * 4.7)
        : listening
          ? 0.14 + 0.07 * Math.sin(t * 1.2)
          : s === "thinking"
            ? 0.1 + 0.05 * Math.sin(t * 3)
            : 0.05;
      // While speaking with a live analyser, track the agent's real amplitude so
      // louder syllables swell the orb; otherwise use the synthetic envelope.
      const analyser = analyserRef.current;
      let target = noisy;
      if (speaking && analyser) {
        // Reuse the hoisted buffer (O8): getByteTimeDomainData overwrites it in place.
        analyser.getByteTimeDomainData(timeDomain);
        target = speechLevelFromTimeDomain(timeDomain);
      }
      level += (target - level) * 0.16;
      if (W && H) {
        ctx.clearRect(0, 0, W, H);
        const theme = getTheme(themeRef.current);
        RENDERERS[theme.vizMode](ctx, W, H, level, t, { speaking, listening }, theme, buf);
      }
      raf = requestAnimationFrame(frame);
    };

    if (reduceMotion) {
      // One static frame at a resting level — respect reduced-motion.
      t = 0;
      level = 0.05;
      if (W && H) {
        const theme = getTheme(themeRef.current);
        RENDERERS[theme.vizMode](ctx, W, H, level, t, { speaking: false, listening: false }, theme, buf);
      }
    } else {
      raf = requestAnimationFrame(frame);
    }

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, []);

  return (
    <div
      style={{
        position: "relative",
        width: "100%",
        height: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <canvas ref={canvasRef} style={{ display: "block" }} />
    </div>
  );
}
