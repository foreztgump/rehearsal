"use client";

import { useRoomContext, useVoiceAssistant } from "@livekit/components-react";
import { useEffect, useRef, useState } from "react";

import { DEFAULT_INTERVIEW } from "./InterviewPanel";
import { KB_UPLOAD_TOPIC } from "./KbPanel";
import { DEFAULT_MODEL } from "./ModelPanel";
import { DEFAULT_PERSONA } from "./PersonaPanel";
import type { SessionConfig } from "./VoiceRoom";
import { palette } from "./ui/tokens";

// Stable JSON equality for the default-skip optimization. The held value and the
// agent default share the same key order (both built from the panel constants),
// so a stringify compare is sufficient and avoids a needless first-turn re-prefill.
function sameAsDefault(value: unknown, fallback: unknown): boolean {
  return JSON.stringify(value) === JSON.stringify(fallback);
}

/**
 * Once-only post-connect apply effect (KEY TENSION resolution). Rendered INSIDE
 * <LiveKitRoom>, it watches for the agent participant to join (readiness ==
 * `agent.identity` defined — the agent only registers its persona/mode/model RPC
 * methods + KB byte-stream handler AFTER session.start()), then fires the held
 * SetupScreen config EXACTLY ONCE in order: persona.update → mode.update →
 * model.update → queued KB sendFile. A useRef once-guard makes it React 19
 * Strict-Mode double-invoke safe.
 *
 * No RPC method/payload key or the kb.upload topic changes here — only WHEN they
 * fire moves from a per-panel Apply click to this gated effect. Each await is
 * wrapped so a single failure surfaces a non-blocking note and never hard-fails
 * or blocks the talking UI.
 */
export default function ApplySetupOnConnect({ config }: { config: SessionConfig }) {
  const room = useRoomContext();
  const { agent } = useVoiceAssistant();
  const applied = useRef(false);
  const [note, setNote] = useState("Connecting…");

  useEffect(() => {
    // Resolve the agent identity exactly as the panels do. Until it is defined
    // the agent hasn't registered its RPC handlers — show a non-fatal note and
    // retry on the next `agent` change (the effect re-runs on agent?.identity).
    const fallback = Array.from(room.remoteParticipants.values())[0];
    const agentIdentity = agent?.identity ?? fallback?.identity;
    if (!agentIdentity) {
      setNote("Still connecting the agent…");
      return;
    }
    if (applied.current) return;
    applied.current = true;

    (async () => {
      setNote("Applying your setup…");

      // persona.update — skip when unchanged from the agent default (default-skip).
      if (!sameAsDefault(config.persona, DEFAULT_PERSONA)) {
        try {
          await room.localParticipant.performRpc({
            destinationIdentity: agentIdentity,
            method: "persona.update",
            payload: JSON.stringify(config.persona),
          });
        } catch {
          setNote("Couldn't apply persona — you can re-apply from settings.");
        }
      }

      // mode.update {mode, role_key} — skip when unchanged from the default.
      if (!sameAsDefault(config.mode, DEFAULT_INTERVIEW)) {
        try {
          await room.localParticipant.performRpc({
            destinationIdentity: agentIdentity,
            method: "mode.update",
            payload: JSON.stringify(config.mode),
          });
        } catch {
          setNote("Couldn't apply interview mode — you can re-apply from settings.");
        }
      }

      // model.update {choice} — skip when unchanged from the default (Fast).
      if (!sameAsDefault(config.model, DEFAULT_MODEL)) {
        try {
          await room.localParticipant.performRpc({
            destinationIdentity: agentIdentity,
            method: "model.update",
            payload: JSON.stringify({ choice: config.model }),
          });
        } catch {
          setNote("Couldn't apply model — you can re-apply from settings.");
        }
      }

      // Queued KB uploads — each picked file as its own byte stream on the
      // existing topic. Fires only if files were queued on the setup screen.
      for (const file of config.kbFiles) {
        try {
          await room.localParticipant.sendFile(file, { topic: KB_UPLOAD_TOPIC });
        } catch {
          setNote(`Couldn't upload "${file.name}" — re-add it from settings.`);
        }
      }

      setNote("");
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agent?.identity]);

  if (!note) return null;
  return (
    <p className="transition-status" style={{ color: palette.textMuted, margin: 0 }}>
      {note}
    </p>
  );
}
