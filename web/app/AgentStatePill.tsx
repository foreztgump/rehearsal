"use client";

import { useVoiceAssistant } from "@livekit/components-react";

import { font, palette, radius, space } from "./ui/tokens";

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
      className="transition-pill"
      style={{
        display: "inline-block",
        padding: `${space.xs} ${space.sm}`,
        borderRadius: radius.pill,
        background: STATE_COLORS[state] ?? "#8b949e",
        color: palette.bg,
        fontWeight: font.weight.semibold,
        fontSize: font.size.label,
        textTransform: "capitalize",
      }}
    >
      {state}
    </span>
  );
}
