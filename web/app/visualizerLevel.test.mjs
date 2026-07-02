import assert from "node:assert/strict";
import test from "node:test";
import {
  rmsFromTimeDomain,
  speechLevelFromTimeDomain,
  SPEECH_LEVEL_GAIN,
} from "./visualizerLevel.ts";

test("rmsFromTimeDomain returns 0 for a silent (all-128) frame", () => {
  const silent = new Uint8Array(512).fill(128);
  assert.equal(rmsFromTimeDomain(silent), 0);
});

test("rmsFromTimeDomain returns 0 for an empty frame (no divide-by-zero)", () => {
  assert.equal(rmsFromTimeDomain(new Uint8Array(0)), 0);
});

test("rmsFromTimeDomain measures a full-scale square wave as ~1.0", () => {
  // Alternating 0/255 around the 128 midpoint is a full-swing signal → RMS ≈ 1.
  const square = new Uint8Array(512);
  for (let i = 0; i < square.length; i++) square[i] = i % 2 === 0 ? 0 : 255;
  const rms = rmsFromTimeDomain(square);
  assert.ok(Math.abs(rms - 1) < 0.02, `expected ~1.0, got ${rms}`);
});

test("rmsFromTimeDomain reads only the frame it is given (hoisted-buffer safe)", () => {
  // A reused/oversized buffer whose tail is still silent must not inflate the RMS:
  // half full-swing, half silent → RMS well below 1.
  const half = new Uint8Array(512).fill(128);
  for (let i = 0; i < 256; i++) half[i] = i % 2 === 0 ? 0 : 255;
  const rms = rmsFromTimeDomain(half);
  assert.ok(rms > 0.6 && rms < 0.8, `half-swing frame RMS out of range: ${rms}`);
});

test("speechLevelFromTimeDomain applies the gain and clamps to 1", () => {
  const square = new Uint8Array(64);
  for (let i = 0; i < square.length; i++) square[i] = i % 2 === 0 ? 0 : 255;
  // RMS ≈ 1, gained by SPEECH_LEVEL_GAIN, clamped to 1.
  assert.equal(speechLevelFromTimeDomain(square), 1);

  // A tiny signal scales linearly by the gain and stays under 1.
  const tiny = new Uint8Array(64).fill(128);
  tiny[0] = 129; // one LSB of deviation
  const level = speechLevelFromTimeDomain(tiny);
  assert.ok(level > 0 && level < 1, `tiny signal must be in (0,1): ${level}`);
  assert.ok(SPEECH_LEVEL_GAIN > 1, "gain must amplify quiet speech");
});
