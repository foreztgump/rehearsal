"use client";

import { useRoomContext, useVoiceAssistant } from "@livekit/components-react";
import { useState } from "react";

import { ApplyState, STATUS_COLOR, STATUS_LABEL } from "./ui/apply";
import { font, inputStyle, labelStyle, palette, panelStyle, radius, space } from "./ui/tokens";

// Duplication seam (08-PATTERNS.md File 2): these choice keys MUST mirror
// agent/main.py MODEL_CHOICES ("fast", "better"). There is no model.get RPC in the
// MVP, so drift here is silent — keep in sync by hand. NEVER surface the raw Ollama
// tag here: the agent maps the plain key → tag (LLM-01).
const CHOICES = ["fast", "better"] as const;

// OUTCOME labels ONLY (LLM-01, REQUIREMENTS:98) — no raw tag, no latency/token
// numbers. The RPC carries the plain key; the label is UI-only.
const CHOICE_LABEL: Record<(typeof CHOICES)[number], string> = {
  fast: "Fast (snappier)",
  better: "Better (more thoughtful)",
};

/**
 * Side-panel response-model picker (LLM-01..LLM-03). Holds local form state — the
 * picked choice (default Fast, LLM-02; per-session persistence by construction —
 * the panel holds the choice for the session) — and sends a {choice} snapshot on
 * Apply over the `model.update` RPC. The "applying…→applied" window is a
 * panel-local ApplyState union; the native RPC return IS the ack (no agent→UI
 * attribute read for the MVP). Must render inside <LiveKitRoom> for room context.
 */
export default function ModelPanel() {
  const room = useRoomContext();
  const { agent } = useVoiceAssistant();
  const [choice, setChoice] = useState<(typeof CHOICES)[number]>("fast");
  const [status, setStatus] = useState<ApplyState>("idle");

  async function apply() {
    setStatus("applying");
    // Target the agent participant (the RPC destination). Prefer the identity
    // surfaced by useVoiceAssistant().agent; fall back to the first non-local
    // remote participant. Guard: no agent joined yet → error.
    const fallback = Array.from(room.remoteParticipants.values())[0];
    const agentIdentity = agent?.identity ?? fallback?.identity;
    if (!agentIdentity) {
      setStatus("error");
      return;
    }
    try {
      // Payload key MUST match the agent's handle_model_update parse: choice.
      // The native RPC return string IS the ack: "applied" on success, "error"
      // when the agent rejected an unknown choice (it validates before mutating).
      const ack = await room.localParticipant.performRpc({
        destinationIdentity: agentIdentity,
        method: "model.update",
        payload: JSON.stringify({ choice }),
      });
      setStatus(ack === "applied" ? "applied" : "error");
    } catch {
      setStatus("error");
    }
  }

  return (
    <div style={panelStyle}>
      <strong style={{ fontSize: font.size.heading }}>Response model</strong>

      <label style={labelStyle}>
        Model
        <select
          style={inputStyle}
          value={choice}
          onChange={(e) => setChoice(e.target.value as (typeof CHOICES)[number])}
        >
          {CHOICES.map((c) => (
            <option key={c} value={c}>{CHOICE_LABEL[c]}</option>
          ))}
        </select>
      </label>

      <button
        className="transition-hover"
        style={{
          padding: `${space.sm} ${space.md}`,
          borderRadius: radius.control,
          border: "none",
          background: palette.action,
          color: palette.bg,
          fontWeight: font.weight.semibold,
          cursor: status === "applying" ? "progress" : "pointer",
        }}
        disabled={status === "applying"}
        onClick={apply}
      >
        Apply
      </button>

      <span
        className="transition-status"
        style={{ minHeight: "1.2rem", color: STATUS_COLOR[status], fontWeight: font.weight.semibold }}
      >
        {STATUS_LABEL[status]}
      </span>
    </div>
  );
}
