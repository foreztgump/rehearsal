"use client";

import { useState } from "react";
import type { ReactNode } from "react";

import AgentStatePill from "./AgentStatePill";
import SegmentedToggle from "./SegmentedToggle";
import SettingsDrawer from "./SettingsDrawer";
import SttDebugWindow from "./SttDebugWindow";
import Transcript from "./Transcript";
import Visualizer from "./Visualizer";
import type { LiveConfigField, SessionConfig } from "./VoiceRoom";
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
 * transcript, and avatar persist. Only a confirmed End (onEnd) returns to setup.
 */
export default function TalkingScreen({
  avatarOn,
  onToggleAvatar,
  onEnd,
  onNew,
  onReset,
  resetMarker,
  avatarView,
  onToggleAvatarView,
  avatar,
  agentName,
  config,
  sessionEpoch,
  onBeginConfigApply,
  onInvalidateConfigApplies,
  onConfigChange,
}: {
  avatarOn: boolean;
  onToggleAvatar: (on: boolean) => void;
  // Session lifecycle (SESS-01/02/03): End returns to setup clearing state, New
  // restarts keeping setup, Reset clears history/transcript in the same room.
  onEnd: () => void;
  onNew: () => void;
  onReset: () => void;
  // Wall-clock timestamp of the last Reset; the transcript hides turns finalized
  // before it (0 = nothing reset yet).
  resetMarker: number;
  // Avatar framing (upper ↔ full body) + its toggle, surfaced only in avatar mode.
  avatarView: "upper" | "full";
  onToggleAvatarView: () => void;
  // The avatar stage element (mounted in the shell to preserve the dynamic-import
  // ssr:false contract); rendered here in the stage only when avatarOn.
  avatar?: ReactNode;
  agentName: string;
  config: SessionConfig;
  sessionEpoch: number;
  onBeginConfigApply: (field: LiveConfigField) => number;
  onInvalidateConfigApplies: () => void;
  onConfigChange: (
    sessionEpoch: number,
    field: LiveConfigField,
    version: number,
    update: (current: SessionConfig) => SessionConfig,
  ) => void;
}) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  // Full-screen avatar: the avatar fills the stage and the transcript is hidden.
  const [avatarFullscreen, setAvatarFullscreen] = useState(false);
  const showAvatar = avatarOn && !!avatar;
  const avatarOnly = showAvatar && avatarFullscreen;

  return (
    <div
      className="screen-enter"
      style={{ height: "100dvh", width: "100%", display: "flex", flexDirection: "column", overflow: "hidden" }}
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
          <button type="button" className="btn-ghost danger" onClick={onEnd}>
            End
          </button>
        </div>
      </div>

      {/* Stage: visualizer/avatar hero (with who-name) + transcript. Avatar mode
          splits into two columns; voice mode stacks the orb over a centered
          transcript column. */}
      <div
        className="talk-main"
        data-avatar={showAvatar ? "true" : "false"}
        data-fullscreen={avatarOnly ? "true" : "false"}
      >
        {/* Hero: avatar stage OR the canvas orb visualizer. The visualizer carries
            no 3D deps, so the voice-only bundle stays clean. */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: "12px",
            minHeight: 0,
            minWidth: 0,
            overflow: "hidden",
          }}
        >
          {/* Bounded stage: flex:1 + minHeight:0 + overflow:hidden makes the avatar
              or orb scale to fit the cell on any viewport instead of overflowing. */}
          <div
            style={{
              flex: 1,
              minHeight: 0,
              width: "100%",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              overflow: "hidden",
            }}
          >
            {showAvatar ? (
              <div style={{ width: "100%", height: "100%" }}>{avatar}</div>
            ) : (
              <Visualizer />
            )}
          </div>
          <WhoName agentName={agentName} />
          {showAvatar && (
            <div style={{ display: "flex", gap: "8px" }}>
              <button
                type="button"
                className="btn-ghost"
                onClick={onToggleAvatarView}
                aria-pressed={avatarView === "full"}
                style={{ fontSize: "13px", padding: "5px 12px" }}
              >
                {avatarView === "upper" ? "Show full body" : "Show head & shoulders"}
              </button>
              <button
                type="button"
                className="btn-ghost"
                onClick={() => setAvatarFullscreen((on) => !on)}
                aria-pressed={avatarFullscreen}
                style={{ fontSize: "13px", padding: "5px 12px" }}
              >
                {avatarFullscreen ? "Show transcript" : "Full screen"}
              </button>
            </div>
          )}
        </div>

        {/* Transcript column — centered + width-capped in voice mode. Hidden when the
            avatar is full-screen. */}
        {!avatarOnly && (
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
            <Transcript resetAfter={resetMarker} />
          </div>
        )}
      </div>

      <SettingsDrawer
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onEnd={onEnd}
        onNew={onNew}
        onReset={onReset}
        resetMarker={resetMarker}
        config={config}
        sessionEpoch={sessionEpoch}
        onBeginConfigApply={onBeginConfigApply}
        onInvalidateConfigApplies={onInvalidateConfigApplies}
        onConfigChange={onConfigChange}
      />
      <SttDebugWindow />
    </div>
  );
}
