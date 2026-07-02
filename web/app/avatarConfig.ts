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
// {seq, request_id, words:[{w,s,e}]} with sentence-relative seconds; AvatarStage
// re-anchors each schedule to the measured audio onset so jitter never desyncs.
export const LIPSYNC_TOPIC = "lk.avatar.lipsync";

// Same-origin Draco decoder path (vendored, offline). The default GLB is Draco-
// geometry + WebP-texture compressed (AVTR-08); TalkingHead's GLTFLoader needs the
// decoder for KHR_draco_mesh_compression. WebP needs no decoder (browser-native).
// Trailing slash: three's DRACOLoader appends draco_decoder.js / draco_wasm_wrapper.js.
export const DRACO_DECODER_PATH = "/vendor/three/addons/libs/draco/";

// During speech the trainer should keep direct eye contact. Ambient scanning is
// fine outside speech, but looking away mid-answer reads unnatural in live UAT.
export const TALKINGHEAD_SPEAKING_BEHAVIOR = {
  avatarSpeakingEyeContact: 1,
  avatarSpeakingHeadMove: 0,
} as const;

export const TALKINGHEAD_SPEAKING_GAZE_LOCKS = [
  ["eyesRotateX", 0],
  ["eyesRotateY", 0],
  ["headRotateX", 0],
  ["headRotateY", 0],
  ["headRotateZ", 0],
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
