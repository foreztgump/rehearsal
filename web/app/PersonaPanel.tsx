"use client";

import { useRoomContext, useVoiceAssistant } from "@livekit/components-react";
import { ReactNode, useState } from "react";

import { ApplyState, STATUS_COLOR, STATUS_LABEL } from "./ui/apply";
import { font, inputStyle, labelStyle, palette, panelStyle, radius, space } from "./ui/tokens";

// File #6 duplication seam (03-PATTERNS.md): these arrays + the seed persona
// MUST mirror agent/persona.py (VOICE_IDS, DIFFICULTY/VERBOSITY/CORRECTION keys,
// DEFAULT_PERSONA). There is no persona.get RPC in the MVP, so drift here is
// silent — keep in sync by hand. Reconcile VOICE_IDS against the Kokoro server
// (curl http://kokoro:8880/v1/audio/voices) once on the VM ([VM-INTROSPECT]).
const VOICE_IDS = [
  "af_heart", "af_bella", "af_nicole", "af_sarah", "af_kore",
  "am_michael", "am_fenrir", "am_puck", "am_adam",
  "bf_emma", "bf_alice", "bm_george", "bm_daniel",
] as const;
const DIFFICULTY = ["beginner", "intermediate", "expert"] as const;
const VERBOSITY = ["terse", "balanced", "detailed"] as const;
const CORRECTION = ["gentle", "moderate", "aggressive"] as const;

// Shared persona shape — imported by SetupScreen + ApplySetupOnConnect so the
// pre-connect held config and the post-connect apply use the same type.
export type Persona = {
  role_text: string;
  display_name: string;
  difficulty: string;
  verbosity: string;
  correction: string;
  voice_id: string;
};

// Seed mirrors agent/persona.py DEFAULT_PERSONA so the panel is populated on load
// with no round-trip. Empty role_text lets the agent fall back to ROLE_PREAMBLE.
export const DEFAULT_PERSONA: Persona = {
  role_text: "",
  display_name: "Cybersecurity Trainer",
  difficulty: "intermediate",
  verbosity: "balanced",
  correction: "gentle",
  voice_id: "af_bella",
};

/**
 * Presentational, fully-controlled persona fields. Renders the panel container
 * (heading + form rows) writing every edit through `onChange`. NO room context,
 * NO RPC — safe to render outside <LiveKitRoom> (the setup-screen path). An
 * optional `footer` slot lets the live wrapper inject its Apply button + status.
 */
function PersonaFields({
  value,
  onChange,
  footer,
}: {
  value: Persona;
  onChange: (p: Persona) => void;
  footer?: ReactNode;
}) {
  function set<K extends keyof Persona>(key: K, fieldValue: string) {
    onChange({ ...value, [key]: fieldValue });
  }

  return (
    <div style={panelStyle}>
      <strong style={{ fontSize: font.size.heading }}>Persona</strong>

      <label style={labelStyle}>
        Display name
        <input
          style={inputStyle}
          value={value.display_name}
          onChange={(e) => set("display_name", e.target.value)}
        />
      </label>

      <label style={labelStyle}>
        Role / instructions
        <textarea
          style={{ ...inputStyle, minHeight: "5rem", resize: "vertical", fontSize: font.size.label }}
          placeholder="Leave blank to use the default Cybersecurity Trainer role."
          value={value.role_text}
          onChange={(e) => set("role_text", e.target.value)}
        />
      </label>

      <label style={labelStyle}>
        Difficulty
        <select
          style={inputStyle}
          value={value.difficulty}
          onChange={(e) => set("difficulty", e.target.value)}
        >
          {DIFFICULTY.map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
      </label>

      <label style={labelStyle}>
        Verbosity
        <select
          style={inputStyle}
          value={value.verbosity}
          onChange={(e) => set("verbosity", e.target.value)}
        >
          {VERBOSITY.map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
      </label>

      <label style={labelStyle}>
        Correction
        <select
          style={inputStyle}
          value={value.correction}
          onChange={(e) => set("correction", e.target.value)}
        >
          {CORRECTION.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </label>

      <label style={labelStyle}>
        Voice
        <select
          style={inputStyle}
          value={value.voice_id}
          onChange={(e) => set("voice_id", e.target.value)}
        >
          {VOICE_IDS.map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
      </label>

      {footer}
    </div>
  );
}

/**
 * Live (uncontrolled) persona editor — the in-room/settings-drawer path. Holds
 * its own form state seeded from DEFAULT_PERSONA and sends a full snapshot on
 * Apply over the `persona.update` RPC. The "applying…→applied" window is a
 * panel-local ApplyState union. Must render inside <LiveKitRoom> for room context.
 */
function PersonaPanelLive() {
  const room = useRoomContext();
  const { agent } = useVoiceAssistant();
  const [persona, setPersona] = useState<Persona>(DEFAULT_PERSONA);
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
      // Payload keys MUST match the agent's Persona(**snapshot):
      // role_text, display_name, difficulty, verbosity, correction, voice_id.
      // Payload carries persona text/enums/voice id only — no credentials. The
      // native RPC return value IS the "applying…→applied" ack (no custom protocol).
      await room.localParticipant.performRpc({
        destinationIdentity: agentIdentity,
        method: "persona.update",
        payload: JSON.stringify(persona),
      });
      setStatus("applied");
    } catch {
      setStatus("error");
    }
  }

  return (
    <PersonaFields
      value={persona}
      onChange={setPersona}
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
 * Side-panel persona editor (PERS-02..PERS-05). Two modes:
 * - Controlled (setup path): pass `value` + `onChange` → renders the form against
 *   lifted state with NO Apply button and NO room context (safe outside the room).
 * - Uncontrolled (live/drawer path): omit props → holds its own state + Apply RPC.
 */
export default function PersonaPanel({
  value,
  onChange,
}: {
  value?: Persona;
  onChange?: (p: Persona) => void;
}) {
  if (onChange) {
    return <PersonaFields value={value ?? DEFAULT_PERSONA} onChange={onChange} />;
  }
  return <PersonaPanelLive />;
}
