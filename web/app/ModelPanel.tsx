"use client";

import { useRoomContext, useVoiceAssistant } from "@livekit/components-react";
import { useState } from "react";

import { ApplyState, STATUS_COLOR, STATUS_LABEL } from "./ui/apply";

// Duplication seam (08-PATTERNS.md File 2): these choice keys MUST mirror
// agent/main.py MODEL_CHOICES ("fast", "better"). There is no model.get RPC in the
// MVP, so drift here is silent — keep in sync by hand. NEVER surface the raw Ollama
// tag here: the agent maps the plain key → tag (LLM-01).
const CHOICES = ["fast", "better"] as const;

// Shared model-choice type — imported by SetupScreen + ApplySetupOnConnect so the
// pre-connect held config and the post-connect apply use the same type.
export type ModelChoice = (typeof CHOICES)[number];

// Default mirrors LLM-02 (Fast). Held by the setup screen on load.
export const DEFAULT_MODEL: ModelChoice = "fast";

// OUTCOME labels ONLY (LLM-01, REQUIREMENTS:98) — no raw tag, no latency/token
// numbers. The RPC carries the plain key; the label is UI-only.
const CHOICE_LABEL: Record<ModelChoice, string> = {
  fast: "Fast (snappier)",
  better: "Better (more thoughtful)",
};

/**
 * Presentational, fully-controlled model picker. Renders a single labeled field
 * (a `.field` so it drops straight into the setup card's grid) writing every edit
 * through `onChange`. NO room context, NO RPC — safe to render outside
 * <LiveKitRoom> (the setup-screen path). `className` lets the caller span columns.
 */
export function ModelFields({
  value,
  onChange,
  className,
}: {
  value: ModelChoice;
  onChange: (c: ModelChoice) => void;
  className?: string;
}) {
  return (
    <div className={className ? `field ${className}` : "field"}>
      <label className="field-label" htmlFor="model-select">
        Response model
      </label>
      <select
        id="model-select"
        className="control"
        value={value}
        onChange={(e) => onChange(e.target.value as ModelChoice)}
      >
        {CHOICES.map((c) => (
          <option key={c} value={c}>{CHOICE_LABEL[c]}</option>
        ))}
      </select>
    </div>
  );
}

/**
 * Live (uncontrolled) model picker — the in-room/settings-drawer path. Holds its
 * own choice state (default Fast, LLM-02) and sends a {choice} snapshot on Apply
 * over the `model.update` RPC; the native RPC return IS the ack. Must render
 * inside <LiveKitRoom> for room context.
 */
function ModelPanelLive() {
  const room = useRoomContext();
  const { agent } = useVoiceAssistant();
  const [choice, setChoice] = useState<ModelChoice>(DEFAULT_MODEL);
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
    <div className="drawer-section">
      <h4>Response model</h4>
      <ModelFields value={choice} onChange={setChoice} />
      <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
        <button className="btn-apply" disabled={status === "applying"} onClick={apply}>
          Apply
        </button>
        <span
          className="transition-status"
          style={{ color: STATUS_COLOR[status], fontWeight: 600, fontSize: "13px" }}
        >
          {STATUS_LABEL[status]}
        </span>
      </div>
    </div>
  );
}

/**
 * Side-panel response-model picker (LLM-01..LLM-03). Two modes:
 * - Controlled (setup path): pass `value` + `onChange` → renders the form against
 *   lifted state with NO Apply button and NO room context (safe outside the room).
 * - Uncontrolled (live/drawer path): omit props → holds its own state + Apply RPC.
 */
export default function ModelPanel({
  value,
  onChange,
  className,
}: {
  value?: ModelChoice;
  onChange?: (c: ModelChoice) => void;
  className?: string;
}) {
  if (onChange) {
    return <ModelFields value={value ?? DEFAULT_MODEL} onChange={onChange} className={className} />;
  }
  return <ModelPanelLive />;
}
