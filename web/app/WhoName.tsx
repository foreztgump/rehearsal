"use client";

import { useVoiceAssistant } from "@livekit/components-react";

/**
 * The status line beneath the orb visualizer (mockup `.who-name`). Translates the
 * live agent state into the same human phrasing the mockups used, with the agent's
 * display name bolded while it is thinking/speaking. Must render inside
 * <LiveKitRoom>.
 */
export default function WhoName({ agentName }: { agentName: string }) {
  const { state } = useVoiceAssistant();

  switch (state) {
    case "thinking":
      return (
        <p className="who-name">
          <b>{agentName}</b> is thinking…
        </p>
      );
    case "speaking":
      return (
        <p className="who-name">
          <b>{agentName}</b> speaking
        </p>
      );
    case "listening":
      return <p className="who-name">Listening to you…</p>;
    default:
      return <p className="who-name">Talk when you&apos;re ready</p>;
  }
}
