"use client";

import { useEffect, useRef, useState } from "react";
import { useRoomContext, useVoiceAssistant } from "@livekit/components-react";

import {
  AVATAR_UPDATE_RETRY_MS,
  retryTickForSend,
  shouldScheduleRetry,
} from "./avatarRetry";

const TTS_UPDATE_METHOD = "tts.update";

// Owns ALL tts.update sends (initial state after connect + every toggle change),
// so the agent's TTS-engine choice (Kokoro ↔ Chatterbox) is driven solely by
// SessionConfig.expressiveVoice and nothing double-sends. Mirrors ApplyAvatarMode.
export default function ApplyExpressiveMode({ expressive }: { expressive: boolean }) {
  const room = useRoomContext();
  const { agent } = useVoiceAssistant();
  const lastSent = useRef<boolean | null>(null);
  // The target value the current retry budget belongs to. When expressive differs
  // from it, the send is a NEW toggle and the budget resets (F32) — otherwise a
  // spent budget from an earlier toggle would leave a later toggle with at most
  // one attempt and could permanently desync the TTS engine from expressiveVoice.
  const budgetFor = useRef<boolean | null>(null);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [retryTick, setRetryTick] = useState(0);
  const agentIdentity = agent?.identity;

  useEffect(() => {
    if (!agentIdentity) return; // wait for the agent to join
    if (lastSent.current === expressive) return;
    lastSent.current = expressive;

    // A new toggle collapses the running budget to 0; a same-target retry keeps it.
    const isNewTarget = budgetFor.current !== expressive;
    budgetFor.current = expressive;
    const tick = retryTickForSend(retryTick, isNewTarget);
    if (isNewTarget && retryTick !== 0) setRetryTick(0);

    room.localParticipant
      .performRpc({
        destinationIdentity: agentIdentity,
        method: TTS_UPDATE_METHOD,
        payload: JSON.stringify({ expressive }),
      })
      .then(() => {
        if (retryTick !== 0) setRetryTick(0); // recovered — re-arm retries for later toggles
      })
      .catch((err) => {
        // Non-fatal: the agent keeps its current TTS engine; never break the room.
        console.warn("tts.update failed", err);
        lastSent.current = null; // allow the resend below (or a later toggle) to retry
        if (shouldScheduleRetry(tick)) {
          retryTimer.current = setTimeout(
            () => setRetryTick((prev) => prev + 1),
            AVATAR_UPDATE_RETRY_MS,
          );
        }
      });
    return () => {
      if (retryTimer.current) clearTimeout(retryTimer.current);
    };
  }, [agentIdentity, expressive, room, retryTick]);

  return null;
}
