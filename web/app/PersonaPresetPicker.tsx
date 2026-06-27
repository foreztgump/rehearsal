"use client";

import { PERSONA_PRESETS, type PersonaPreset } from "./personaPresets";

// Setup-screen persona chooser. Selecting a preset pre-fills the (still editable)
// persona fields below it; it never disables the CTA. Presentational — the parent
// owns state via onSelect.
export default function PersonaPresetPicker({
  activeDisplayName,
  onSelect,
}: {
  activeDisplayName: string;
  onSelect: (preset: PersonaPreset) => void;
}) {
  return (
    <div className="field full">
      <label className="field-label">Persona preset</label>
      <div
        className="seg-wrap"
        role="radiogroup"
        aria-label="Persona preset"
        style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}
      >
        {PERSONA_PRESETS.map((preset) => {
          const active = preset.persona.display_name === activeDisplayName;
          return (
            <button
              key={preset.id}
              type="button"
              role="radio"
              aria-checked={active}
              title={preset.blurb}
              className="btn-ghost"
              // Active state via the theme accent (there is no .btn-ghost.on rule in
              // globals.css; an inline accent border is the smallest correct indicator).
              style={active ? { borderColor: "var(--accent)", color: "var(--text)" } : undefined}
              onClick={() => onSelect(preset)}
            >
              {preset.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
