"use client";

import { LiveKitRoom, RoomAudioRenderer, StartAudio } from "@livekit/components-react";
import dynamic from "next/dynamic";
import { useState } from "react";
import AgentStatePill from "./AgentStatePill";
import InterviewPanel from "./InterviewPanel";
import KbPanel from "./KbPanel";
import ModelPanel from "./ModelPanel";
import PersonaPanel from "./PersonaPanel";
import Transcript from "./Transcript";

// Dynamic-import the OPTIONAL 3D avatar so it is ABSENT from the voice-only bundle
// (AVTR-01). ssr:false: WebGL/TalkingHead is browser-only. When the toggle is OFF the
// component is unmounted, which runs AvatarStage's full teardown cleanup.
const AvatarStage = dynamic(() => import("./AvatarStage"), { ssr: false });

// Browser-visible LiveKit WS endpoint (Caddy 7443 vhost → livekit-server:7880).
const SERVER_URL = process.env.NEXT_PUBLIC_LIVEKIT_URL!;

// Client-side echo/noise defense is mandatory and local-first — the playback
// reference signal only exists in the browser, so no server-side cloud
// noise-cancellation plugin is used (PERF-03 local-first).
const AUDIO_CAPTURE_DEFAULTS = {
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
};

/**
 * Single-gesture voice entry: the "Start talking" click does mic-permission +
 * autoplay-unlock + room connect in one user gesture (open-mic, no push-to-talk).
 * Once a token is fetched, renders <LiveKitRoom> with agent audio playout, the
 * autoplay backstop, the agent-state pill, and the two-sided transcript.
 */
export default function VoiceRoom() {
  const [token, setToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Default OFF = Voice only. Flipping ON mounts the dynamic-imported avatar (AVTR-01).
  const [avatarOn, setAvatarOn] = useState(false);
  // Active persona display_name → AvatarStage resolves its GLB+mood (AVTR-06). Seeded
  // to the DEFAULT_PERSONA name in PersonaPanel ("Cybersecurity Trainer") so Avatar
  // mode works out of the box. PersonaPanel still owns its own editable persona state
  // and the persona.update RPC (voice_id, etc.) — this is a client-only display_name
  // lift for avatar selection, NO server change (isolation gate). Wiring point for
  // full persona-change reactivity: lift PersonaPanel's display_name into this state.
  const [personaName] = useState("Cybersecurity Trainer");

  if (!token) {
    return (
      <div>
        <button
          style={{
            fontSize: "1.1rem",
            padding: "0.75rem 1.5rem",
            borderRadius: "0.5rem",
            border: "none",
            background: "#3fb950",
            color: "#0b0f14",
            fontWeight: 600,
            cursor: "pointer",
          }}
          onClick={async () => {
            setError(null);
            try {
              const res = await fetch("/api/token");
              if (!res.ok) throw new Error(`token fetch failed (${res.status})`);
              const data = await res.json();
              setToken(data.token);
            } catch (err) {
              setError(err instanceof Error ? err.message : "could not start");
            }
          }}
        >
          Start talking
        </button>
        <p style={{ color: "#8b949e", marginTop: "0.75rem", fontSize: "0.9rem" }}>
          Tip: use headphones for the cleanest experience — they stop the agent
          from hearing (and interrupting) itself through your speakers.
        </p>
        {error && (
          <p style={{ color: "#f85149", marginTop: "0.75rem" }}>{error}</p>
        )}
      </div>
    );
  }

  return (
    <LiveKitRoom
      serverUrl={SERVER_URL}
      token={token}
      connect
      audio
      video={false}
      options={{ audioCaptureDefaults: AUDIO_CAPTURE_DEFAULTS }}
    >
      <RoomAudioRenderer />
      <StartAudio label="Click to enable audio" />
      <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
        <AgentStatePill />
        {/* Default-OFF "Voice only / Avatar" toggle (AVTR-01). Audio always plays
            normally via <RoomAudioRenderer/> regardless of this toggle (AVTR-02). */}
        <div
          role="group"
          aria-label="Voice only / Avatar"
          style={{
            display: "inline-flex",
            borderRadius: "999px",
            overflow: "hidden",
            border: "1px solid #30363d",
            fontSize: "0.85rem",
          }}
        >
          {([
            ["Voice only", false],
            ["Avatar", true],
          ] as const).map(([label, on]) => (
            <button
              key={label}
              type="button"
              onClick={() => setAvatarOn(on)}
              style={{
                padding: "0.25rem 0.75rem",
                border: "none",
                cursor: "pointer",
                fontWeight: 600,
                background: avatarOn === on ? "#58a6ff" : "transparent",
                color: avatarOn === on ? "#0b0f14" : "#8b949e",
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      {avatarOn && (
        <div style={{ width: "100%", height: "360px", marginTop: "1rem" }}>
          <AvatarStage persona={personaName} />
        </div>
      )}
      <div style={{ display: "flex", gap: "1rem", alignItems: "flex-start", marginTop: "1rem" }}>
        <PersonaPanel />
        <InterviewPanel />
        <ModelPanel />
        <KbPanel />
        <Transcript />
      </div>
    </LiveKitRoom>
  );
}
