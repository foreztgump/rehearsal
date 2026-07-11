// Web mirror of agent/voice_map.py — Kokoro voice id → Chatterbox named voice.
//
// CANONICAL SOURCE IS THE AGENT (`agent/voice_map.py`); this table exists only so the
// Voice picker can show the TRUE expressive voice name (Plan B: the label must match
// what you hear). In expressive mode the agent translates the persona's Kokoro
// `voice_id` to a gender-matched Chatterbox voice, so the UI would otherwise promise
// "Bella" while Chatterbox actually speaks "Olivia". Keep these 13 entries in sync with
// the agent's _CHATTERBOX_VOICE_BY_KOKORO_ID (gender-only mapping; rarely changes).
const CHATTERBOX_VOICE_BY_KOKORO_ID: Record<string, string> = {
  // female (af_/bf_)
  af_heart: "Emily",
  af_bella: "Olivia",
  af_nicole: "Alice",
  af_sarah: "Abigail",
  af_kore: "Cora",
  bf_emma: "Elena",
  bf_alice: "Jade",
  // male (am_/bm_)
  am_michael: "Michael",
  am_fenrir: "Adrian",
  am_puck: "Austin",
  am_adam: "Alexander",
  bm_george: "Gabriel",
  bm_daniel: "Thomas",
};

// The Chatterbox voice actually heard in expressive mode for a given persona voice id.
// Falls back to the id itself for unknown shapes (mirrors the agent's gender fallback
// only loosely — the UI never sends this value, it is display-only).
export function chatterboxVoiceName(voiceId: string): string {
  return CHATTERBOX_VOICE_BY_KOKORO_ID[voiceId] ?? voiceId;
}
