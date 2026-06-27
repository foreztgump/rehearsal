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
// measure per-frame RMS energy off the inbound track and open the mouth morphs via
// setValue(). This keeps Path-A's no-server-coupling property (energy only, no
// transcription/timestamps) while actually animating the mouth.
type TalkingHeadInstance = {
  showAvatar: (avatar: Record<string, unknown>) => Promise<void>;
  setMood: (mood: string) => void;
  setValue: (mt: string, val: number, ms?: number | null) => void;
  makeEyeContact: (ms: number) => void;
  lookAtCamera: (ms: number) => void;
  dispose: () => void;
  audioCtx: AudioContext;
};
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
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0;
      source.connect(analyser);
      // NOTE: analyser is NOT connected to ctx.destination — we only read it, so the
      // avatar never plays its own copy of the audio (no double playout).

      // Time-domain RMS is the true amplitude envelope: it dips toward zero between
      // syllables, giving real open/close motion. (Frequency-band peak stays high
      // through continuous speech and pins the mouth open — that was the old bug.)
      const time = new Uint8Array(analyser.fftSize);
      let smooth = 0;

      const tick = () => {
        const h = headRef.current;
        if (!h || disposed) return;
        analyser.getByteTimeDomainData(time);
        let sumSq = 0;
        for (let i = 0; i < time.length; i++) {
          const v = (time[i] - 128) / 128;
          sumSq += v * v;
        }
        const rms = Math.sqrt(sumSq / time.length);
        // Gate out the noise floor (~0.01), then scale the speech band into a full
        // open range with a cap; mutedRef holds the mouth shut during barge-in.
        const open = mutedRef.current
          ? 0
          : Math.min(0.8, Math.max(0, rms - 0.01) * 7);
        // Asymmetric smoothing: open fast (attack), close a touch slower (release)
        // so the mouth tracks syllables without strobing.
        const k = open > smooth ? 0.5 : 0.25;
        smooth += (open - smooth) * k;
        try {
          h.setValue("mouthOpen", smooth);
          h.setValue("viseme_aa", smooth * 0.7);
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
        head.setValue("mouthOpen", 0, 80);
        head.setValue("viseme_aa", 0, 80);
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
