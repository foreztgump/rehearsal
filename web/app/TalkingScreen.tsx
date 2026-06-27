"use client";

import { ReactNode, useState } from "react";

import AgentStatePill from "./AgentStatePill";
import SettingsDrawer from "./SettingsDrawer";
import Transcript from "./Transcript";
import { font, palette, radius, space } from "./ui/tokens";

/**
 * In-room talking screen (Screen B). Rendered INSIDE <LiveKitRoom> as a full-height
 * flex column: a top bar (agent-state pill + Voice-only/Avatar segmented toggle +
 * a Settings button), an optional avatar stage (only when `avatarOn`; the avatar
 * element itself is mounted in the shell to keep the dynamic-import contract there),
 * the Transcript as the hero flex-1 column, and the reversible SettingsDrawer
 * (closed by default). The config panels live in the drawer, not the always-visible
 * layout, so the conversation is the hero.
 *
 * Opening Settings overlays the drawer WITHOUT unmounting <LiveKitRoom> — the room,
 * transcript, and avatar persist. Only a confirmed Leave (onLeave) returns to setup.
 */
export default function TalkingScreen({
  avatarOn,
  onToggleAvatar,
  onLeave,
  avatar,
}: {
  avatarOn: boolean;
  onToggleAvatar: (on: boolean) => void;
  onLeave: () => void;
  // The avatar stage element (mounted in the shell to preserve the dynamic-import
  // ssr:false contract); rendered here in the 360px region only when avatarOn.
  avatar?: ReactNode;
}) {
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <div
      className="screen-enter"
      style={{
        minHeight: "100vh",
        width: "100%",
        display: "flex",
        flexDirection: "column",
        gap: space.md,
        padding: space.lg,
      }}
    >
      {/* Top bar: state pill + Voice-only/Avatar toggle + Settings. */}
      <div style={{ display: "flex", gap: space.md, alignItems: "center" }}>
        <AgentStatePill />

        {/* Default-OFF "Voice only / Avatar" toggle (AVTR-01). Audio always plays
            via <RoomAudioRenderer/> in the shell regardless of this toggle (AVTR-02). */}
        <div
          role="group"
          aria-label="Voice only / Avatar"
          style={{
            display: "inline-flex",
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
              onClick={() => onToggleAvatar(on)}
              style={{
                padding: `${space.xs} ${space.md}`,
                border: "none",
                cursor: "pointer",
                fontWeight: font.weight.semibold,
                background: avatarOn === on ? palette.accent : "transparent",
                color: avatarOn === on ? palette.bg : palette.textMuted,
              }}
            >
              {label}
            </button>
          ))}
        </div>

        <button
          type="button"
          className="transition-hover"
          onClick={() => setSettingsOpen(true)}
          style={{
            marginLeft: "auto",
            padding: `${space.xs} ${space.md}`,
            borderRadius: radius.control,
            border: `1px solid ${palette.border}`,
            background: "transparent",
            color: palette.text,
            fontWeight: font.weight.semibold,
            cursor: "pointer",
          }}
        >
          Settings
        </button>
      </div>

      {/* Optional avatar stage (360px region; mount contract owned by the shell). */}
      {avatarOn && avatar && (
        <div style={{ width: "100%", height: "360px" }}>{avatar}</div>
      )}

      {/* Hero transcript column — fills remaining height so its own scroll works. */}
      <Transcript />

      <SettingsDrawer
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onLeave={onLeave}
      />
    </div>
  );
}
