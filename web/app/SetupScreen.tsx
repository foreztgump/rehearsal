"use client";

import { useState } from "react";

import InterviewPanel, { InterviewFields } from "./InterviewPanel";
import KbPanel from "./KbPanel";
import MicPicker from "./MicPicker";
import ModelPanel from "./ModelPanel";
import { PersonaFields } from "./PersonaPanel";
import SegmentedToggle from "./SegmentedToggle";
import ThemeDots from "./ThemeDots";
import type { SessionConfig } from "./VoiceRoom";

// UI-SPEC Copywriting table — verbatim copy slots.
const TAGLINE = "Set up your session, then start talking.";
const HEADPHONES_TIP =
  "Tip: use headphones for the cleanest experience — they stop the agent from hearing (and interrupting) itself.";
const CONNECT_ERROR =
  "Couldn't reach the session server. Check the stack is running, then try again.";

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
 * two-column field grid, a sliding segmented Avatar toggle, the dashed KB
 * dropzone, and a collapsed "Customize" disclosure (theme picker + persona +
 * interview), capped by the gradient Start CTA. The CTA is NEVER disabled by
 * missing choices — defaults pre-fill every group.
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
  const [customizeOpen, setCustomizeOpen] = useState(false);

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
            <div className="logo" aria-hidden="true">A</div>
            <h1 style={{ margin: 0, fontSize: "27px", fontWeight: 800, letterSpacing: "-0.02em" }}>
              Adept
            </h1>
          </div>
          <ThemeDots />
        </div>
        <p className="card-sub" style={{ margin: "11px 0 28px" }}>{TAGLINE}</p>

        <div className="grid-2">
          {/* Always-visible essentials: model, microphone, avatar, knowledge base. */}
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

          <InterviewFields
            value={config.mode}
            onChange={(mode) => onChange({ ...config, mode })}
          />

          <KbPanel
            files={config.kbFiles}
            onFilesChange={(kbFiles) => onChange({ ...config, kbFiles })}
            className="full"
          />

          {/* Customize disclosure: theme + advanced persona, collapsed by default
              with a summary line of the current defaults. */}
          <div className="disclosure">
            <button
              type="button"
              className="disclosure-summary"
              aria-expanded={customizeOpen}
              onClick={() => setCustomizeOpen((o) => !o)}
            >
              <span>
                {customizeOpen
                  ? "Customize — persona"
                  : `Customize — ${config.persona.display_name} · ${config.persona.difficulty}`}
              </span>
              <span className="chev" aria-hidden="true">▾</span>
            </button>

            <div
              className="transition-disclosure"
              style={{ display: "grid", gridTemplateRows: customizeOpen ? "1fr" : "0fr" }}
            >
              <div style={{ overflow: "hidden" }}>
                <div style={{ paddingTop: customizeOpen ? "18px" : 0 }}>
                  <div className="grid-2">
                    <PersonaFields
                      value={config.persona}
                      onChange={(persona) => onChange({ ...config, persona })}
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>

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
              {CONNECT_ERROR}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
