"use client";

import { LiveKitRoom, RoomAudioRenderer, StartAudio } from "@livekit/components-react";
import dynamic from "next/dynamic";
import { useState } from "react";
import ApplyAvatarMode from "./ApplyAvatarMode";
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

// REL-01: actionable copy when the browser blocks mic access — shown verbatim on the
// SetupScreen so the user can fix it, instead of connecting to a silent dead room.
const MIC_BLOCKED_MESSAGE =
  "Microphone access is blocked. Click the mic/camera icon in your browser's " +
  "address bar, choose Allow, then press Start again.";
// Friendly copy for a token/connect failure (the technical reason is logged, not shown).
const CONNECT_ERROR_MESSAGE =
  "Couldn't reach the session server. Check the stack is running, then try again.";

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
  // SESS-02 transcript reset marker: a wall-clock timestamp bumped on Reset so the
  // live transcript view "forgets" everything finalized before it (the room keeps
  // accumulating transcriptions; the marker is how the UI hides the old turns).
  const [resetMarker, setResetMarker] = useState(0);
  // Avatar framing preference (AVTR-10). Default to the upper (head-and-shoulders)
  // frame — full body reads unnatural without body motion; the user opts into full.
  const [avatarView, setAvatarView] = useState<"upper" | "full">("upper");

  async function probeMicPermission(): Promise<boolean> {
    // REL-01: fail loudly + actionably if the mic is blocked, instead of connecting
    // to a dead room. The probe also primes the permission so LiveKit capture succeeds.
    try {
      const probe = await navigator.mediaDevices.getUserMedia({ audio: true });
      probe.getTracks().forEach((track) => track.stop());
      return true;
    } catch {
      setError(MIC_BLOCKED_MESSAGE);
      setConnecting(false);
      return false;
    }
  }

  async function start() {
    // Single user gesture: mic-permission + autoplay-unlock + connect all hang
    // off this click. Probe the mic first, then fetch the token + mount <LiveKitRoom>.
    setError(null);
    setConnecting(true);
    if (!(await probeMicPermission())) return;
    try {
      const res = await fetch("/api/token");
      if (!res.ok) throw new Error(`token fetch failed (${res.status})`);
      const data = await res.json();
      setToken(data.token);
    } catch (err) {
      // Surface a friendly message; log the technical cause for the operator.
      console.error("session start failed:", err);
      setError(CONNECT_ERROR_MESSAGE);
      setConnecting(false);
    }
  }

  // SESS-03 End: disconnect + clear ALL held ephemeral state. Unmounting <LiveKitRoom>
  // ends the agent job (its closure state current_persona/mode/role/model, session_kb,
  // history, and the per-connection STT cache all die); resetting the config clears KB
  // files, model, persona, and avatarOn in the UI.
  function endSession() {
    setToken(null);
    setSessionConfig(DEFAULT_SESSION_CONFIG);
    setError(null);
    setResetMarker(0);
    // start() set connecting=true and never reset it on success (SetupScreen
    // unmounts on token). Returning to setup must clear it, or the Start button
    // stays stuck disabled on "Connecting…" and a new session can't begin.
    setConnecting(false);
  }

  // SESS-01 New: fresh room/token, KEEP the user's setup choices. Drop the token so
  // <LiveKitRoom> fully unmounts, then re-Start on the next tick.
  function newSession() {
    setToken(null);
    setResetMarker(0);
    setTimeout(() => {
      void start();
    }, 0);
  }

  // SESS-02 Reset: same room. The drawer fires the session.reset RPC (clears the
  // agent's history); this just bumps the marker so the transcript view clears too.
  function resetSession() {
    setResetMarker(Date.now());
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
      {/* Sends avatar.update (initial + on every toggle) to drive the captioned-TTS
          lip-sync gate (AVTR-12). Taps the same SessionConfig.avatarOn — no second
          source of truth; the in-room Voice/Avatar toggle flows through here. */}
      <ApplyAvatarMode avatarOn={sessionConfig.avatarOn} />
      <TalkingScreen
        avatarOn={sessionConfig.avatarOn}
        onToggleAvatar={(on) => setSessionConfig((c) => ({ ...c, avatarOn: on }))}
        // Session lifecycle (SESS-01/02/03): End disconnects + clears held state, New
        // restarts keeping setup, Reset clears history/transcript in the same room.
        onEnd={endSession}
        onNew={newSession}
        onReset={resetSession}
        resetMarker={resetMarker}
        // Avatar framing toggle (upper ↔ full body), only shown when avatarOn.
        avatarView={avatarView}
        onToggleAvatarView={() =>
          setAvatarView((current) => (current === "upper" ? "full" : "upper"))
        }
        // Mount the avatar HERE so the dynamic-import (ssr:false) contract stays in
        // the shell; TalkingScreen only places it in the 360px region when avatarOn.
        avatar={<AvatarStage persona={sessionConfig.persona.display_name} view={avatarView} />}
        agentName={sessionConfig.persona.display_name}
      />
    </LiveKitRoom>
  );
}
