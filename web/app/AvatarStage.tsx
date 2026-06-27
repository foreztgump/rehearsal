"use client";

import { useVoiceAssistant } from "@livekit/components-react";
import type { TrackReference } from "@livekit/components-core";
import { useEffect, useRef, useState } from "react";
import {
  avatarForPersona,
  CAMERA_VIEW,
  DRACO_DECODER_PATH,
  TALKINGHEAD_SPECIFIER,
} from "./avatarConfig";

// Surface of the TalkingHead 1.7 instance we touch. Path-A streaming API confirmed
// against the vendored source (web/public/vendor/talkinghead/talkinghead.mjs):
//   streamStart(opt) -> sets up the 'playback-worklet' AudioWorkletNode + analyzer
//   streamInterrupt() -> stops avatar audio + lipsync instantly (barge-in)
//   setValue(mt,val,ms) -> writes the 'system' tier of a morph target, applied to
//     the mesh every frame with the library's own smoothing (talkinghead.mjs:1999).
//   dispose() -> internally calls streamStop() (closes the worklet) + disconnects
//     every audio node + loses the WebGL context.
//
// NOTE on lip-sync mechanism: TalkingHead's built-in streamAudio() energy path only
// MODULATES viseme_* morphs that are already queued in animQueue (talkinghead.mjs
// :2419-2472). Path-A feeds audio with NO viseme/timestamp data, so that queue is
// empty and the built-in path moves nothing. We therefore drive the mouth OURSELVES:
// measure per-frame RMS energy off the inbound track and open the mouth morphs.
//
// We must NOT use setValue() for this. setValue() writes the 'system' tier
// (talkinghead.mjs:1999), which is run through a velocity-ramp exponential smoother
// in updateMorphTargets (talkinghead.mjs:1669-1697): the ramp velocity o.v resets to
// 0 every time the morph reaches its target and re-accelerates from acc≈0.01, so
// per-frame target changes never build speed and the mesh crawls far behind — the
// mouth opens/closes slowly and out of sync. Instead we write the 'realtime' tier
// (talkinghead.mjs:1620-1623), which is applied to the mesh immediately with NO
// smoothing, and we do our own light smoothing in JS so the motion tracks syllables.
// This keeps Path-A's no-server-coupling property (energy only, no
// transcription/timestamps) while actually animating the mouth in time.
type MorphTier = { realtime: number | null; needsUpdate: boolean };
type TalkingHeadInstance = {
  showAvatar: (avatar: Record<string, unknown>) => Promise<void>;
  setMood: (mood: string) => void;
  setValue: (mt: string, val: number, ms?: number | null) => void;
  makeEyeContact: (ms: number) => void;
  lookAtCamera: (ms: number) => void;
  dispose: () => void;
  audioCtx: AudioContext;
  mtAvatar: Record<string, MorphTier>;
};

// Apply a morph value on the immediate 'realtime' tier (bypasses TalkingHead's
// velocity-ramp smoothing — see the mechanism note above).
function setRealtime(head: TalkingHeadInstance, mt: string, val: number) {
  const o = head.mtAvatar[mt];
  if (o) {
    o.realtime = val;
    o.needsUpdate = true;
  }
}
type TalkingHeadModule = {
  TalkingHead: new (
    node: HTMLElement,
    opt: Record<string, unknown>,
  ) => TalkingHeadInstance;
};

// Resolve the inbound agent audio MediaStreamTrack from useVoiceAssistant().audioTrack
// (a TrackReference). This is the SAME track <RoomAudioRenderer/> renders — we only
// read it, never mute/reroute it (AVTR-02).
function inboundTrack(ref: TrackReference | undefined): MediaStreamTrack | null {
  const t = ref?.publication?.track?.mediaStreamTrack;
  return t ?? null;
}

/**
 * Dynamic-imported (ssr:false) WebGL avatar stage for the OPTIONAL 3D talking head
 * (Phase 12). 12-02 wires the behaviour: loads the persona's GLB (AVTR-06), Path-A
 * audio-driven lip-sync off the INBOUND Kokoro WebRTC track (AVTR-02), eye-contact +
 * mood off the agent state (AVTR-04), and barge-in via the existing LiveKit
 * user-speech-start interrupt (AVTR-03). Still ZERO server diff.
 */
export default function AvatarStage({ persona }: { persona?: string }) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const headRef = useRef<TalkingHeadInstance | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );

  const { state, audioTrack } = useVoiceAssistant();
  const avatar = avatarForPersona(persona);

  // Path-A audio tap resources, torn down with the stage. The cloned track + its
  // Web Audio nodes are a SECOND, read-only consumer of the agent audio — the
  // primary <RoomAudioRenderer/> playout is never touched. We read per-frame energy
  // off the analyser and drive the mouth morphs via head.setValue() ourselves
  // (the built-in energy path needs queued visemes we never feed — see header note).
  const tapRef = useRef<{
    ctx: AudioContext;
    clone: MediaStreamTrack;
    source: MediaStreamAudioSourceNode;
    analyser: AnalyserNode;
    raf: number;
    sourceTrackId: string;
  } | null>(null);
  // barge-in flag: when the user is speaking we hold the mouth shut regardless of
  // any residual inbound audio energy.
  const mutedRef = useRef(false);

  // --- Mount: construct head + load the persona GLB (AVTR-05/06/08). Runs once. ---
  useEffect(() => {
    let cancelled = false;

    (async () => {
      const host = hostRef.current;
      if (!host) return;

      try {
        const mod: TalkingHeadModule = await import(
          /* webpackIgnore: true */ TALKINGHEAD_SPECIFIER
        );
        if (cancelled) return;

        // Interview framing (AVTR-05); no TTS path (empty ttsEndpoint => no
        // Google-TTS pipeline); no lipsync-*.mjs modules (Path-A is energy-driven,
        // not phoneme tables). dracoEnabled + same-origin decoder so the Draco GLB
        // decodes offline (AVTR-08), never hitting the gstatic CDN default.
        const head = new mod.TalkingHead(host, {
          cameraView: CAMERA_VIEW,
          lipsyncModules: [],
          ttsEndpoint: "",
          jwtGet: null,
          dracoEnabled: true,
          dracoDecoderPath: DRACO_DECODER_PATH,
        });

        if (cancelled) {
          head.dispose();
          return;
        }
        headRef.current = head;

        // Load the active persona's GLB and apply its resting mood (AVTR-04/06).
        await head.showAvatar({
          url: avatar.glb,
          body: avatar.body,
          avatarMood: avatar.mood,
          lipsyncLang: "en",
        });
        if (cancelled) {
          head.dispose();
          headRef.current = null;
          return;
        }

        head.setMood(avatar.mood);
        setStatus("ready");
      } catch {
        // WebGL-unavailable / import / GLB-decode failure: degrade gracefully
        // (AVTR-08). The toggle is the escape hatch — never throw, no retry.
        if (!cancelled) setStatus("error");
      }
    })();

    // Full teardown on unmount / Avatar-toggle-OFF (AVTR-01/03/08). Tear down OUR
    // audio tap first (close ScriptProcessor + source + cloned track), then
    // dispose() — which internally streamStop()s the worklet, disconnects every
    // audio node and loses the WebGL context. Nothing is left running.
    return () => {
      cancelled = true;
      const tap = tapRef.current;
      if (tap) {
        try {
          cancelAnimationFrame(tap.raf);
          tap.source.disconnect();
          tap.analyser.disconnect();
          tap.clone.stop();
          tap.ctx.close();
        } catch {
          // best-effort during teardown; never throw out of cleanup.
        }
        tapRef.current = null;
      }
      const head = headRef.current;
      if (head) {
        try {
          head.dispose();
        } catch {
          // dispose is best-effort during teardown; never throw out of cleanup.
        }
        headRef.current = null;
      }
    };
    // Mount-once: the GLB load + teardown lifecycle is keyed to the component's
    // mount (the Avatar toggle), not to persona/state. avatar.* is read at mount;
    // persona-change reactivity is handled in the dedicated effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- Persona change: re-apply mood without reloading the head (AVTR-04). ---
  // (GLB swap on persona change is a future refinement — see 12-AVATAR-VERIFY.md.)
  useEffect(() => {
    const head = headRef.current;
    if (head && status === "ready") {
      try {
        head.setMood(avatar.mood);
      } catch {
        /* non-fatal */
      }
    }
  }, [avatar.mood, status]);

  // --- Path-A lip-sync tap on the INBOUND Kokoro track (AVTR-02). ---
  // Build the read-only Web Audio tap once the head is ready and the agent audio
  // track is available. We CLONE the inbound track into our OWN AudioContext +
  // AnalyserNode (never touching the primary <RoomAudioRenderer/> playout), then a
  // rAF loop reads frequency energy and opens the mouth morphs via head.setValue().
  // This is Path-A (energy only, NO transcription/timestamps) but drives the mouth
  // directly because TalkingHead's built-in energy path only modulates queued
  // visemes we never feed (see header note).
  useEffect(() => {
    const head = headRef.current;
    if (!head || status !== "ready") return;

    const track = inboundTrack(audioTrack);
    if (!track) return;

    // Already tapping this exact track? Nothing to do.
    if (tapRef.current && tapRef.current.sourceTrackId === track.id) return;

    // Track changed (new agent/publication): tear down the stale tap first.
    if (tapRef.current) {
      const old = tapRef.current;
      try {
        cancelAnimationFrame(old.raf);
        old.source.disconnect();
        old.analyser.disconnect();
        old.clone.stop();
      } catch {
        /* best-effort */
      }
      tapRef.current = null;
    }

    let disposed = false;
    try {
      // Dedicated AudioContext for the read-only tap. CLONE the track so our source
      // is independent of the primary playout — never mute/reroute the original
      // (AVTR-02 read-only second consumer).
      const ctx = new AudioContext();
      const clone = track.clone();
      const stream = new MediaStream([clone]);
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      // 2048-point FFT => ~23 Hz/bin at 48 kHz, fine enough to resolve the first two
      // vowel formants (F1 ~250-850 Hz, F2 ~800-2500 Hz) for Path-A viseme shaping.
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0;
      source.connect(analyser);
      // NOTE: analyser is NOT connected to ctx.destination — we only read it, so the
      // avatar never plays its own copy of the audio (no double playout).

      // Time-domain RMS is the true amplitude envelope: it dips toward zero between
      // syllables, giving real open/close motion. (Frequency-band peak stays high
      // through continuous speech and pins the mouth open — that was the old bug.)
      const time = new Uint8Array(analyser.fftSize);
      const freq = new Uint8Array(analyser.frequencyBinCount);
      const hz = ctx.sampleRate / analyser.fftSize; // Hz per bin

      // Vowel viseme templates as (F1,F2) formant centroids in Hz. Path-A can't know
      // the phoneme, but the spectral shape of a vowel is dominated by F1/F2, so we
      // estimate them per frame and blend toward the nearest vowel. Consonants stay
      // approximate (energy-only) — this is the best achievable without transcription.
      const VOWELS: { m: string; f1: number; f2: number }[] = [
        { m: "viseme_aa", f1: 730, f2: 1090 },
        { m: "viseme_E", f1: 530, f2: 1840 },
        { m: "viseme_I", f1: 300, f2: 2300 },
        { m: "viseme_O", f1: 570, f2: 840 },
        { m: "viseme_U", f1: 440, f2: 1020 },
      ];
      const VKEYS = VOWELS.map((v) => v.m);
      // Per-viseme smoothed weights so shapes cross-fade instead of snapping.
      const vw: Record<string, number> = {};
      for (const k of VKEYS) vw[k] = 0;
      let smooth = 0;

      // Find the dominant spectral peak (bin index) within [loHz,hiHz].
      const peakHz = (loHz: number, hiHz: number) => {
        const lo = Math.max(1, Math.floor(loHz / hz));
        const hi = Math.min(freq.length - 1, Math.ceil(hiHz / hz));
        let bi = lo;
        let bv = -1;
        for (let i = lo; i <= hi; i++) {
          if (freq[i] > bv) {
            bv = freq[i];
            bi = i;
          }
        }
        return { f: bi * hz, mag: bv };
      };

      const tick = () => {
        const h = headRef.current;
        if (!h || disposed) return;

        // --- 1) Envelope (how far the mouth opens) from time-domain RMS. ---
        analyser.getByteTimeDomainData(time);
        let sumSq = 0;
        for (let i = 0; i < time.length; i++) {
          const v = (time[i] - 128) / 128;
          sumSq += v * v;
        }
        const rms = Math.sqrt(sumSq / time.length);
        const open = mutedRef.current
          ? 0
          : Math.min(0.9, Math.max(0, rms - 0.01) * 8);
        // Snap open fast (attack), ease closed slower (release). The realtime tier
        // applies this immediately, so this is the ONLY smoothing in the chain.
        const k = open > smooth ? 0.9 : 0.45;
        smooth += (open - smooth) * k;

        // --- 2) Vowel shape (which mouth shape) from F1/F2 formant estimate. ---
        let target = "viseme_aa";
        if (!mutedRef.current && smooth > 0.06) {
          analyser.getByteFrequencyData(freq);
          const f1 = peakHz(250, 900);
          const f2 = peakHz(900, 2700);
          // Only classify when there's real voiced energy in the formant bands.
          if (f2.mag > 60) {
            let best = VOWELS[0];
            let bestD = Infinity;
            for (const vo of VOWELS) {
              // F2 dominates the classification. F1 is only lightly weighted because
              // for high-pitched voices (e.g. Kokoro af_bella, F0 ~230 Hz) the pitch
              // fundamental masks F1 in the 250-900 Hz band, making it unreliable.
              const d1 = (f1.f - vo.f1) / 700;
              const d2 = (f2.f - vo.f2) / 1200;
              const d = 0.15 * d1 * d1 + d2 * d2;
              if (d < bestD) {
                bestD = d;
                best = vo;
              }
            }
            target = best.m;
          }
        }
        // Cross-fade viseme weights toward the chosen vowel; decay the rest.
        for (const key of VKEYS) {
          const goal = key === target ? smooth : 0;
          vw[key] += (goal - vw[key]) * (goal > vw[key] ? 0.6 : 0.35);
        }

        try {
          setRealtime(h, "mouthOpen", smooth);
          for (const key of VKEYS) setRealtime(h, key, vw[key]);
        } catch {
          /* non-fatal per-frame */
        }
        const raf = requestAnimationFrame(tick);
        if (tapRef.current) tapRef.current.raf = raf;
      };
      const raf = requestAnimationFrame(tick);

      if (disposed) {
        cancelAnimationFrame(raf);
        source.disconnect();
        analyser.disconnect();
        clone.stop();
        ctx.close();
        return;
      }

      tapRef.current = {
        ctx,
        clone,
        source,
        analyser,
        raf,
        sourceTrackId: track.id,
      };
    } catch {
      // Tap setup failed (e.g. AudioContext blocked pre-gesture); the avatar still
      // renders, just without lip-sync. Operator gate covers this.
    }

    return () => {
      disposed = true;
      const tap = tapRef.current;
      if (tap && tap.sourceTrackId === track.id) {
        try {
          cancelAnimationFrame(tap.raf);
          tap.source.disconnect();
          tap.analyser.disconnect();
          tap.clone.stop();
          tap.ctx.close();
        } catch {
          /* best-effort */
        }
        tapRef.current = null;
      }
    };
  }, [audioTrack, status]);

  // --- Eye contact + barge-in off the agent state (AVTR-03/04). ---
  // Eye contact is held while the agent is BOTH speaking and listening. Barge-in:
  // when the user starts speaking the agent leaves 'speaking' (the existing LiveKit
  // interrupt — the same signal the call already uses, NO second VAD); we hold the
  // mouth shut so the avatar stops mid-utterance instantly.
  useEffect(() => {
    const head = headRef.current;
    if (!head || status !== "ready") return;

    if (state === "speaking" || state === "listening") {
      try {
        head.makeEyeContact(2000);
        head.lookAtCamera(500);
      } catch {
        /* non-fatal */
      }
    }

    // Drive lip-sync only while the agent is actually speaking. Any other state
    // (listening/thinking/idle) gates the mouth shut — this is the barge-in cut
    // (AVTR-03): the instant the user speaks, the agent leaves 'speaking' and the
    // mouth snaps closed mid-utterance. Reuses the existing signal; no new VAD.
    const speaking = state === "speaking";
    mutedRef.current = !speaking;
    if (!speaking) {
      try {
        setRealtime(head, "mouthOpen", 0);
        for (const v of [
          "viseme_aa",
          "viseme_E",
          "viseme_I",
          "viseme_O",
          "viseme_U",
        ]) {
          setRealtime(head, v, 0);
        }
      } catch {
        /* non-fatal */
      }
    }
  }, [state, status]);

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <div
        ref={hostRef}
        aria-label="3D avatar"
        style={{ width: "100%", height: "100%" }}
      />
      {status === "loading" && (
        <p style={{ color: "#8b949e", fontSize: "0.9rem" }}>loading avatar…</p>
      )}
      {status === "error" && (
        <p style={{ color: "#d29922", fontSize: "0.9rem" }}>
          3D avatar unavailable on this device — use Voice only.
        </p>
      )}
    </div>
  );
}
