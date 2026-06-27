"use client";

import { useRoomContext, useVoiceAssistant } from "@livekit/components-react";
import { ReactNode, useState } from "react";

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

// Shared interview-mode shape — imported by SetupScreen + ApplySetupOnConnect so
// the pre-connect held config and the post-connect apply use the same type. Keys
// MUST match the agent's handle_mode_update parse: mode, role_key.
export type InterviewMode = {
  mode: string;
  role_key: string;
};

// Default mirrors MODE-01 (Learn) + the first role. Held by the setup screen on load.
export const DEFAULT_INTERVIEW: InterviewMode = {
  mode: MODE_LEARN,
  role_key: ROLES[0],
};

/**
 * Presentational, fully-controlled interview-mode fields. Renders the panel
 * container (heading + mode/role selects) writing every edit through `onChange`.
 * NO room context, NO RPC — safe to render outside <LiveKitRoom> (the
 * setup-screen path). An optional `footer` slot lets the live wrapper inject its
 * Apply button + status.
 */
function InterviewFields({
  value,
  onChange,
  footer,
}: {
  value: InterviewMode;
  onChange: (m: InterviewMode) => void;
  footer?: ReactNode;
}) {
  return (
    <div style={panelStyle}>
      <strong style={{ fontSize: font.size.heading }}>Interview Mode</strong>

      <label style={labelStyle}>
        Mode
        <select
          style={inputStyle}
          value={value.mode}
          onChange={(e) => onChange({ ...value, mode: e.target.value })}
        >
          <option value={MODE_LEARN}>Learn / Converse</option>
          <option value={MODE_INTERVIEW}>Interview</option>
        </select>
      </label>

      <label style={labelStyle}>
        Target role
        <select
          style={inputStyle}
          value={value.role_key}
          disabled={value.mode !== MODE_INTERVIEW}
          onChange={(e) => onChange({ ...value, role_key: e.target.value })}
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>{ROLE_LABEL[r]}</option>
          ))}
        </select>
      </label>

      {footer}
    </div>
  );
}

/**
 * Live (uncontrolled) interview-mode control — the in-room/settings-drawer path.
 * Holds its own state (mode default Learn, MODE-01 + target role) and sends a
 * {mode, role_key} snapshot on Apply over the `mode.update` RPC; the native RPC
 * return IS the ack. Must render inside <LiveKitRoom> for room context.
 */
function InterviewPanelLive() {
  const room = useRoomContext();
  const { agent } = useVoiceAssistant();
  const [interview, setInterview] = useState<InterviewMode>(DEFAULT_INTERVIEW);
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
        payload: JSON.stringify(interview),
      });
      setStatus(ack === "applied" ? "applied" : "error");
    } catch {
      setStatus("error");
    }
  }

  return (
    <InterviewFields
      value={interview}
      onChange={setInterview}
      footer={
        <>
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
        </>
      }
    />
  );
}

/**
 * Side-panel Interview-mode control (MODE-01..MODE-04). Two modes:
 * - Controlled (setup path): pass `value` + `onChange` → renders the form against
 *   lifted state with NO Apply button and NO room context (safe outside the room).
 * - Uncontrolled (live/drawer path): omit props → holds its own state + Apply RPC.
 */
export default function InterviewPanel({
  value,
  onChange,
}: {
  value?: InterviewMode;
  onChange?: (m: InterviewMode) => void;
}) {
  if (onChange) {
    return <InterviewFields value={value ?? DEFAULT_INTERVIEW} onChange={onChange} />;
  }
  return <InterviewPanelLive />;
}
