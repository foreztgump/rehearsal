"use client";

import { useRoomContext, useVoiceAssistant } from "@livekit/components-react";
import { useState } from "react";

// Duplication seam (06-PATTERNS.md File 3): these mode/role keys MUST
// mirror agent/interview.py (MODE_LEARN, MODE_INTERVIEW, ROLES). There is no
// mode.get RPC in the MVP, so drift here is silent — keep in sync by hand.
const MODE_LEARN = "learn";
const MODE_INTERVIEW = "interview";
const ROLES = ["soc_analyst", "security_engineer", "grc"] as const;

// Human-readable labels for the role <select> (UI only — the RPC carries the key).
const ROLE_LABEL: Record<(typeof ROLES)[number], string> = {
  soc_analyst: "SOC Analyst",
  security_engineer: "Security Engineer",
  grc: "GRC Specialist",
};

type ApplyState = "idle" | "applying" | "applied" | "error";

const STATUS_LABEL: Record<ApplyState, string> = {
  idle: "",
  applying: "applying…",
  applied: "applied",
  error: "error — could not apply",
};

const STATUS_COLOR: Record<ApplyState, string> = {
  idle: "#8b949e",
  applying: "#d29922",
  applied: "#3fb950",
  error: "#f85149",
};

const panelStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "0.6rem",
  width: "20rem",
  padding: "1rem",
  border: "1px solid #30363d",
  borderRadius: "0.5rem",
  background: "#0d1117",
  color: "#c9d1d9",
  fontSize: "0.9rem",
};

const labelStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "0.25rem",
  fontWeight: 600,
};

const inputStyle: React.CSSProperties = {
  padding: "0.4rem 0.5rem",
  borderRadius: "0.35rem",
  border: "1px solid #30363d",
  background: "#161b22",
  color: "#c9d1d9",
  fontWeight: 400,
};

/**
 * Side-panel Interview-mode control (MODE-01..MODE-04). Holds local form state —
 * mode (default Learn, MODE-01) + the target role — and sends a {mode, role_key}
 * snapshot on Apply over the `mode.update` RPC (wired in 06-01-2). The
 * "applying…→applied" window is a panel-local ApplyState union; the native RPC
 * return IS the ack (no agent→UI attribute read for the MVP). Must render inside
 * <LiveKitRoom> for room context.
 */
export default function InterviewPanel() {
  const room = useRoomContext();
  const { agent } = useVoiceAssistant();
  const [mode, setMode] = useState<string>(MODE_LEARN);
  const [roleKey, setRoleKey] = useState<(typeof ROLES)[number]>(ROLES[0]);
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
      // Payload keys MUST match the agent's handle_mode_update parse: mode, role_key.
      await room.localParticipant.performRpc({
        destinationIdentity: agentIdentity,
        method: "mode.update",
        payload: JSON.stringify({ mode, role_key: roleKey }),
      });
      setStatus("applied");
    } catch {
      setStatus("error");
    }
  }

  return (
    <div style={panelStyle}>
      <strong style={{ fontSize: "1rem" }}>Interview Mode</strong>

      <label style={labelStyle}>
        Mode
        <select
          style={inputStyle}
          value={mode}
          onChange={(e) => setMode(e.target.value)}
        >
          <option value={MODE_LEARN}>Learn / Converse</option>
          <option value={MODE_INTERVIEW}>Interview</option>
        </select>
      </label>

      <label style={labelStyle}>
        Target role
        <select
          style={inputStyle}
          value={roleKey}
          disabled={mode !== MODE_INTERVIEW}
          onChange={(e) => setRoleKey(e.target.value as (typeof ROLES)[number])}
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>{ROLE_LABEL[r]}</option>
          ))}
        </select>
      </label>

      <button
        style={{
          padding: "0.5rem 1rem",
          borderRadius: "0.35rem",
          border: "none",
          background: "#3fb950",
          color: "#0b0f14",
          fontWeight: 600,
          cursor: status === "applying" ? "progress" : "pointer",
        }}
        disabled={status === "applying"}
        onClick={apply}
      >
        Apply
      </button>

      <span style={{ minHeight: "1.2rem", color: STATUS_COLOR[status], fontWeight: 600 }}>
        {STATUS_LABEL[status]}
      </span>
    </div>
  );
}
