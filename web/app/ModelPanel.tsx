"use client";

import { useRoomContext, useVoiceAssistant } from "@livekit/components-react";
import { useEffect, useState } from "react";

import { ApplyState, STATUS_COLOR, STATUS_LABEL } from "./ui/apply";

// R7: choices + labels are baked at build time from the installer's .env (not a
// hardcoded array). One-model install → one option (rendered read-only below).
// Back-compat: unset env → ["fast","better"] (the pre-R7 default). NEVER surface
// the raw Ollama tag here: the agent maps the plain key → tag (LLM-01).
const RAW_CHOICES = (process.env.NEXT_PUBLIC_REHEARSAL_MODEL_CHOICES ?? "fast,better")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);
export const CHOICES = RAW_CHOICES as readonly string[];

const RAW_LABELS = (process.env.NEXT_PUBLIC_REHEARSAL_MODEL_LABELS ?? "Fast,Better")
  .split(",")
  .map((s) => s.trim());
const CHOICE_LABEL: Record<string, string> = Object.fromEntries(
  CHOICES.map((c, i) => [c, RAW_LABELS[i] ?? c])
);

// Shared model-choice type — imported by SetupScreen + ApplySetupOnConnect so the
// pre-connect held config and the post-connect apply use the same type. Widened to
// string in R7 so the baked install set (any keys) typechecks.
export type ModelChoice = string;

// Default = the first baked choice (the installer's chosen default).
export const DEFAULT_MODEL: ModelChoice = CHOICES[0] ?? "fast";

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
  disabled,
}: {
  value: ModelChoice;
  onChange: (c: ModelChoice) => void;
  className?: string;
  disabled?: boolean;
}) {
  return (
    <div className={className ? `field ${className}` : "field"}>
      <label className="field-label" htmlFor="model-select">
        Response model
      </label>
      {CHOICES.length <= 1 ? (
        <input
          id="model-select"
          className="control"
          value={CHOICE_LABEL[CHOICES[0]] ?? CHOICES[0] ?? ""}
          readOnly
          aria-readonly="true"
          disabled={disabled}
        />
      ) : (
        <select
          id="model-select"
          className="control"
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value as ModelChoice)}
        >
          {CHOICES.map((c) => (
            <option key={c} value={c}>{CHOICE_LABEL[c] ?? c}</option>
          ))}
        </select>
      )}
    </div>
  );
}

/**
 * Live (uncontrolled) model picker — the in-room/settings-drawer path. Holds its
 * own choice state (default Fast, LLM-02) and sends a {choice} snapshot on Apply
 * over the `model.update` RPC; the native RPC return IS the ack. Must render
 * inside <LiveKitRoom> for room context.
 */
function ModelPanelLive({
  initialChoice = DEFAULT_MODEL,
  onApplyStart,
  onApplied,
}: {
  initialChoice?: ModelChoice;
  onApplyStart?: () => number;
  onApplied?: (choice: ModelChoice, version: number) => void;
}) {
  const room = useRoomContext();
  const { agent } = useVoiceAssistant();
  const [choice, setChoice] = useState<ModelChoice>(initialChoice);
  const [status, setStatus] = useState<ApplyState>("idle");

  useEffect(() => {
    setChoice(initialChoice);
    setStatus((current) => current === "applied" ? current : "idle");
  }, [initialChoice]);

  async function apply() {
    const applyVersion = onApplyStart?.() ?? 0;
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
      if (ack === "applied") {
        setStatus("applied");
        onApplied?.(choice, applyVersion);
      } else {
        setStatus("error");
      }
    } catch {
      setStatus("error");
    }
  }

  return (
    <div className="drawer-section">
      <h4>Response model</h4>
      <ModelFields value={choice} onChange={setChoice} disabled={status === "applying"} />
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
  onApplyStart,
  onApplied,
}: {
  value?: ModelChoice;
  onChange?: (c: ModelChoice) => void;
  className?: string;
  onApplyStart?: () => number;
  onApplied?: (c: ModelChoice, version: number) => void;
}) {
  if (onChange) {
    return (
      <ModelFields value={value ?? DEFAULT_MODEL} onChange={onChange} className={className} />
    );
  }
  return (
    <ModelPanelLive
      initialChoice={value ?? DEFAULT_MODEL}
      onApplyStart={onApplyStart}
      onApplied={onApplied}
    />
  );
}
