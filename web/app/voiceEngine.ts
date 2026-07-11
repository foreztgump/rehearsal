// Voice-engine choice, install-aware. The expressive engine (Chatterbox-Turbo) is
// opt-in at install time: the installer builds it behind the `expressive` compose
// profile and bakes NEXT_PUBLIC_REHEARSAL_EXPRESSIVE_AVAILABLE=1 into the web bundle.
// When it is not installed the flag stays "0" and the UI hides the voice picker
// entirely (a dead toggle that routes to a service that isn't running is worse than
// no toggle). Mirrors the R7 model-choice baking pattern in ModelPanel.ts.
export const EXPRESSIVE_AVAILABLE =
  process.env.NEXT_PUBLIC_REHEARSAL_EXPRESSIVE_AVAILABLE === "1";

// Named engines for the picker — the point is to STOP the UI reading as "stale to
// Kokoro": each option names the engine and its headline tradeoff so the active voice
// is explicit. The values map to SessionConfig.expressiveVoice (kokoro=false).
export const VOICE_ENGINE_OPTIONS = [
  { label: "Kokoro · fast", value: "kokoro" },
  { label: "Chatterbox · expressive", value: "chatterbox" },
] as const;
