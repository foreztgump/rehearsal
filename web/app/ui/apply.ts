// Shared apply-status contract for the config panels that fire a live-agent RPC
// (PersonaPanel / ModelPanel / InterviewPanel). The "applying…→applied" window is
// a panel-local union, independent of the global agent-state pill. Pure constants,
// no React import, no side effects (same bundle-isolation discipline as tokens.ts).
//
// These values are byte-identical to the pre-refactor PersonaPanel/ModelPanel/
// InterviewPanel definitions — the de-dup is presentational only.
//
// NOTE: KbPanel uses a DIFFERENT union (KbStatus) with its own status maps — do
// NOT merge it here.

export type ApplyState = "idle" | "applying" | "applied" | "error";

export const STATUS_LABEL: Record<ApplyState, string> = {
  idle: "",
  applying: "applying…",
  applied: "applied",
  error: "error — could not apply",
};

export const STATUS_COLOR: Record<ApplyState, string> = {
  idle: "#8b949e",
  applying: "#d29922",
  applied: "#3fb950",
  error: "#f85149",
};
