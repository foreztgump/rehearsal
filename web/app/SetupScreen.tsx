"use client";

import { useState } from "react";

import InterviewPanel from "./InterviewPanel";
import KbPanel from "./KbPanel";
import MicPicker from "./MicPicker";
import ModelPanel from "./ModelPanel";
import PersonaPanel from "./PersonaPanel";
import type { SessionConfig } from "./VoiceRoom";
import { font, palette, panelStyle, radius, space } from "./ui/tokens";

// UI-SPEC Copywriting table — verbatim copy slots.
const TAGLINE = "Set up your session, then start talking.";
const HEADPHONES_TIP =
  "Tip: use headphones for the cleanest experience — they stop the agent from hearing (and interrupting) itself.";
const CONNECT_ERROR =
  "Couldn't reach the session server. Check the stack is running, then try again.";

/**
 * Landing / setup screen (Screen A, D-01/D-02). A single centered card holding
 * EVERY session choice in plain React state BEFORE any LiveKit connection — NO
 * room hooks here (renders outside <LiveKitRoom>). The VoiceRoom shell owns the
 * config state and the Start gesture; this component is presentational, writing
 * edits through `onChange` and invoking `onStart` on the single CTA click.
 *
 * Advanced persona/interview fields sit behind a collapsed "Customize"
 * disclosure so the default path is one glance → Start (D-02). The CTA is NEVER
 * disabled by missing choices — defaults pre-fill every group.
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
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        padding: space.lg,
      }}
    >
      <div
        className="screen-enter"
        style={{
          width: "100%",
          maxWidth: "720px",
          display: "flex",
          flexDirection: "column",
          gap: space.lg,
          padding: space.xl,
          background: palette.panel,
          border: `1px solid ${palette.border}`,
          borderRadius: radius.card,
        }}
      >
        {/* Wordmark + tagline */}
        <div style={{ display: "flex", flexDirection: "column", gap: space.xs }}>
          <strong style={{ fontSize: font.size.display, color: palette.text }}>Adept</strong>
          <span style={{ color: palette.textMuted, fontSize: font.size.body }}>{TAGLINE}</span>
        </div>

        {/* Always-visible essentials: model, microphone, avatar, knowledge base. */}
        <ModelPanel value={config.model} onChange={(model) => onChange({ ...config, model })} />

        <div style={panelStyle}>
          <strong style={{ fontSize: font.size.heading }}>Microphone</strong>
          <MicPicker
            value={config.micDeviceId}
            onChange={(micDeviceId) => onChange({ ...config, micDeviceId })}
          />
        </div>

        {/* Avatar segmented toggle (Voice only / Avatar) — active segment accent. */}
        <div style={panelStyle}>
          <strong style={{ fontSize: font.size.heading }}>Avatar</strong>
          <div
            role="group"
            aria-label="Voice only / Avatar"
            style={{
              display: "inline-flex",
              alignSelf: "flex-start",
              borderRadius: radius.pill,
              overflow: "hidden",
              border: `1px solid ${palette.border}`,
              fontSize: font.size.label,
            }}
          >
            {([
              ["Voice only", false],
              ["Avatar", true],
            ] as const).map(([label, on]) => (
              <button
                key={label}
                type="button"
                className="transition-segment"
                onClick={() => onChange({ ...config, avatarOn: on })}
                style={{
                  padding: `${space.xs} ${space.md}`,
                  border: "none",
                  cursor: "pointer",
                  fontWeight: font.weight.semibold,
                  background: config.avatarOn === on ? palette.accent : "transparent",
                  color: config.avatarOn === on ? palette.bg : palette.textMuted,
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <KbPanel
          files={config.kbFiles}
          onFilesChange={(kbFiles) => onChange({ ...config, kbFiles })}
        />

        {/* Customize disclosure: advanced persona + interview fields, collapsed
            by default with a summary line of the current defaults. */}
        <div style={{ display: "flex", flexDirection: "column", gap: space.sm }}>
          <button
            type="button"
            className="transition-hover"
            aria-expanded={customizeOpen}
            onClick={() => setCustomizeOpen((o) => !o)}
            style={{
              alignSelf: "flex-start",
              padding: `${space.xs} ${space.sm}`,
              borderRadius: radius.control,
              border: `1px solid ${palette.border}`,
              background: "transparent",
              color: palette.text,
              fontWeight: font.weight.semibold,
              cursor: "pointer",
            }}
          >
            {customizeOpen ? "Hide customization" : "Customize"}
          </button>

          {!customizeOpen && (
            <span style={{ color: palette.textMuted, fontSize: font.size.label }}>
              {config.persona.display_name} · {config.persona.difficulty} ·{" "}
              {config.mode.mode === "interview" ? "Interview" : "Learn"} mode
            </span>
          )}

          <div
            className="transition-disclosure"
            style={{ display: "grid", gridTemplateRows: customizeOpen ? "1fr" : "0fr" }}
          >
            <div style={{ overflow: "hidden", display: "flex", flexDirection: "column", gap: space.lg }}>
              <PersonaPanel
                value={config.persona}
                onChange={(persona) => onChange({ ...config, persona })}
              />
              <InterviewPanel
                value={config.mode}
                onChange={(mode) => onChange({ ...config, mode })}
              />
            </div>
          </div>
        </div>

        {/* Headphones tip (moved here from the old Start button). */}
        <p style={{ color: palette.textMuted, margin: 0, fontSize: font.size.label }}>
          {HEADPHONES_TIP}
        </p>

        {/* Primary CTA — green, 44px target, never disabled by missing choices. */}
        <button
          type="button"
          className="transition-hover"
          onClick={onStart}
          disabled={connecting}
          style={{
            minHeight: "44px",
            padding: `${space.sm} ${space.lg}`,
            borderRadius: radius.control,
            border: "none",
            background: palette.action,
            color: palette.bg,
            fontWeight: font.weight.semibold,
            fontSize: font.size.body,
            cursor: connecting ? "progress" : "pointer",
          }}
        >
          {connecting ? "Connecting…" : "Start session"}
        </button>

        {error && (
          <p style={{ color: palette.destructive, margin: 0 }}>{CONNECT_ERROR}</p>
        )}
      </div>
    </div>
  );
}
