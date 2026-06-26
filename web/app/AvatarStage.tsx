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
//   streamStart(opt) -> sets up the 'playback-worklet' AudioWorkletNode
//   streamAudio({audio}) -> feeds 16-bit PCM; the worklet's output feeds the
//     analyzer whose energy drives viseme morphs (NO timestamps = Path-A)
//   streamInterrupt() -> stops avatar audio + lipsync instantly (barge-in)
//   dispose() -> internally calls streamStop() (closes the worklet) + disconnects
//     every audio node + loses the WebGL context.
type TalkingHeadInstance = {
  showAvatar: (avatar: Record<string, unknown>) => Promise<void>;
  streamStart: (opt: Record<string, unknown>) => Promise<void>;
  streamAudio: (r: { audio: Float32Array }) => void;
  streamInterrupt: () => void;
  setMood: (mood: string) => void;
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
  // primary <RoomAudioRenderer/> playout is never touched.
  const tapRef = useRef<{
    clone: MediaStreamTrack;
    source: MediaStreamAudioSourceNode;
    processor: ScriptProcessorNode;
    sink: GainNode;
    sourceTrackId: string;
  } | null>(null);
  // streaming-started guard so we only streamStart() once per head.
  const streamingRef = useRef(false);

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
          tap.processor.onaudioprocess = null;
          tap.processor.disconnect();
          tap.source.disconnect();
          tap.sink.disconnect();
          tap.clone.stop();
        } catch {
          // best-effort during teardown; never throw out of cleanup.
        }
        tapRef.current = null;
      }
      streamingRef.current = false;
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
  // track is available. streamStart({gain:0}) MUTES TalkingHead's own playout so
  // the avatar never double-plays over <RoomAudioRenderer/> — the analyzer still
  // receives full energy, so visemes are driven with NO timestamps/transcription.
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
        old.processor.onaudioprocess = null;
        old.processor.disconnect();
        old.source.disconnect();
        old.sink.disconnect();
        old.clone.stop();
      } catch {
        /* best-effort */
      }
      tapRef.current = null;
    }

    let disposed = false;
    (async () => {
      try {
        // gain:0 => avatar playout silenced (no double audio); sampleRate omitted
        // so the worklet runs at head.audioCtx's rate, matching our capture node.
        // waitForAudioChunks:false => energy drives visemes as chunks arrive.
        if (!streamingRef.current) {
          await head.streamStart({
            gain: 0,
            mood: avatar.mood,
            lipsyncType: "visemes",
            lipsyncLang: "en",
            waitForAudioChunks: false,
          });
          streamingRef.current = true;
        }
        if (disposed) return;

        const ctx = head.audioCtx;
        // CLONE the track so our source is independent of the primary playout —
        // never mute/reroute the original (AVTR-02 read-only second consumer).
        const clone = track.clone();
        const stream = new MediaStream([clone]);
        const source = ctx.createMediaStreamSource(stream);
        // ScriptProcessor captures raw PCM frames with no extra worklet file.
        const processor = ctx.createScriptProcessor(4096, 1, 1);
        // Park the processor on a muted sink so it actually pulls audio frames
        // without adding anything audible to the graph.
        const sink = ctx.createGain();
        sink.gain.value = 0;

        processor.onaudioprocess = (e: AudioProcessingEvent) => {
          const h = headRef.current;
          if (!h || !streamingRef.current) return;
          // Copy the Float32 frame (TalkingHead transfers the buffer to the
          // worklet, so we must hand it an owned copy).
          const input = e.inputBuffer.getChannelData(0);
          h.streamAudio({ audio: new Float32Array(input) });
        };

        source.connect(processor);
        processor.connect(sink);
        sink.connect(ctx.destination);

        if (disposed) {
          processor.onaudioprocess = null;
          processor.disconnect();
          source.disconnect();
          sink.disconnect();
          clone.stop();
          return;
        }

        tapRef.current = {
          clone,
          source,
          processor,
          sink,
          sourceTrackId: track.id,
        };
      } catch {
        // Tap setup failed (e.g. AudioContext suspended pre-gesture); the avatar
        // still renders, just without lip-sync. Operator gate covers this.
      }
    })();

    return () => {
      disposed = true;
    };
  }, [audioTrack, status, avatar.mood]);

  // --- Eye contact + barge-in off the agent state (AVTR-03/04). ---
  // Eye contact is held while the agent is BOTH speaking and listening. When the
  // agent enters 'listening' (the existing LiveKit user-speech-start signal — the
  // same interrupt the call already uses, NO second VAD) we streamInterrupt() to
  // cut avatar audio + lip-sync instantly.
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

    // Barge-in: user started speaking => agent is now 'listening'. Stop the avatar
    // mid-utterance (AVTR-03). Reuses the existing interrupt signal; no new VAD.
    if (state === "listening") {
      try {
        head.streamInterrupt();
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
