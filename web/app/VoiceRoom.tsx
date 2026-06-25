"use client";

import { LiveKitRoom, RoomAudioRenderer, StartAudio } from "@livekit/components-react";
import { useState } from "react";
import AgentStatePill from "./AgentStatePill";
import Transcript from "./Transcript";

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
      <AgentStatePill />
      <Transcript />
    </LiveKitRoom>
  );
}
