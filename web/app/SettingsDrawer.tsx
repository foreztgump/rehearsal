"use client";

import { useEffect, useRef, useState } from "react";

import InterviewPanel from "./InterviewPanel";
import KbPanel from "./KbPanel";
import ModelPanel from "./ModelPanel";
import PersonaPanel from "./PersonaPanel";
import { font, palette, radius, space } from "./ui/tokens";

// UI-SPEC Copywriting table — verbatim destructive-confirm copy. Phase 13 builds
// the affordance + copy ONLY; the full clear-all teardown is Phase 14 — onLeave
// here just sets token=null in the shell (the single disconnect path).
const LEAVE_CONFIRM =
  "End this conversation and return to setup? Your transcript will clear.";

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
 * A clearly-destructive "Leave session" affordance (#f85149) opens a confirm; only
 * on confirm does it call `onLeave` (token=null in the shell). Escape closes the
 * drawer; focus is trapped while open; every control shows the #58a6ff focus ring.
 */
export default function SettingsDrawer({
  open,
  onClose,
  onLeave,
}: {
  open: boolean;
  onClose: () => void;
  onLeave: () => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [confirmLeave, setConfirmLeave] = useState(false);

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
      setConfirmLeave(false);
      return;
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

        {/* Hosted live-tweak panels — UNCONTROLLED mode (no props) so each keeps its
            existing performRpc/sendFile apply logic against the running agent. */}
        <PersonaPanel />
        <InterviewPanel />
        <ModelPanel />
        <KbPanel />

        {/* Destructive Leave session affordance (copy + confirm only; teardown is
            Phase 14). On confirm -> onLeave sets token=null in the shell. */}
        <div style={{ display: "flex", flexDirection: "column", gap: space.sm, marginTop: "auto" }}>
          {confirmLeave ? (
            <div style={{ display: "flex", flexDirection: "column", gap: space.sm }}>
              <p style={{ margin: 0, color: palette.textBody, fontSize: font.size.label }}>
                {LEAVE_CONFIRM}
              </p>
              <div style={{ display: "flex", gap: space.sm }}>
                <button
                  type="button"
                  className="transition-hover"
                  onClick={onLeave}
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
                  Leave session
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
              Leave session
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
