"use client";

import { ReactNode, useState } from "react";

import AgentStatePill from "./AgentStatePill";
import SegmentedToggle from "./SegmentedToggle";
import SettingsDrawer from "./SettingsDrawer";
import Transcript from "./Transcript";
import Visualizer from "./Visualizer";
import WhoName from "./WhoName";

const AVATAR_OPTIONS = [
  { label: "Voice only", value: "voice" },
  { label: "Avatar", value: "avatar" },
] as const;

/**
 * In-room talking screen (Screen B). Rendered INSIDE <LiveKitRoom> as a full-height
 * flex column matching the design-mockups/v4 talk view: a sticky blurred top bar
 * (agent-state pill + Voice-only/Avatar sliding toggle + ghost Settings/Leave),
 * then a stage split into the visualizer/avatar hero (with a live "who-name" status
 * line) and the Transcript. The reversible SettingsDrawer hosts the config panels.
 *
 * Opening Settings overlays the drawer WITHOUT unmounting <LiveKitRoom> — the room,
 * transcript, and avatar persist. Only a confirmed Leave (onLeave) returns to setup.
 */
export default function TalkingScreen({
  avatarOn,
  onToggleAvatar,
  onLeave,
  avatar,
  agentName,
}: {
  avatarOn: boolean;
  onToggleAvatar: (on: boolean) => void;
  onLeave: () => void;
  // The avatar stage element (mounted in the shell to preserve the dynamic-import
  // ssr:false contract); rendered here in the stage only when avatarOn.
  avatar?: ReactNode;
  agentName: string;
}) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const showAvatar = avatarOn && !!avatar;

  return (
    <div
      className="screen-enter"
      style={{ minHeight: "100vh", width: "100%", display: "flex", flexDirection: "column" }}
    >
      {/* Sticky blurred top bar. */}
      <div className="topbar">
        <AgentStatePill />
        <div style={{ marginLeft: "auto", display: "flex", gap: "9px", alignItems: "center" }}>
          <SegmentedToggle
            ariaLabel="Voice only / Avatar"
            options={AVATAR_OPTIONS}
            value={avatarOn ? "avatar" : "voice"}
            onChange={(v) => onToggleAvatar(v === "avatar")}
          />
          <button type="button" className="btn-ghost" onClick={() => setSettingsOpen(true)}>
            Settings
          </button>
          <button type="button" className="btn-ghost danger" onClick={onLeave}>
            Leave
          </button>
        </div>
      </div>

      {/* Stage: visualizer/avatar hero (with who-name) + transcript. Avatar mode
          splits into two columns; voice mode stacks the orb over a centered
          transcript column. */}
      <div
        style={{
          flex: 1,
          minHeight: 0,
          display: "grid",
          gap: "22px",
          padding: "18px 22px 26px",
          gridTemplateColumns: showAvatar ? "minmax(300px, 44%) 1fr" : "1fr",
          gridTemplateRows: showAvatar ? "1fr" : "auto 1fr",
          alignItems: showAvatar ? "stretch" : undefined,
        }}
      >
        {/* Hero: avatar stage OR the canvas orb visualizer. The visualizer carries
            no 3D deps, so the voice-only bundle stays clean. */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: "18px",
            minHeight: 0,
          }}
        >
          {showAvatar ? (
            <div style={{ width: "100%", height: "100%", minHeight: "320px" }}>{avatar}</div>
          ) : (
            <Visualizer />
          )}
          <WhoName agentName={agentName} />
        </div>

        {/* Transcript column — centered + width-capped in voice mode. */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            minHeight: 0,
            width: "100%",
            maxWidth: showAvatar ? undefined : "720px",
            margin: showAvatar ? undefined : "0 auto",
          }}
        >
          <Transcript />
        </div>
      </div>

      <SettingsDrawer
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onLeave={onLeave}
      />
    </div>
  );
}
