"use client";

import { useRoomContext, useVoiceAssistant } from "@livekit/components-react";
import { useState } from "react";

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

type ApplyState = "idle" | "applying" | "applied" | "error";

// Seed mirrors agent/persona.py DEFAULT_PERSONA so the panel is populated on load
// with no round-trip. Empty role_text lets the agent fall back to ROLE_PREAMBLE.
const DEFAULT_PERSONA = {
  role_text: "",
  display_name: "Cybersecurity Trainer",
  difficulty: "intermediate",
  verbosity: "balanced",
  correction: "gentle",
  voice_id: "af_bella",
};

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
 * Side-panel persona editor (PERS-02..PERS-05). Holds editable form state seeded
 * from the agent's DEFAULT_PERSONA and sends a full snapshot on Apply over the
 * `persona.update` RPC (wired in 03-02-2). The "applying…→applied" window is a
 * panel-local ApplyState union, independent of the global agent-state pill. Must
 * render inside <LiveKitRoom> for room context.
 */
export default function PersonaPanel() {
  const room = useRoomContext();
  const { agent } = useVoiceAssistant();
  const [persona, setPersona] = useState(DEFAULT_PERSONA);
  const [status, setStatus] = useState<ApplyState>("idle");

  function set<K extends keyof typeof persona>(key: K, value: string) {
    setPersona((prev) => ({ ...prev, [key]: value }));
  }

  async function apply() {
    setStatus("applying");
  }

  return (
    <div style={panelStyle}>
      <strong style={{ fontSize: "1rem" }}>Persona</strong>

      <label style={labelStyle}>
        Display name
        <input
          style={inputStyle}
          value={persona.display_name}
          onChange={(e) => set("display_name", e.target.value)}
        />
      </label>

      <label style={labelStyle}>
        Role / instructions
        <textarea
          style={{ ...inputStyle, minHeight: "5rem", resize: "vertical" }}
          placeholder="Leave blank to use the default Cybersecurity Trainer role."
          value={persona.role_text}
          onChange={(e) => set("role_text", e.target.value)}
        />
      </label>

      <label style={labelStyle}>
        Difficulty
        <select
          style={inputStyle}
          value={persona.difficulty}
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
          value={persona.verbosity}
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
          value={persona.correction}
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
          value={persona.voice_id}
          onChange={(e) => set("voice_id", e.target.value)}
        >
          {VOICE_IDS.map((v) => (
            <option key={v} value={v}>{v}</option>
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
