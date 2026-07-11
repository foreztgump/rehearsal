// Pure client constants for the OPTIONAL 3D avatar (Phase 12), shared by 12-01/12-02.
// Dependency-free (no React) so it tree-shakes cleanly and never pulls the avatar
// libraries into the voice-only bundle.

// Interview-appropriate framing (AVTR-05). TalkingHead supports "full" | "mid" |
// "upper" | "head"; we frame to the upper body. "head" is the tighter alternate.
export const CAMERA_VIEW: "upper" | "head" = "upper";

// Bare specifier the importmap (web/app/layout.tsx) maps to the vendored
// /vendor/talkinghead/talkinghead.mjs. AvatarStage does `await import(TALKINGHEAD_SPECIFIER)`
// so the heavy library resolves at runtime via the importmap, NOT through webpack —
// keeping it out of the voice-only chunk (AVTR-01).
export const TALKINGHEAD_SPECIFIER = "talkinghead";

// LiveKit data-channel topic the agent's CaptionedTTS publishes word schedules on
// (mirrors agent/captioned_tts.py LIPSYNC_TOPIC). Payload is JSON
// {seq, request_id, words:[{w,s,e}], mood?} with sentence-relative seconds; the
// optional `mood` field carries the per-sentence avatar expression (one of
// AGENT_MOODS). AvatarStage re-anchors each schedule to the measured audio onset so
// jitter never desyncs, applying the mood at anchor time (see AGENT_MOODS below).
export const LIPSYNC_TOPIC = "lk.avatar.lipsync";

// LiveKit data-channel topic the agent publishes per-sentence avatar mood on in
// EXPRESSIVE mode (Chatterbox TTS), payload JSON {seq, mood} with mood ∈ AGENT_MOODS.
// Kokoro mode piggybacks mood on LIPSYNC_TOPIC's schedule instead, so this topic
// carries mood only when there is no lip-sync schedule to ride on. Publishing is
// gated by avatar-ON, so a voice-only session sees none. AvatarStage applies the
// mood at the audio anchor (when the agent's audio is audible), the same way the
// lip-sync-piggybacked mood is applied.
export const MOOD_TOPIC = "lk.avatar.mood";

// Moods AvatarStage will accept from the agent's per-sentence `mood` field. This
// guards talkinghead.mjs setMood (which THROWS on an unknown mood) and lets
// queueSchedule fall back to "neutral" for a missing/unknown value. "angry" is
// intentionally excluded — the agent never emits it.
export const AGENT_MOODS = new Set(["neutral", "happy", "love", "sad"]);

// Laugh cue (expressive mode) → the TalkingHead emoji gesture the face plays as a
// TRANSIENT reaction in sync with the audio [laugh]/[chuckle] the model vocalizes.
// "😂" is the full laugh (squint eyes + open jaw + big smile); "🙂" is a soft smile
// for a chuckle. playGesture queues it into the animation queue and auto-returns to
// the mood baseline, so it composes with lip-sync and speaking head motion. Keys are
// the agent's laugh_kind() values; anything else is ignored on receipt.
export const LAUGH_GESTURE: Record<string, string> = {
  laugh: "😂",
  chuckle: "🙂",
};

// How long each laugh gesture holds before settling back to baseline (seconds). A full
// laugh lingers; a chuckle is quicker. Passed as playGesture's `dur`.
export const LAUGH_GESTURE_SECONDS: Record<string, number> = {
  laugh: 2.5,
  chuckle: 1.5,
};

// Same-origin Draco decoder path (vendored, offline). The default GLB is Draco-
// geometry + WebP-texture compressed (AVTR-08); TalkingHead's GLTFLoader needs the
// decoder for KHR_draco_mesh_compression. WebP needs no decoder (browser-native).
// Trailing slash: three's DRACOLoader appends draco_decoder.js / draco_wasm_wrapper.js.
export const DRACO_DECODER_PATH = "/vendor/three/addons/libs/draco/";

// During speech the trainer keeps a strong eye-contact bias, but is NOT frozen: we
// allow the library's own subtle, bounded speaking head motion (occasional gaussian
// head turns + the volume-synced neck bob) so the avatar reads as alive rather than a
// talking statue. avatarSpeakingHeadMove is the single dial for how often the head
// turns while speaking — lower it toward 0 if it's too much, raise toward 1 for more.
export const TALKINGHEAD_SPEAKING_BEHAVIOR = {
  avatarSpeakingEyeContact: 1,
  avatarSpeakingHeadMove: 0.4,
} as const;

// Gaze locks held ONLY on the eyes while speaking, so the eyes stay on the camera
// (what actually reads as "engaged") without pinning the head. The head-rotate axes
// are intentionally NOT locked here — freezing them was the "frozen statue" cause;
// letting them move lets the library's speaking head sway + neck bob come through.
export const TALKINGHEAD_SPEAKING_GAZE_LOCKS = [
  ["eyesRotateX", 0],
  ["eyesRotateY", 0],
] as const;

type FixedMorphTarget = {
  setFixedValue: (mt: string, val: number | null) => void;
};

export function applySpeakingGazeLock(head: FixedMorphTarget, speaking: boolean) {
  for (const [mt, val] of TALKINGHEAD_SPEAKING_GAZE_LOCKS) {
    head.setFixedValue(mt, speaking ? val : null);
  }
}

// What AvatarStage needs to render a persona's avatar. `body` ("F"|"M") only sets
// TalkingHead's idle-pose/gesture set; `mood` is the persona's resting expression
// applied via setMood on load (AVTR-04). `glb` is a same-origin vendored asset.
export type AvatarSpec = {
  glb: string;
  mood: string;
  body: "F" | "M";
};

// Default avatar so Avatar mode works out of the box for the seed cyber-trainer
// persona (AVTR-06). cyber-trainer.glb = the vendored Draco/WebP RPM half-body
// (Mixamo rig + ARKit-52 + Oculus-15 visemes, verified in 12-AVATAR-VERIFY.md).
export const DEFAULT_AVATAR: AvatarSpec = {
  glb: "/avatars/cyber-trainer.glb",
  mood: "neutral",
  body: "F",
};

// Client-side ONLY persona→avatar map, keyed by persona `display_name` (the seam in
// PersonaPanel.tsx, mirroring agent/persona.py). NO server field, NO persona.update
// change — honors the Phase 12 isolation gate (empty server diff). Voice (`voice_id`)
// stays owned by persona state and is untouched here. Add personas by display_name;
// anything unmapped falls back to DEFAULT_AVATAR via avatarForPersona().
// Preset display_names (web/app/personaPresets.ts) all reuse the default GLB; only
// the resting mood varies per preset, so the avatar's expression follows the chosen
// persona with no new asset. Keys MUST match the preset display_names exactly.
export const PERSONA_AVATARS: Record<string, AvatarSpec> = {
  "Voice Fluency Coach": { glb: DEFAULT_AVATAR.glb, mood: "happy", body: "F" },
  "Cybersecurity Trainer": DEFAULT_AVATAR,
  "AI/ML Coach": { glb: DEFAULT_AVATAR.glb, mood: "happy", body: "F" },
  "Data Analyst Coach": { glb: DEFAULT_AVATAR.glb, mood: "neutral", body: "F" },
  "Software Engineering Mentor": { glb: DEFAULT_AVATAR.glb, mood: "neutral", body: "M" },
  "Cloud/DevOps Coach": { glb: DEFAULT_AVATAR.glb, mood: "neutral", body: "M" },
  "Product Manager Coach": { glb: DEFAULT_AVATAR.glb, mood: "happy", body: "F" },
  "Sales Roleplay Partner": { glb: DEFAULT_AVATAR.glb, mood: "neutral", body: "M" },
  "Customer Success Coach": { glb: DEFAULT_AVATAR.glb, mood: "happy", body: "F" },
  "Leadership Coach": { glb: DEFAULT_AVATAR.glb, mood: "neutral", body: "M" },
  "Healthcare Communication Coach": { glb: DEFAULT_AVATAR.glb, mood: "love", body: "F" },
  "Finance & Business Coach": { glb: DEFAULT_AVATAR.glb, mood: "neutral", body: "M" },
  "GRC / Policy Advisor": { glb: DEFAULT_AVATAR.glb, mood: "neutral", body: "F" },
  "Climate & Energy Coach": { glb: DEFAULT_AVATAR.glb, mood: "neutral", body: "F" },
  "Language Conversation Partner": { glb: DEFAULT_AVATAR.glb, mood: "happy", body: "F" },
};

// Resolve a persona display_name to its avatar, defaulting so Avatar mode never
// breaks for an unmapped/blank persona (AVTR-06). Pure function, no React/server.
export function avatarForPersona(name: string | null | undefined): AvatarSpec {
  if (name && Object.prototype.hasOwnProperty.call(PERSONA_AVATARS, name)) {
    return PERSONA_AVATARS[name];
  }
  return DEFAULT_AVATAR;
}
