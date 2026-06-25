"use client";

import { useTranscriptions } from "@livekit/components-react";

// The token route mints user identities as `user-<ts>`; everything else in the
// room (the agent worker) is the AGENT side.
const USER_IDENTITY_PREFIX = "user-";

/**
 * Two-sided live transcript (VOICE-07). useTranscriptions() returns
 * TextStreamData[] tagged by participant identity; segments are split into USER
 * vs AGENT sides. In-progress partials render too, so a VAD false-trigger shows
 * as "visible nothing" rather than a hidden LLM call.
 */
export default function Transcript() {
  const segments = useTranscriptions();

  return (
    <ul style={{ listStyle: "none", padding: 0, textAlign: "left" }}>
      {segments.map((segment) => {
        const identity = segment.participantInfo.identity;
        const isUser = identity.startsWith(USER_IDENTITY_PREFIX);
        return (
          <li
            key={segment.streamInfo.id}
            data-from={isUser ? "user" : "agent"}
            style={{
              textAlign: isUser ? "right" : "left",
              color: isUser ? "#e6edf3" : "#58a6ff",
              margin: "0.25rem 0",
            }}
          >
            <strong>{isUser ? "You" : "Agent"}:</strong> {segment.text}
          </li>
        );
      })}
    </ul>
  );
}
