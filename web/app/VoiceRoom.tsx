"use client";

import { LiveKitRoom, RoomAudioRenderer, StartAudio } from "@livekit/components-react";
import dynamic from "next/dynamic";
import { useState } from "react";
import AgentStatePill from "./AgentStatePill";
import ApplySetupOnConnect from "./ApplySetupOnConnect";
import { DEFAULT_INTERVIEW, InterviewMode } from "./InterviewPanel";
import InterviewPanel from "./InterviewPanel";
import KbPanel from "./KbPanel";
import { DEFAULT_MODEL, ModelChoice } from "./ModelPanel";
import ModelPanel from "./ModelPanel";
import { DEFAULT_PERSONA, Persona } from "./PersonaPanel";
import PersonaPanel from "./PersonaPanel";
import SetupScreen from "./SetupScreen";
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
 * Held pre-connect session config (the KEY TENSION resolution). Every choice the
 * user makes on the SetupScreen lives here in plain React state with NO room.
 * On Start, the room connects once and ApplySetupOnConnect fires these as the
 * existing RPCs (persona → mode → model) + queued KB uploads. Defaults are
 * agent-mirrored (imported from the panels) so a first-time user can Start
 * immediately (D-02).
 */
export type SessionConfig = {
  persona: Persona;
  mode: InterviewMode;
  model: ModelChoice;
  micDeviceId?: string;
  avatarOn: boolean;
  kbFiles: File[];
};

const DEFAULT_SESSION_CONFIG: SessionConfig = {
  persona: DEFAULT_PERSONA,
  mode: DEFAULT_INTERVIEW,
  model: DEFAULT_MODEL,
  micDeviceId: undefined,
  avatarOn: false,
  kbFiles: [],
};

/**
 * Orchestrator shell for the two-screen flow. Holds the held `sessionConfig`, the
 * `token`, and connect `error`. Renders the SetupScreen while `!token` (no room),
 * and the in-room talking subtree once a token is set — cross-faded via the
 * globals.css screen-enter animation, NEVER unmounting <LiveKitRoom> once
 * connected. The single Start gesture fetches /api/token and setToken (which
 * mounts <LiveKitRoom> + auto-connects); ApplySetupOnConnect then applies the
 * held config after the agent joins.
 */
export default function VoiceRoom() {
  const [sessionConfig, setSessionConfig] = useState<SessionConfig>(DEFAULT_SESSION_CONFIG);
  const [token, setToken] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    // Single user gesture: mic-permission + autoplay-unlock + connect all hang
    // off this click. Fetch the token, then setToken mounts <LiveKitRoom>.
    setError(null);
    setConnecting(true);
    try {
      const res = await fetch("/api/token");
      if (!res.ok) throw new Error(`token fetch failed (${res.status})`);
      const data = await res.json();
      setToken(data.token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "could not start");
      setConnecting(false);
    }
  }

  if (!token) {
    return (
      <SetupScreen
        config={sessionConfig}
        onChange={setSessionConfig}
        onStart={start}
        connecting={connecting}
        error={error}
      />
    );
  }

  return (
    <LiveKitRoom
      serverUrl={SERVER_URL}
      token={token}
      connect
      audio
      video={false}
      options={{
        audioCaptureDefaults: {
          ...AUDIO_CAPTURE_DEFAULTS,
          // Plumb the optional chosen mic into LiveKit; undefined → browser default.
          ...(sessionConfig.micDeviceId ? { deviceId: sessionConfig.micDeviceId } : {}),
        },
      }}
    >
      <RoomAudioRenderer />
      <StartAudio label="Click to enable audio" />
      {/* Once-only post-connect apply of the held setup config (persona → mode →
          model → queued KB), gated on agent readiness. */}
      <ApplySetupOnConnect config={sessionConfig} />
      <div className="screen-enter">
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
                onClick={() => setSessionConfig((c) => ({ ...c, avatarOn: on }))}
                style={{
                  padding: "0.25rem 0.75rem",
                  border: "none",
                  cursor: "pointer",
                  fontWeight: 600,
                  background: sessionConfig.avatarOn === on ? "#58a6ff" : "transparent",
                  color: sessionConfig.avatarOn === on ? "#0b0f14" : "#8b949e",
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        {sessionConfig.avatarOn && (
          <div style={{ width: "100%", height: "360px", marginTop: "1rem" }}>
            <AvatarStage persona={sessionConfig.persona.display_name} />
          </div>
        )}
        <div style={{ display: "flex", gap: "1rem", alignItems: "flex-start", marginTop: "1rem" }}>
          <PersonaPanel />
          <InterviewPanel />
          <ModelPanel />
          <KbPanel />
          <Transcript />
        </div>
      </div>
    </LiveKitRoom>
  );
}
