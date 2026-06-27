"use client";

import { useVoiceAssistant } from "@livekit/components-react";

// Per-state accent color (theme-driven) for the pill text + dot, surfaced from
// the agent's lk.agent.state participant attribute (no custom data-channel).
const STATE_COLOR: Record<string, string> = {
  initializing: "var(--text-muted)",
  idle: "var(--text-muted)",
  listening: "var(--accent)",
  thinking: "var(--warning)",
  speaking: "var(--accent)",
};

const STATE_LABEL: Record<string, string> = {
  initializing: "Connecting",
  idle: "Idle",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
};

/**
 * Binds useVoiceAssistant().state to the mockup's `.statepill`: a tinted pill with
 * a pulsing dot and colored label (listening / thinking / speaking, VOICE-06).
 * Must render inside <LiveKitRoom>.
 */
export default function AgentStatePill() {
  const { state } = useVoiceAssistant();
  const color = STATE_COLOR[state] ?? "var(--text-muted)";

  return (
    <span className="statepill" style={{ color }}>
      <span className="dot" />
      {STATE_LABEL[state] ?? state}
    </span>
  );
}
