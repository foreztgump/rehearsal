// Pure audio-level helpers for the canvas orb (Visualizer.tsx). Dependency-free so
// the RMS math is unit-testable with `node --test` (no React / Web Audio) and so the
// per-frame allocation can be hoisted (O8).

// Multiplier mapping inbound-speech RMS (~0.0–0.17 typical) onto the orb's 0–1 level
// so normal speaking fills the orb without clipping (AVTR-09).
export const SPEECH_LEVEL_GAIN = 6;

/**
 * RMS of a Web-Audio time-domain byte frame (getByteTimeDomainData: 0–255, 128 =
 * silence), returned in 0–1. Pure: no allocation, reads only `length` samples of the
 * passed buffer so a hoisted, reused Uint8Array can be handed in each frame (O8).
 */
export function rmsFromTimeDomain(samples: Uint8Array): number {
  if (samples.length === 0) return 0;
  let sumOfSquares = 0;
  for (let i = 0; i < samples.length; i++) {
    const centered = (samples[i] - 128) / 128;
    sumOfSquares += centered * centered;
  }
  return Math.sqrt(sumOfSquares / samples.length);
}

/**
 * The orb target level while speaking with a live analyser: gained RMS clamped to 1.
 * Kept pure/separate from the rAF loop so it is testable and allocation-free.
 */
export function speechLevelFromTimeDomain(samples: Uint8Array): number {
  return Math.min(1, rmsFromTimeDomain(samples) * SPEECH_LEVEL_GAIN);
}
