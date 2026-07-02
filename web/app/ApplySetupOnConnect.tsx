"use client";

import { useRoomContext, useVoiceAssistant } from "@livekit/components-react";
import { useEffect, useRef, useState } from "react";

import { DEFAULT_INTERVIEW } from "./InterviewPanel";
import { KB_UPLOAD_TOPIC } from "./KbPanel";
import { DEFAULT_MODEL } from "./ModelPanel";
import { DEFAULT_PERSONA } from "./PersonaPanel";
import { ackApplied, agentReadyForApply } from "./setupApply";
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
 * <LiveKitRoom>, it fires the held SetupScreen config EXACTLY ONCE in order:
 * persona.update → mode.update → model.update → queued KB sendFile.
 *
 * Readiness (F13): the agent participant is visible from ctx.connect(), but its
 * RPC methods and the kb.upload byte-stream handler only register AFTER
 * session.start() — which is also when it starts publishing lk.agent.state
 * (useVoiceAssistant().state). Gating on a LIVE state avoids an early performRpc
 * (UNSUPPORTED_METHOD) or, worse, an early sendFile that LiveKit silently drops
 * with no handler → a setup-queued KB upload vanishes with no kb.state error.
 *
 * Acks (F13): the agent handlers RESOLVE performRpc with a string ack ("applied"
 * / "error") rather than throwing, so a transport-only try/catch treats a
 * validation rejection as success. Each send checks the ack; the once-guard is
 * set ONLY after every send both resolves AND acks "applied", so a partial
 * failure re-runs on the next render (the effect depends on `state`) instead of
 * being permanently marked done.
 *
 * No RPC method/payload key or the kb.upload topic changes here — only WHEN they
 * fire moves from a per-panel Apply click to this gated effect. A useRef
 * once-guard keeps it React 19 Strict-Mode double-invoke safe.
 */
export default function ApplySetupOnConnect({ config }: { config: SessionConfig }) {
  const room = useRoomContext();
  const { agent, state } = useVoiceAssistant();
  const applied = useRef(false);
  const running = useRef(false);
  const [note, setNote] = useState("Connecting…");

  useEffect(() => {
    if (applied.current || running.current) return;
    // Resolve the agent identity exactly as the panels do.
    const fallback = Array.from(room.remoteParticipants.values())[0];
    const agentIdentity = agent?.identity ?? fallback?.identity;
    // Gate on BOTH the identity and a live post-start state — until the agent
    // publishes listening/thinking/speaking its handlers may not be registered.
    if (!agentIdentity || !agentReadyForApply(state)) {
      setNote("Still connecting the agent…");
      return;
    }
    // Re-entrancy guard for the async body (the once-guard is only set on full
    // success below, so this ref prevents a concurrent second run in between).
    running.current = true;

    (async () => {
      setNote("Applying your setup…");
      let allOk = true;

      // Send a JSON-RPC update and return whether the agent acked "applied".
      // A transport rejection OR a non-"applied" ack both count as a failure.
      const send = async (method: string, payload: unknown, failNote: string) => {
        try {
          const ack = await room.localParticipant.performRpc({
            destinationIdentity: agentIdentity,
            method,
            payload: JSON.stringify(payload),
          });
          if (!ackApplied(ack)) {
            allOk = false;
            setNote(failNote);
          }
        } catch {
          allOk = false;
          setNote(failNote);
        }
      };

      // persona.update — skip when unchanged from the agent default (default-skip).
      if (!sameAsDefault(config.persona, DEFAULT_PERSONA)) {
        await send("persona.update", config.persona, "Couldn't apply persona — you can re-apply from settings.");
      }

      // mode.update {mode, role_key} — skip when unchanged from the default.
      if (!sameAsDefault(config.mode, DEFAULT_INTERVIEW)) {
        await send("mode.update", config.mode, "Couldn't apply interview mode — you can re-apply from settings.");
      }

      // model.update {choice} — skip when unchanged from the default (Fast).
      if (!sameAsDefault(config.model, DEFAULT_MODEL)) {
        await send("model.update", { choice: config.model }, "Couldn't apply model — you can re-apply from settings.");
      }

      // Queued KB uploads — each picked file as its own byte stream on the
      // existing topic. sendFile has no ack channel, so a lost stream can only be
      // caught by the readiness gate above; a transport error still fails here.
      for (const file of config.kbFiles) {
        try {
          await room.localParticipant.sendFile(file, { topic: KB_UPLOAD_TOPIC });
        } catch {
          allOk = false;
          setNote(`Couldn't upload "${file.name}" — re-add it from settings.`);
        }
      }

      // Only mark done when EVERYTHING succeeded; otherwise leave the guard clear
      // so a later render (state change / re-mount) retries the failed pieces.
      running.current = false;
      if (allOk) {
        applied.current = true;
        setNote("");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agent?.identity, state]);

  if (!note) return null;
  return (
    <p className="transition-status" style={{ color: palette.textMuted, margin: 0 }}>
      {note}
    </p>
  );
}
