// Pure presentation helpers for a single transcript line (Transcript.tsx). Kept
// dependency-free so the class/attribute derivation is unit-testable with node --test
// and can be shared by the memoized <TranscriptLine> row (O9).

export type TranscriptLineView = {
  isUser: boolean;
  isFinal: boolean;
};

/**
 * The theme-reactive bubble class list for a line (globals.css): agent = glass left,
 * user = accent-gradient right; a non-final (interim) line adds `.interim` so a VAD
 * false-trigger reads as tentative. `.bubble-pop` is a one-shot entrance that runs
 * once because the row is keyed by line id (a streaming text update reuses the node).
 * Pure: identical inputs → identical string.
 */
export function transcriptLineClass({ isUser, isFinal }: TranscriptLineView): string {
  return `bubble bubble-pop ${isUser ? "user" : "agent"}${isFinal ? "" : " interim"}`;
}
