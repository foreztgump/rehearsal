"use client";

import { InterviewFields } from "./InterviewPanel";
import KbPanel from "./KbPanel";
import MicPicker from "./MicPicker";
import ModelPanel from "./ModelPanel";
import { PersonaFields, SavedPersonaControls } from "./PersonaPanel";
import PersonaPresetPicker from "./PersonaPresetPicker";
import SegmentedToggle from "./SegmentedToggle";
import ThemeDots from "./ThemeDots";
import { EXPRESSIVE_AVAILABLE, VOICE_ENGINE_OPTIONS } from "./voiceEngine";
import { AVATAR_CATALOG } from "./avatarConfig";
import type { SessionConfig } from "./VoiceRoom";

// UI-SPEC Copywriting table — verbatim copy slots.
const TAGLINE = "Local first fully private voice practice with expert personas.";
const HEADPHONES_TIP =
  "Tip: use headphones for the cleanest experience — they stop the agent from hearing (and interrupting) itself.";

const AVATAR_OPTIONS = [
  { label: "Voice only", value: "voice" },
  { label: "Avatar", value: "avatar" },
] as const;



/**
 * Landing / setup screen (Screen A, D-01/D-02). A single centered card holding
 * EVERY session choice in plain React state BEFORE any LiveKit connection — NO
 * room hooks here (renders outside <LiveKitRoom>). The VoiceRoom shell owns the
 * config state and the Start gesture; this component is presentational, writing
 * edits through `onChange` and invoking `onStart` on the single CTA click.
 *
 * Visual contract: the design-mockups/v4 unified card — logo + wordmark, a
 * scenario-first two-column field grid, primary persona controls, a sliding
 * segmented Avatar toggle, the dashed KB dropzone, and the gradient Start CTA.
 * The CTA is NEVER disabled by missing choices — defaults pre-fill every group.
 */
export default function SetupScreen({
  config,
  onChange,
  onStart,
  connecting = false,
  error,
}: {
  config: SessionConfig;
  onChange: (c: SessionConfig) => void;
  onStart: () => void;
  connecting?: boolean;
  error?: string | null;
}) {
  function updatePersona(persona: SessionConfig["persona"]) {
    onChange({ ...config, persona });
  }

  function updateMode(mode: SessionConfig["mode"]) {
    onChange({ ...config, mode });
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: "40px 18px",
        textAlign: "left",
      }}
    >
      <div
        className="screen-enter surface"
        style={{ width: "100%", maxWidth: "760px", borderRadius: "var(--r-card)", padding: "38px" }}
      >
        {/* Logo + wordmark + always-visible theme switcher. */}
        <div className="card-head" style={{ justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "14px" }}>
            <div className="logo" aria-hidden="true">R</div>
            <h1 style={{ margin: 0, fontSize: "27px", fontWeight: 800, letterSpacing: "-0.02em" }}>
              Rehearsal
            </h1>
          </div>
          <ThemeDots />
        </div>
        <p className="card-sub" style={{ margin: "11px 0 28px" }}>{TAGLINE}</p>

        <div className="grid-2">
          <InterviewFields
            value={config.mode}
            onChange={updateMode}
            personaDisplayName={config.persona.display_name}
          />

          <PersonaPresetPicker
            activeDisplayName={config.persona.display_name}
            onSelect={(preset) => updatePersona(preset.persona)}
          />

          <SavedPersonaControls value={config.persona} onLoad={updatePersona} />

          <PersonaFields
            value={config.persona}
            onChange={updatePersona}
            expressive={EXPRESSIVE_AVAILABLE && config.expressiveVoice}
          />

          <ModelPanel value={config.model} onChange={(model) => onChange({ ...config, model })} />

          <MicPicker
            value={config.micDeviceId}
            onChange={(micDeviceId) => onChange({ ...config, micDeviceId })}
          />

          <div className="field">
            <label className="field-label">Avatar</label>
            <SegmentedToggle
              ariaLabel="Voice only / Avatar"
              options={AVATAR_OPTIONS}
              value={config.avatarOn ? "avatar" : "voice"}
              onChange={(v) => onChange({ ...config, avatarOn: v === "avatar" })}
            />
          </div>

          {/* Avatar face picker — only when Avatar is on. "Auto" (empty value) keeps
              the persona-matched face; any other choice loads that catalog GLB. */}
          {config.avatarOn && (
            <div className="field">
              <label className="field-label" htmlFor="avatar-face-select">
                Avatar face
              </label>
              <select
                id="avatar-face-select"
                className="control"
                value={config.selectedAvatarId ?? ""}
                onChange={(e) =>
                  onChange({ ...config, selectedAvatarId: e.target.value || undefined })
                }
              >
                <option value="">Auto (match persona)</option>
                {AVATAR_CATALOG.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.label}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Voice engine — only rendered when the expressive engine was installed
              (else the flag is baked "0" and this whole field is hidden, so users
              never see a toggle that routes to a service that isn't running). */}
          {EXPRESSIVE_AVAILABLE && (
            <div className="field">
              <label className="field-label">Voice (Chatterbox is more emotional, slightly slower)</label>
              <SegmentedToggle
                ariaLabel="Kokoro (fast) / Chatterbox (expressive) voice"
                options={VOICE_ENGINE_OPTIONS}
                value={config.expressiveVoice ? "chatterbox" : "kokoro"}
                onChange={(v) => onChange({ ...config, expressiveVoice: v === "chatterbox" })}
              />
            </div>
          )}

          <KbPanel
            files={config.kbFiles}
            onFilesChange={(kbFiles) => onChange({ ...config, kbFiles })}
            className="full"
          />

          {/* Primary CTA — gradient, never disabled by missing choices. */}
          <button
            type="button"
            className="btn-primary"
            style={{ gridColumn: "1 / -1", marginTop: "6px" }}
            onClick={onStart}
            disabled={connecting}
          >
            {connecting ? "Connecting…" : "Start session"}
          </button>

          {/* Headphones tip. */}
          <p
            style={{
              gridColumn: "1 / -1",
              textAlign: "center",
              margin: 0,
              fontSize: "12.5px",
              fontWeight: 500,
              color: "var(--text-muted)",
            }}
          >
            {HEADPHONES_TIP}
          </p>

          {error && (
            <p style={{ gridColumn: "1 / -1", color: "var(--destructive)", margin: 0, textAlign: "center" }}>
              {error}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
