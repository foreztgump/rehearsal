"use client";

import { LiveKitRoom, RoomAudioRenderer, StartAudio } from "@livekit/components-react";
import dynamic from "next/dynamic";
import { useState } from "react";
import ApplySetupOnConnect from "./ApplySetupOnConnect";
import { DEFAULT_INTERVIEW, InterviewMode } from "./InterviewPanel";
import { DEFAULT_MODEL, ModelChoice } from "./ModelPanel";
import { DEFAULT_PERSONA, Persona } from "./PersonaPanel";
import SetupScreen from "./SetupScreen";
import TalkingScreen from "./TalkingScreen";

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
      <TalkingScreen
        avatarOn={sessionConfig.avatarOn}
        onToggleAvatar={(on) => setSessionConfig((c) => ({ ...c, avatarOn: on }))}
        // The ONLY disconnect path (success criterion 3): a confirmed Leave sets
        // token=null → <LiveKitRoom> unmounts → back to setup. Full clear-all
        // teardown semantics are Phase 14; this slice wires the affordance only.
        onLeave={() => setToken(null)}
        // Mount the avatar HERE so the dynamic-import (ssr:false) contract stays in
        // the shell; TalkingScreen only places it in the 360px region when avatarOn.
        avatar={<AvatarStage persona={sessionConfig.persona.display_name} />}
        agentName={sessionConfig.persona.display_name}
      />
    </LiveKitRoom>
  );
}
