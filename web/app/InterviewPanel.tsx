"use client";

import { useRoomContext, useVoiceAssistant } from "@livekit/components-react";
import { useState } from "react";

import { ApplyState, STATUS_COLOR, STATUS_LABEL } from "./ui/apply";
import { font, inputStyle, labelStyle, palette, panelStyle, radius, space } from "./ui/tokens";

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
      // The native RPC return string IS the ack: "applied" on success, "error" when
      // the agent rejected an unknown mode/role_key (it validates before committing).
      const ack = await room.localParticipant.performRpc({
        destinationIdentity: agentIdentity,
        method: "mode.update",
        payload: JSON.stringify({ mode, role_key: roleKey }),
      });
      setStatus(ack === "applied" ? "applied" : "error");
    } catch {
      setStatus("error");
    }
  }

  return (
    <div style={panelStyle}>
      <strong style={{ fontSize: font.size.heading }}>Interview Mode</strong>

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
