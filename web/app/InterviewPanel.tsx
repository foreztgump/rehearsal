"use client";

import { useRoomContext, useVoiceAssistant } from "@livekit/components-react";
import { useEffect, useRef, useState } from "react";

import SegmentedToggle from "./SegmentedToggle";
import {
  DEFAULT_INTERVIEW,
  MODE_INTERVIEW,
  PRACTICE_SCENARIOS,
  ROLE_LABEL,
  ROLES,
  isInterviewMode,
  type InterviewMode,
  withPracticeMode,
} from "./practiceFlow";
import { ApplyState, STATUS_COLOR, STATUS_LABEL } from "./ui/apply";

export { DEFAULT_INTERVIEW, MODE_INTERVIEW, type InterviewMode } from "./practiceFlow";

/**
 * Presentational, fully-controlled practice-mode fields. Renders the panel
 * container (heading + mode/role selects) writing every edit through `onChange`.
 * NO room context, NO RPC — safe to render outside <LiveKitRoom> (the
 * setup-screen path). An optional `footer` slot lets the live wrapper inject its
 * Apply button + status.
 */
export function InterviewFields({
  value,
  onChange,
  personaDisplayName = "",
  disabled,
}: {
  value: InterviewMode;
  onChange: (m: InterviewMode) => void;
  personaDisplayName?: string;
  disabled?: boolean;
}) {
  const hasShownInterviewTarget = useRef(isInterviewMode(value));
  if (isInterviewMode(value)) hasShownInterviewTarget.current = true;

  return (
    <>
      <div className="field full">
        <label className="field-label">What do you want to practice?</label>
        <SegmentedToggle
          ariaLabel="Practice scenario"
          options={PRACTICE_SCENARIOS}
          value={value.mode}
          disabled={disabled}
          onChange={(mode) =>
            onChange(
              withPracticeMode(value, mode, personaDisplayName, hasShownInterviewTarget.current),
            )}
        />
      </div>

      {isInterviewMode(value) && (
        <div className="field">
          <label className="field-label" htmlFor="role-select">
            Interview target
          </label>
          <select
            id="role-select"
            className="control"
            value={value.role_key}
            disabled={disabled}
            onChange={(e) => onChange({ ...value, role_key: e.target.value })}
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>{ROLE_LABEL[r]}</option>
            ))}
          </select>
        </div>
      )}
    </>
  );
}

/**
 * Live (uncontrolled) practice-mode control — the in-room/settings-drawer path.
 * Holds its own state (mode default Learn, MODE-01 + target role) and sends a
 * {mode, role_key} snapshot on Apply over the `mode.update` RPC; the native RPC
 * return IS the ack. Must render inside <LiveKitRoom> for room context.
 */
function InterviewPanelLive({
  initialInterview = DEFAULT_INTERVIEW,
  personaDisplayName = "",
  onApplied,
}: {
  initialInterview?: InterviewMode;
  personaDisplayName?: string;
  onApplied?: (interview: InterviewMode) => void;
}) {
  const room = useRoomContext();
  const { agent } = useVoiceAssistant();
  const [interview, setInterview] = useState<InterviewMode>(initialInterview);
  const [status, setStatus] = useState<ApplyState>("idle");

  useEffect(() => {
    setInterview(initialInterview);
    setStatus((current) => current === "applied" ? current : "idle");
  }, [initialInterview]);

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
      if (ack === "applied") {
        setStatus("applied");
        onApplied?.(interview);
      } else {
        setStatus("error");
      }
    } catch {
      setStatus("error");
    }
  }

  return (
    <div className="drawer-section">
      <h4>Practice mode</h4>
      <InterviewFields
        value={interview}
        onChange={setInterview}
        personaDisplayName={personaDisplayName}
        disabled={status === "applying"}
      />
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
 * Side-panel practice-mode control (MODE-01..MODE-04). Two modes:
 * - Controlled (setup path): pass `value` + `onChange` → renders the form against
 *   lifted state with NO Apply button and NO room context (safe outside the room).
 * - Uncontrolled (live/drawer path): omit props → holds its own state + Apply RPC.
 */
export default function InterviewPanel({
  value,
  onChange,
  personaDisplayName,
  onApplied,
}: {
  value?: InterviewMode;
  onChange?: (m: InterviewMode) => void;
  personaDisplayName?: string;
  onApplied?: (m: InterviewMode) => void;
}) {
  if (onChange) {
    return (
      <InterviewFields
        value={value ?? DEFAULT_INTERVIEW}
        onChange={onChange}
        personaDisplayName={personaDisplayName}
      />
    );
  }
  return (
    <InterviewPanelLive
      initialInterview={value ?? DEFAULT_INTERVIEW}
      personaDisplayName={personaDisplayName}
      onApplied={onApplied}
    />
  );
}
