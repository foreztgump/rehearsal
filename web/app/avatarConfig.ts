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

// How long each laugh gesture holds before settling back to baseline (seconds). Kept
// short and reaction-like: the emoji gesture pins eyesClosed/jawOpen/mouthSmile, so a
// long hold fights the viseme lipsync and keeps a laughing face while the trainer talks
// through the following words. A full laugh is a touch longer than a chuckle. Passed as
// playGesture's `dur`.
export const LAUGH_GESTURE_SECONDS: Record<string, number> = {
  laugh: 1.0,
  chuckle: 0.7,
};

// Same-origin Draco decoder path (vendored, offline). The default GLB is Draco-
// geometry + WebP-texture compressed (AVTR-08); TalkingHead's GLTFLoader needs the
// decoder for KHR_draco_mesh_compression. WebP needs no decoder (browser-native).
// Trailing slash: three's DRACOLoader appends draco_decoder.js / draco_wasm_wrapper.js.
export const DRACO_DECODER_PATH = "/vendor/three/addons/libs/draco/";

// While speaking the trainer holds EYE CONTACT and faces the user (looks straight),
// like an attentive coach. avatarSpeakingEyeContact:1 keeps the gaze on camera, and
// avatarSpeakingHeadMove:0 disables the library's occasional gaussian head TURNS —
// those are what read as "looking away mid-sentence" and break eye contact. The face
// is kept alive by the mouth visemes, engagement brows, and hand gestures (added
// since), plus the volume-synced neck bob, which is independent of this dial — so a
// steady, forward-facing head no longer looks like a frozen statue. Raise
// avatarSpeakingHeadMove toward 1 to reintroduce head turns if a livelier head is
// wanted at the cost of eye contact.
export const TALKINGHEAD_SPEAKING_BEHAVIOR = {
  avatarSpeakingEyeContact: 1,
  avatarSpeakingHeadMove: 0,
} as const;

// Gaze locks held while speaking so the trainer FACES the user and holds eye contact
// (looks straight). Both the head-rotate axes and the eye-rotate axes are pinned to 0,
// because disabling the gaussian head TURNS alone (avatarSpeakingHeadMove:0) still let
// mood/gesture/lookAtCamera animations drift the head off-center. Pinning the head does
// NOT re-create the old "frozen statue": the volume-synced neck bob (talkinghead.mjs
// ~2665) is applied to the neck object independently of these headRotate morphs and
// survives the pin, and the face is kept alive by the mouth visemes, engagement brows,
// and laugh gesture (all added since the head-pin last read as a statue). Released on
// turn-end via applySpeakingGazeLock so ambient scanning resumes outside speech.
export const TALKINGHEAD_SPEAKING_GAZE_LOCKS = [
  ["headRotateX", 0],
  ["headRotateY", 0],
  ["headRotateZ", 0],
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

// A user-selectable avatar face. `id` is the stable key the picker round-trips;
// `label` is the human choice; `glb`/`body` are the model. Every GLB here MUST be
// TalkingHead-compatible (Mixamo rig + ARKit-52 + Oculus-15 visemes) — enforced by
// scripts/verify-avatars.mjs, which checks the morph targets of every file listed
// here. Add a face by dropping its GLB into web/public/avatars/, listing it below,
// and running `node scripts/verify-avatars.mjs`.
export type AvatarChoice = {
  id: string;
  label: string;
  glb: string;
  body: "F" | "M";
};

// The catalog of faces the user can pick on the setup screen. cyber-trainer is the
// seed default; the rest are the verified TalkingHead example faces (brunette,
// avaturn, avatarsdk) vendored in web/public/avatars/ — all free / non-
// commercial, see web/public/avatars/ATTRIBUTION.md. The picker's implicit first
// option is "Auto (match persona)" (selectedId omitted), which falls back to
// avatarForPersona — so this list is purely the explicit choices.
export const AVATAR_CATALOG: readonly AvatarChoice[] = [
  { id: "cyber-trainer", label: "Cyber Trainer", glb: "/avatars/cyber-trainer.glb", body: "F" },
  { id: "brunette", label: "Brunette", glb: "/avatars/brunette.glb", body: "F" },
  { id: "avaturn", label: "Avaturn", glb: "/avatars/avaturn.glb", body: "F" },
  { id: "avatarsdk", label: "Avatar SDK (male)", glb: "/avatars/avatarsdk.glb", body: "M" },
];

// Resolve the avatar to load from the persona AND an optional explicit picker choice.
// An explicit choice overrides the persona's GLB/body but KEEPS the persona's resting
// mood, so expression continuity (the per-persona baseline used by AvatarStage) is
// preserved across faces. No match / no choice → the persona default (avatarForPersona).
export function resolveAvatar(
  personaName: string | null | undefined,
  selectedId?: string | null,
): AvatarSpec {
  const persona = avatarForPersona(personaName);
  if (!selectedId) return persona;
  const choice = AVATAR_CATALOG.find((c) => c.id === selectedId);
  if (!choice) return persona;
  return { glb: choice.glb, body: choice.body, mood: persona.mood };
}
