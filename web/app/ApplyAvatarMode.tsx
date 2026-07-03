"use client";

import { useEffect, useRef, useState } from "react";
import { useRoomContext, useVoiceAssistant } from "@livekit/components-react";

import {
  AVATAR_UPDATE_RETRY_MS,
  retryTickForSend,
  shouldScheduleRetry,
} from "./avatarRetry";

const AVATAR_UPDATE_METHOD = "avatar.update";

// Owns ALL avatar.update sends (initial state after connect + every toggle change),
// so the gate's source of truth is SessionConfig.avatarOn and nothing double-sends.
export default function ApplyAvatarMode({ avatarOn }: { avatarOn: boolean }) {
  const room = useRoomContext();
  const { agent } = useVoiceAssistant();
  const lastSent = useRef<boolean | null>(null);
  // The target value the current retry budget belongs to. When avatarOn differs
  // from it, the send is a NEW toggle and the budget resets (F32) — otherwise a
  // spent budget from an earlier toggle would leave a later toggle with at most
  // one attempt and could permanently desync the lip-sync gate from avatarOn.
  const budgetFor = useRef<boolean | null>(null);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [retryTick, setRetryTick] = useState(0);
  const agentIdentity = agent?.identity;

  useEffect(() => {
    if (!agentIdentity) return; // wait for the agent to join
    if (lastSent.current === avatarOn) return;
    lastSent.current = avatarOn;

    // A new toggle collapses the running budget to 0; a same-target retry keeps it.
    const isNewTarget = budgetFor.current !== avatarOn;
    budgetFor.current = avatarOn;
    const tick = retryTickForSend(retryTick, isNewTarget);
    if (isNewTarget && retryTick !== 0) setRetryTick(0);

    room.localParticipant
      .performRpc({
        destinationIdentity: agentIdentity,
        method: AVATAR_UPDATE_METHOD,
        payload: JSON.stringify({ on: avatarOn }),
      })
      .then(() => {
        if (retryTick !== 0) setRetryTick(0); // recovered — re-arm retries for later toggles
      })
      .catch((err) => {
        // Non-fatal: lip-sync degrades to Path-A / no-publish; never break the room.
        console.warn("avatar.update failed", err);
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
  }, [agentIdentity, avatarOn, room, retryTick]);

  return null;
}
