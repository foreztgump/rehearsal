"use client";

import { useRoomContext, useVoiceAssistant } from "@livekit/components-react";
import { useEffect, useState } from "react";

import { ApplyState, STATUS_COLOR, STATUS_LABEL } from "./ui/apply";
import {
  PERSONA_CORRECTION,
  PERSONA_DIFFICULTY,
  PERSONA_VERBOSITY,
  PERSONA_VOICE_IDS,
  deleteSavedPersonaResult,
  readSavedPersonas,
  saveSavedPersonaResult,
  type Persona,
  type SavedPersona,
} from "./savedPersonas";

export type { Persona } from "./savedPersonas";

// Seed mirrors agent/persona.py DEFAULT_PERSONA so the panel is populated on load
// with no round-trip. Empty role_text lets the agent fall back to ROLE_PREAMBLE.
export const DEFAULT_PERSONA: Persona = {
  role_text: "",
  display_name: "Voice Fluency Coach",
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
export function PersonaFields({
  value,
  onChange,
  disabled,
}: {
  value: Persona;
  onChange: (p: Persona) => void;
  disabled?: boolean;
}) {
  function set<K extends keyof Persona>(key: K, fieldValue: string) {
    onChange({ ...value, [key]: fieldValue });
  }

  return (
    <>
      <div className="field full">
        <label className="field-label" htmlFor="persona-name">
          Display name
        </label>
        <input
          id="persona-name"
          className="control"
          value={value.display_name}
          disabled={disabled}
          onChange={(e) => set("display_name", e.target.value)}
        />
      </div>

      <div className="field full">
        <label className="field-label" htmlFor="persona-role">
          Role / instructions
        </label>
        <textarea
          id="persona-role"
          className="control"
          placeholder="Leave blank to use the default Voice Fluency Coach role."
          value={value.role_text}
          disabled={disabled}
          onChange={(e) => set("role_text", e.target.value)}
        />
      </div>

      <div className="field">
        <label className="field-label" htmlFor="persona-difficulty">
          Difficulty
        </label>
        <select
          id="persona-difficulty"
          className="control"
          value={value.difficulty}
          disabled={disabled}
          onChange={(e) => set("difficulty", e.target.value)}
        >
          {PERSONA_DIFFICULTY.map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
      </div>

      <div className="field">
        <label className="field-label" htmlFor="persona-verbosity">
          Verbosity
        </label>
        <select
          id="persona-verbosity"
          className="control"
          value={value.verbosity}
          disabled={disabled}
          onChange={(e) => set("verbosity", e.target.value)}
        >
          {PERSONA_VERBOSITY.map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
      </div>

      <div className="field">
        <label className="field-label" htmlFor="persona-correction">
          Correction
        </label>
        <select
          id="persona-correction"
          className="control"
          value={value.correction}
          disabled={disabled}
          onChange={(e) => set("correction", e.target.value)}
        >
          {PERSONA_CORRECTION.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </div>

      <div className="field">
        <label className="field-label" htmlFor="persona-voice">
          Voice
        </label>
        <select
          id="persona-voice"
          className="control"
          value={value.voice_id}
          disabled={disabled}
          onChange={(e) => set("voice_id", e.target.value)}
        >
          {PERSONA_VOICE_IDS.map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
      </div>
    </>
  );
}

export function SavedPersonaControls({
  value,
  onLoad,
  disabled,
}: {
  value: Persona;
  onLoad: (persona: Persona) => void;
  disabled?: boolean;
}) {
  const [saved, setSaved] = useState<SavedPersona[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [saveName, setSaveName] = useState(value.display_name);
  const [saveNameDirty, setSaveNameDirty] = useState(false);
  const [status, setStatus] = useState("");

  useEffect(() => {
    const next = readSavedPersonas();
    setSaved(next);
    setSelectedId(next[0]?.id ?? "");
  }, []);

  useEffect(() => {
    if (!saveNameDirty) setSaveName(value.display_name);
  }, [saveNameDirty, value.display_name]);

  function refresh(next: SavedPersona[]) {
    setSaved(next);
    setSelectedId((current) => {
      if (next.some((item) => item.id === current)) return current;
      return next[0]?.id ?? "";
    });
  }

  function saveCurrent() {
    const trimmedName = saveName.trim();
    if (!trimmedName) {
      setStatus("Name required");
      return;
    }
    const sameName = (item: SavedPersona) =>
      item.name.toLowerCase() === trimmedName.toLowerCase();
    const result = saveSavedPersonaResult(value, trimmedName);
    if (!result.ok) {
      setStatus("Couldn't save");
      return;
    }
    const savedEntry = result.personas.find(sameName);
    refresh(result.personas);
    setSelectedId(savedEntry?.id ?? "");
    setStatus("Saved");
  }

  function loadSelected() {
    const selected = saved.find((item) => item.id === selectedId);
    if (!selected) {
      setStatus("Pick a persona");
      return;
    }
    onLoad({ ...selected.persona });
    setSaveName(selected.name);
    setSaveNameDirty(true);
    setStatus("Loaded");
  }

  function deleteSelected() {
    const id = selectedId;
    if (!id) {
      setStatus("Pick a persona");
      return;
    }
    const result = deleteSavedPersonaResult(id);
    if (!result.ok) {
      setStatus("Couldn't delete");
      return;
    }
    refresh(result.personas);
    setStatus("Deleted");
  }

  return (
    <div className="field full">
      <label className="field-label" htmlFor="saved-persona-name">
        Saved personas
      </label>
      <input
        id="saved-persona-name"
        className="control"
        value={saveName}
        disabled={disabled}
        onChange={(e) => {
          setSaveNameDirty(true);
          setSaveName(e.target.value);
        }}
      />
      <select
        className="control"
        aria-label="Saved persona"
        value={selectedId}
        disabled={disabled || saved.length === 0}
        onChange={(e) => setSelectedId(e.target.value)}
      >
        {saved.length === 0 ? (
          <option value="">No saved personas</option>
        ) : (
          saved.map((item) => (
            <option key={item.id} value={item.id}>{item.name}</option>
          ))
        )}
      </select>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", alignItems: "center" }}>
        <button type="button" className="btn-apply" disabled={disabled} onClick={saveCurrent}>
          Save
        </button>
        <button
          type="button"
          className="btn-ghost"
          disabled={disabled || saved.length === 0}
          onClick={loadSelected}
        >
          Load
        </button>
        <button
          type="button"
          className="btn-ghost"
          disabled={disabled || saved.length === 0}
          onClick={deleteSelected}
        >
          Delete
        </button>
        {status && (
          <span
            className="transition-status"
            role="status"
            style={{ color: "var(--text-muted)", fontSize: "13px" }}
          >
            {status}
          </span>
        )}
      </div>
    </div>
  );
}

/**
 * Live (uncontrolled) persona editor — the in-room/settings-drawer path. Holds
 * its own form state seeded from DEFAULT_PERSONA and sends a full snapshot on
 * Apply over the `persona.update` RPC. The "applying…→applied" window is a
 * panel-local ApplyState union. Must render inside <LiveKitRoom> for room context.
 */
function PersonaPanelLive({
  initialPersona = DEFAULT_PERSONA,
  onApplyStart,
  onApplied,
}: {
  initialPersona?: Persona;
  onApplyStart?: () => number;
  onApplied?: (persona: Persona, version: number) => void;
}) {
  const room = useRoomContext();
  const { agent } = useVoiceAssistant();
  const [persona, setPersona] = useState<Persona>(initialPersona);
  const [status, setStatus] = useState<ApplyState>("idle");

  useEffect(() => {
    setPersona(initialPersona);
    setStatus((current) => current === "applied" ? current : "idle");
  }, [initialPersona]);

  function setLocalPersona(next: Persona) {
    setPersona(next);
    setStatus("idle");
  }

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
      // Payload keys MUST match the agent's Persona(**snapshot):
      // role_text, display_name, difficulty, verbosity, correction, voice_id.
      // Payload carries persona text/enums/voice id only — no credentials. The
      // native RPC return value IS the "applying…→applied" ack (no custom protocol).
      const ack = await room.localParticipant.performRpc({
        destinationIdentity: agentIdentity,
        method: "persona.update",
        payload: JSON.stringify(persona),
      });
      if (ack === "applied") {
        setStatus("applied");
        onApplied?.(persona, applyVersion);
      } else {
        setStatus("error");
      }
    } catch {
      setStatus("error");
    }
  }

  return (
    <div className="drawer-section">
      <h4>Persona</h4>
      <div className="grid-2">
        <SavedPersonaControls
          value={persona}
          onLoad={setLocalPersona}
          disabled={status === "applying"}
        />
        <PersonaFields
          value={persona}
          onChange={setLocalPersona}
          disabled={status === "applying"}
        />
      </div>
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
 * Side-panel persona editor (PERS-02..PERS-05). Two modes:
 * - Controlled (setup path): pass `value` + `onChange` → renders the form against
 *   lifted state with NO Apply button and NO room context (safe outside the room).
 * - Uncontrolled (live/drawer path): omit props → holds its own state + Apply RPC.
 */
export default function PersonaPanel({
  value,
  onChange,
  onApplyStart,
  onApplied,
}: {
  value?: Persona;
  onChange?: (p: Persona) => void;
  onApplyStart?: () => number;
  onApplied?: (p: Persona, version: number) => void;
}) {
  if (onChange) {
    return <PersonaFields value={value ?? DEFAULT_PERSONA} onChange={onChange} />;
  }
  return (
    <PersonaPanelLive
      initialPersona={value ?? DEFAULT_PERSONA}
      onApplyStart={onApplyStart}
      onApplied={onApplied}
    />
  );
}
