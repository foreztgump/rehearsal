"use client";

import { useVoiceAssistant } from "@livekit/components-react";

// Distinct colour per agent state, surfaced from the agent's lk.agent.state
// participant attribute (no custom data-channel protocol).
const STATE_COLORS: Record<string, string> = {
  initializing: "#8b949e",
  idle: "#8b949e",
  listening: "#3fb950",
  thinking: "#d29922",
  speaking: "#58a6ff",
};

/**
 * Binds useVoiceAssistant().state to a colored pill labeled listening /
 * thinking / speaking (VOICE-06). Must render inside <LiveKitRoom>.
 */
export default function AgentStatePill() {
  const { state } = useVoiceAssistant();

  return (
    <span
      style={{
        display: "inline-block",
        padding: "0.25rem 0.75rem",
        borderRadius: "999px",
        background: STATE_COLORS[state] ?? "#8b949e",
        color: "#0b0f14",
        fontWeight: 600,
        fontSize: "0.9rem",
        textTransform: "capitalize",
      }}
    >
      {state}
    </span>
  );
}
