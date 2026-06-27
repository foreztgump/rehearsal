"use client";

import { useEffect, useRef, useState } from "react";
import { useRoomContext, useVoiceAssistant } from "@livekit/components-react";

const AVATAR_UPDATE_METHOD = "avatar.update";
// The agent registers avatar.update late in its entrypoint (after connect), so an
// initial send can land before the method exists and reject. Retry a bounded number
// of times so the avatar's lip-sync gate isn't silently stuck OFF for the session.
const AVATAR_UPDATE_MAX_RETRIES = 5;
const AVATAR_UPDATE_RETRY_MS = 500;

// Owns ALL avatar.update sends (initial state after connect + every toggle change),
// so the gate's source of truth is SessionConfig.avatarOn and nothing double-sends.
export default function ApplyAvatarMode({ avatarOn }: { avatarOn: boolean }) {
  const room = useRoomContext();
  const { agent } = useVoiceAssistant();
  const lastSent = useRef<boolean | null>(null);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [retryTick, setRetryTick] = useState(0);
  const agentIdentity = agent?.identity;

  useEffect(() => {
    if (!agentIdentity) return; // wait for the agent to join
    if (lastSent.current === avatarOn) return;
    lastSent.current = avatarOn;
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
        if (retryTick < AVATAR_UPDATE_MAX_RETRIES) {
          retryTimer.current = setTimeout(
            () => setRetryTick((tick) => tick + 1),
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
