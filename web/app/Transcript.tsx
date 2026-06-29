"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { normalizeTranscriptSegments } from "./transcriptSegments";
import { useTranscriptionSegments } from "./useTranscriptionSegments";
import { font, palette, radius, space } from "./ui/tokens";

// "At bottom" tolerance in px. Kept above a couple of px so a programmatic
// scrollTop write to the exact bottom never falsely flips atBottom (RESEARCH §4
// React 19 gotcha) and a near-bottom human scroll still counts as stuck.
const THRESHOLD = 32;

/**
 * Two-sided live transcript (VOICE-07) with smart stick-to-bottom auto-scroll
 * (success criterion D-04). Transcript segments are tagged by participant
 * identity; segments are split into USER (right, #e6edf3) vs AGENT
 * (left, #58a6ff) sides. The view sticks to the newest line ONLY while the user is
 * already at the bottom; once they scroll up to read history it never yanks, and a
 * "Jump to latest ↓" pill returns them to the bottom + re-engages stick.
 *
 * In-progress (interim) segments render at reduced opacity / italic so a VAD
 * false-trigger shows as visible-but-tentative rather than a hidden LLM call.
 * Token streaming is rendered instantly (no animation) regardless of motion prefs.
 */
export default function Transcript({ resetAfter = 0 }: { resetAfter?: number }) {
  const segments = useTranscriptionSegments();
  const lines = useMemo(() => normalizeTranscriptSegments(segments), [segments]);

  // SESS-02 reset: record when each segment was first seen, then hide everything that
  // predates the latest Reset. The room keeps accumulating transcriptions across a
  // same-room Reset; this is how the view "forgets" the prior conversation. A brand-new
  // (not-yet-recorded) segment falls back to "now" so it shows immediately.
  const firstSeenRef = useRef<Map<string, number>>(new Map());
  useEffect(() => {
    for (const line of lines) {
      if (!firstSeenRef.current.has(line.id)) {
        firstSeenRef.current.set(line.id, Date.now());
      }
    }
  }, [lines]);
  const visibleLines = lines.filter(
    (line) => (firstSeenRef.current.get(line.id) ?? Date.now()) >= resetAfter,
  );

  const containerRef = useRef<HTMLDivElement>(null);
  // atBottom lives in a ref (not state) so recomputing it on every scroll event
  // does not churn renders; only the pill's visibility is state.
  const atBottomRef = useRef(true);
  const [showJump, setShowJump] = useState(false);

  function recomputeAtBottom() {
    const el = containerRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= THRESHOLD;
    atBottomRef.current = atBottom;
    setShowJump(!atBottom && lines.length > 0);
  }

  // Stick to the newest line on each segment update, but ONLY when the user is at
  // the bottom. Instant (scrollTop write) — never smooth — to avoid streaming
  // token thrash. The write lands at the exact bottom so the resulting scroll
  // event keeps atBottom true.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    if (atBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    } else {
      // New content arrived while scrolled up — surface the jump pill.
      setShowJump(lines.length > 0);
    }
  }, [lines]);

  function jumpToLatest() {
    const el = containerRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    atBottomRef.current = true;
    setShowJump(false);
  }

  return (
    <div style={{ position: "relative", flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <div
        ref={containerRef}
        className="transcript-scroll"
        onScroll={recomputeAtBottom}
        style={{ flex: 1, minHeight: 0, overflowY: "auto", textAlign: "left" }}
      >
        {visibleLines.length === 0 ? (
          <div
            style={{
              height: "100%",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: space.xs,
              textAlign: "center",
              color: palette.textMuted,
            }}
          >
            <strong style={{ fontSize: font.size.heading, color: palette.textBody }}>
              Start talking
            </strong>
            <span style={{ fontSize: font.size.body }}>
              Say hello, ask a question, or describe what you want to practice.
            </span>
          </div>
        ) : (
          <ul
            style={{
              listStyle: "none",
              padding: `${space.xs} 0`,
              margin: 0,
              display: "flex",
              flexDirection: "column",
              gap: space.sm,
            }}
          >
            {visibleLines.map((line) => {
              const isUser = line.speaker === "You";
              // Use the theme-reactive .bubble classes (globals.css): agent = glass
              // left, user = accent-gradient right, .interim = tentative, .bubble-pop
              // = one-shot entrance (runs once; the <li> is keyed by line id so a
              // streaming text update reuses the node and never re-animates).
              return (
                <li
                  key={line.id}
                  data-from={isUser ? "user" : "agent"}
                  data-final={line.isFinal ? "true" : "false"}
                  data-source-id={line.sourceId}
                  className={`bubble bubble-pop ${isUser ? "user" : "agent"}${line.isFinal ? "" : " interim"}`}
                >
                  <span className="who">{line.speaker}</span>
                  {line.text}
                  {line.isFinal && <span className="final-mark" aria-label="final transcript">✓</span>}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {showJump && (
        <button
          type="button"
          className="jump-pill transition-hover"
          onClick={jumpToLatest}
          style={{
            position: "absolute",
            bottom: space.md,
            left: "50%",
            transform: "translateX(-50%)",
            padding: `${space.xs} ${space.md}`,
            borderRadius: radius.pill,
            border: "none",
            background: palette.accent,
            color: palette.bg,
            fontWeight: font.weight.semibold,
            fontSize: font.size.label,
            cursor: "pointer",
            boxShadow: "0 2px 8px rgba(0,0,0,0.4)",
          }}
        >
          Jump to latest ↓
        </button>
      )}
    </div>
  );
}
