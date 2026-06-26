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

// NOTE (12-02): the persona→GLB map + default GLB url are added here in the next plan.
