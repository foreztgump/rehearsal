"use client";

import { useRoomContext, useVoiceAssistant } from "@livekit/components-react";
import { useEffect, useMemo, useRef, useState } from "react";

import InterviewPanel from "./InterviewPanel";
import KbPanel from "./KbPanel";
import ModelPanel from "./ModelPanel";
import PersonaPanel from "./PersonaPanel";
import ThemeDots from "./ThemeDots";
import { normalizeTranscriptSegments } from "./transcriptSegments";
import { downloadTranscript, formatTranscript, TranscriptEntry } from "./transcriptExport";
import { font, palette, radius, space } from "./ui/tokens";
import { useTranscriptionSegments } from "./useTranscriptionSegments";
import type { LiveConfigField, SessionConfig } from "./VoiceRoom";

// UI-SPEC Copywriting table — verbatim destructive-confirm copy (SESS-03 End is the
// two-step inline confirm; SESS-01 New / SESS-02 Reset use a native confirm).
// Exported so the top-bar End (TalkingScreen) reuses the exact same copy (F33).
export const END_CONFIRM =
  "End this conversation and return to setup? Your transcript will clear.";
const NEW_CONFIRM = "Start a fresh session? The current conversation clears.";
const RESET_CONFIRM = "Clear the conversation but keep your setup?";
const RESET_FAILED_MESSAGE =
  "Couldn't clear the conversation — the agent still has it. Please try again.";
// The agent's RPC handlers ack success with this exact string; anything else is a
// rejection (LiveKit resolves performRpc with the returned string, it does not throw).
const RPC_APPLIED = "applied";

const TRANSCRIPT_TXT_FILENAME = "rehearsal-transcript.txt";
const TRANSCRIPT_MD_FILENAME = "rehearsal-transcript.md";

// The focusable controls a focus trap cycles through. Kept broad so every native
// control inside the hosted live panels (inputs/selects/textareas/buttons) is
// reachable by Tab without leaking focus to the page behind the overlay.
const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Reversible in-room settings overlay (success criterion 3, UI-SPEC navigation
 * pattern (a)). Rendered INSIDE <LiveKitRoom> so opening/closing it NEVER unmounts
 * the room — the agent, transcript, and avatar all persist. It hosts the existing
 * Persona/Interview/Model/KB panels in their UNCHANGED uncontrolled live-RPC mode
 * (they have room context; Apply tweaks the running agent).
 *
 * A clearly-destructive "End session" affordance (#f85149) opens a confirm; only on
 * confirm does it call `onEnd` (disconnect + clear held state in the shell). It also
 * hosts New/Reset session actions and transcript export. Escape closes the drawer;
 * focus is trapped while open; every control shows the #58a6ff focus ring.
 */
export default function SettingsDrawer({
  open,
  onClose,
  onEnd,
  onNew,
  onReset,
  resetMarker,
  config,
  sessionEpoch,
  onBeginConfigApply,
  onInvalidateConfigApplies,
  onConfigChange,
}: {
  open: boolean;
  onClose: () => void;
  // Session lifecycle (SESS-01/02/03) threaded from the shell.
  onEnd: () => void;
  onNew: () => void;
  onReset: () => void;
  // Wall-clock of the last Reset (0 = never). Export excludes pre-reset turns so a
  // "cleared" session never leaks back out (matches the on-screen Transcript).
  resetMarker: number;
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
  const panelRef = useRef<HTMLDivElement>(null);
  const wasOpenRef = useRef(false);
  const invalidateConfigAppliesRef = useRef(onInvalidateConfigApplies);
  const [confirmLeave, setConfirmLeave] = useState(false);

  useEffect(() => {
    invalidateConfigAppliesRef.current = onInvalidateConfigApplies;
  }, [onInvalidateConfigApplies]);

  // Live-room hooks (the drawer always renders inside <LiveKitRoom>). Called before
  // the `if (!open)` early return so hook order stays stable across open/close.
  const room = useRoomContext();
  const { agent } = useVoiceAssistant();
  const transcriptions = useTranscriptionSegments();
  const transcriptLines = useMemo(() => normalizeTranscriptSegments(transcriptions), [transcriptions]);
  // First-finalize wall-clock per segment id — backs export timestamps reliably even
  // while the drawer is closed (this component stays mounted, only its tree hides).
  const firstFinalAtRef = useRef<Map<string, number>>(new Map());
  useEffect(() => {
    for (const line of transcriptLines) {
      if (line.isFinal && !firstFinalAtRef.current.has(line.id)) {
        firstFinalAtRef.current.set(line.id, Date.now());
      }
    }
  }, [transcriptLines]);

  function buildEntries(): TranscriptEntry[] {
    const entries: TranscriptEntry[] = [];
    for (const line of transcriptLines) {
      if (!line.isFinal) continue;
      const at = firstFinalAtRef.current.get(line.id) ?? Date.now();
      if (at < resetMarker) continue; // a turn the user cleared on Reset — never export it
      entries.push({ speaker: line.speaker, text: line.text, at });
    }
    return entries;
  }

  function exportTranscript(format: "txt" | "md"): void {
    const filename = format === "md" ? TRANSCRIPT_MD_FILENAME : TRANSCRIPT_TXT_FILENAME;
    downloadTranscript(formatTranscript(buildEntries(), format), filename);
  }

  // SESS-02 Reset: clear the agent's history in-place via the session.reset RPC, then
  // clear the transcript view (onReset bumps the shell's reset marker). The view is
  // cleared ONLY when the agent confirms it cleared too — otherwise the UI would look
  // empty while the agent still holds (and could quote) the "cleared" conversation.
  async function resetSession(): Promise<void> {
    if (!window.confirm(RESET_CONFIRM)) return;
    const fallback = Array.from(room.remoteParticipants.values())[0];
    const agentIdentity = agent?.identity ?? fallback?.identity;
    if (!agentIdentity) {
      onReset(); // no agent holds context — clearing the local view can't diverge
      return;
    }
    try {
      const ack = await room.localParticipant.performRpc({
        destinationIdentity: agentIdentity,
        method: "session.reset",
        payload: JSON.stringify({}),
      });
      if (ack !== RPC_APPLIED) {
        window.alert(RESET_FAILED_MESSAGE); // agent kept its context — keep the view in sync
        return;
      }
    } catch {
      // boundary: agent gone / LiveKit disconnect — don't blank a view the agent may still back.
      window.alert(RESET_FAILED_MESSAGE);
      return;
    }
    onReset();
  }

  function newSession(): void {
    if (window.confirm(NEW_CONFIRM)) onNew();
  }

  // Escape closes the drawer; Tab is trapped to the panel's focusable controls so
  // focus never escapes to the live room behind the overlay.
  useEffect(() => {
    if (!open) return;

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const root = panelRef.current;
      if (!root) return;
      const focusable = Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => el.offsetParent !== null,
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [open, onClose]);

  // Move focus into the drawer when it opens; reset the leave-confirm on close.
  useEffect(() => {
    if (!open) {
      wasOpenRef.current = false;
      setConfirmLeave(false);
      return;
    }
    if (!wasOpenRef.current) {
      wasOpenRef.current = true;
      invalidateConfigAppliesRef.current();
    }
    const root = panelRef.current;
    const firstFocusable = root?.querySelector<HTMLElement>(FOCUSABLE);
    firstFocusable?.focus();
  }, [open]);

  if (!open) return null;

  return (
    <div
      // Scrim + overlay. Clicking the scrim closes (a Cancel affordance); the panel
      // stops propagation so clicks inside it don't close.
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 50,
        display: "flex",
        justifyContent: "flex-end",
        background: "rgba(0,0,0,0.55)",
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="Session settings"
        className="screen-enter"
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "min(420px, 100%)",
          height: "100%",
          overflowY: "auto",
          background: palette.panel,
          borderLeft: `1px solid ${palette.border}`,
          padding: space.lg,
          display: "flex",
          flexDirection: "column",
          gap: space.lg,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <strong style={{ fontSize: font.size.heading, color: palette.text }}>Settings</strong>
          <button
            type="button"
            className="transition-hover"
            onClick={onClose}
            aria-label="Close settings"
            style={{
              padding: `${space.xs} ${space.sm}`,
              borderRadius: radius.control,
              border: `1px solid ${palette.border}`,
              background: "transparent",
              color: palette.text,
              fontWeight: font.weight.semibold,
              cursor: "pointer",
            }}
          >
            Close
          </button>
        </div>

        {/* Theme switcher — same compact dots as the setup header, switchable mid-session. */}
        <div className="drawer-section">
          <h4>Theme</h4>
          <ThemeDots />
        </div>

        {/* Hosted live-tweak panels keep their existing Apply/RPC controls, seeded
            from the running session config instead of panel-local defaults. */}
        <PersonaPanel
          value={config.persona}
          onApplyStart={() => onBeginConfigApply("persona")}
          onApplied={(persona, version) =>
            onConfigChange(sessionEpoch, "persona", version, (current) => ({
              ...current,
              persona,
            }))
          }
        />
        <InterviewPanel
          value={config.mode}
          personaDisplayName={config.persona.display_name}
          onApplyStart={() => onBeginConfigApply("mode")}
          onApplied={(mode, version) =>
            onConfigChange(sessionEpoch, "mode", version, (current) => ({
              ...current,
              mode,
            }))
          }
        />
        <ModelPanel
          value={config.model}
          onApplyStart={() => onBeginConfigApply("model")}
          onApplied={(model, version) =>
            onConfigChange(sessionEpoch, "model", version, (current) => ({
              ...current,
              model,
            }))
          }
        />
        <KbPanel />

        {/* SESS-04 transcript export — pure client-side Blob download, no server
            round-trip (PERF-03 local-first). */}
        <div className="drawer-section">
          <h4>Transcript</h4>
          <div style={{ display: "flex", gap: space.sm }}>
            <button type="button" className="btn-ghost" onClick={() => exportTranscript("txt")}>
              Export .txt
            </button>
            <button type="button" className="btn-ghost" onClick={() => exportTranscript("md")}>
              Export .md
            </button>
          </div>
        </div>

        {/* SESS-01/02 Session actions: New (fresh room, keep setup) and Reset (clear
            history + transcript, same room). Both use a native confirm. */}
        <div className="drawer-section">
          <h4>Session</h4>
          <div style={{ display: "flex", gap: space.sm }}>
            <button type="button" className="btn-ghost" onClick={newSession}>
              New session
            </button>
            <button type="button" className="btn-ghost" onClick={() => void resetSession()}>
              Reset
            </button>
          </div>
        </div>

        {/* SESS-03 destructive End session affordance (two-step inline confirm). On
            confirm -> onEnd disconnects + clears all held state in the shell. */}
        <div style={{ display: "flex", flexDirection: "column", gap: space.sm, marginTop: "auto" }}>
          {confirmLeave ? (
            <div style={{ display: "flex", flexDirection: "column", gap: space.sm }}>
              <p style={{ margin: 0, color: palette.textBody, fontSize: font.size.label }}>
                {END_CONFIRM}
              </p>
              <div style={{ display: "flex", gap: space.sm }}>
                <button
                  type="button"
                  className="transition-hover"
                  onClick={onEnd}
                  style={{
                    flex: 1,
                    padding: `${space.sm} ${space.md}`,
                    borderRadius: radius.control,
                    border: "none",
                    background: palette.destructive,
                    color: palette.bg,
                    fontWeight: font.weight.semibold,
                    cursor: "pointer",
                  }}
                >
                  End session
                </button>
                <button
                  type="button"
                  className="transition-hover"
                  onClick={() => setConfirmLeave(false)}
                  style={{
                    flex: 1,
                    padding: `${space.sm} ${space.md}`,
                    borderRadius: radius.control,
                    border: `1px solid ${palette.border}`,
                    background: "transparent",
                    color: palette.text,
                    fontWeight: font.weight.semibold,
                    cursor: "pointer",
                  }}
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button
              type="button"
              className="transition-hover"
              onClick={() => setConfirmLeave(true)}
              style={{
                alignSelf: "flex-start",
                padding: `${space.sm} ${space.md}`,
                borderRadius: radius.control,
                border: `1px solid ${palette.destructive}`,
                background: "transparent",
                color: palette.destructive,
                fontWeight: font.weight.semibold,
                cursor: "pointer",
              }}
            >
              End session
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
