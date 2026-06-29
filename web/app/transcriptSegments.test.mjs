import assert from "node:assert/strict";
import test from "node:test";
import {
  applyTranscriptCorrection,
  applyTranscriptCorrectionOrDefer,
  mergeTranscriptSegment,
  normalizeTranscriptSegments,
} from "./transcriptSegments.ts";

const finalAttr = "lk.transcription_final";
const segmentAttr = "lk.segment_id";

function segment(id, identity, text, final = false, segmentId = undefined) {
  return {
    text,
    participantInfo: { identity },
    streamInfo: {
      id,
      attributes: {
        ...(final ? { [finalAttr]: final } : {}),
        ...(segmentId ? { [segmentAttr]: segmentId } : {}),
      },
    },
  };
}

test("final user transcript replaces the prior interim bubble", () => {
  const lines = normalizeTranscriptSegments([
    segment("interim-1", "user-1", "turnips and carrot"),
    segment("final-1", "user-1", "turnips and carrots", "true"),
  ]);

  assert.equal(lines.length, 1);
  assert.equal(lines[0].id, "interim-1");
  assert.equal(lines[0].text, "turnips and carrots");
  assert.equal(lines[0].isFinal, true);
});

test("boolean final attribute also replaces the prior interim bubble", () => {
  const lines = normalizeTranscriptSegments([
    segment("interim-1", "user-1", "flour fat and saw"),
    segment("final-1", "user-1", "flour fat and sauce", true),
  ]);

  assert.equal(lines.length, 1);
  assert.equal(lines[0].text, "flour fat and sauce");
  assert.equal(lines[0].isFinal, true);
});

test("final transcript does not replace another speaker", () => {
  const lines = normalizeTranscriptSegments([
    segment("agent-1", "agent", "hello"),
    segment("user-final", "user-1", "hello", true),
  ]);

  assert.deepEqual(lines.map((line) => line.speaker), ["Agent", "You"]);
});

test("same segment id final stream updates the existing bubble metadata", () => {
  const segments = mergeTranscriptSegment(
    [segment("interim-stream", "user-1", "flour fat and saw", false, "turn-1")],
    segment("final-stream", "user-1", "flour fat and sauce", true, "turn-1"),
  );
  const lines = normalizeTranscriptSegments(segments);

  assert.equal(lines.length, 1);
  assert.equal(lines[0].id, "interim-stream");
  assert.equal(lines[0].text, "flour fat and sauce");
  assert.equal(lines[0].isFinal, true);
});

test("Parakeet correction replaces the latest final user bubble", () => {
  const corrected = applyTranscriptCorrection([
    segment("agent-1", "agent", "hello", true),
    segment("user-1", "user-1", "is this", true),
  ], "so barge-in does not work correctly anymore");
  const lines = normalizeTranscriptSegments(corrected);

  assert.equal(lines.length, 2);
  assert.equal(lines[1].text, "so barge-in does not work correctly anymore");
  assert.equal(lines[1].speaker, "You");
  assert.equal(lines[1].isFinal, true);
});

test("Parakeet correction waits for a final user bubble", () => {
  const deferred = applyTranscriptCorrectionOrDefer([
    segment("user-interim", "user-1", "bar gin"),
  ], "barge-in");
  const merged = mergeTranscriptSegment(
    deferred.segments,
    segment("user-final", "user-1", "bargain", true, "turn-1"),
  );
  const corrected = applyTranscriptCorrectionOrDefer(merged, deferred.pendingCorrection);
  const lines = normalizeTranscriptSegments(corrected.segments);

  assert.equal(deferred.pendingCorrection, "barge-in");
  assert.equal(corrected.pendingCorrection, null);
  assert.equal(lines.length, 1);
  assert.equal(lines[0].text, "barge-in");
  assert.equal(lines[0].isFinal, true);
});
