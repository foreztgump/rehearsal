import assert from "node:assert/strict";
import test from "node:test";
import { transcriptLineClass } from "./transcriptLine.ts";

test("final agent line: glass-left bubble, no interim, popped once", () => {
  assert.equal(
    transcriptLineClass({ isUser: false, isFinal: true }),
    "bubble bubble-pop agent",
  );
});

test("final user line: accent-right bubble", () => {
  assert.equal(
    transcriptLineClass({ isUser: true, isFinal: true }),
    "bubble bubble-pop user",
  );
});

test("interim lines add the .interim tentative marker (both sides)", () => {
  assert.equal(
    transcriptLineClass({ isUser: false, isFinal: false }),
    "bubble bubble-pop agent interim",
  );
  assert.equal(
    transcriptLineClass({ isUser: true, isFinal: false }),
    "bubble bubble-pop user interim",
  );
});

test("class flips from interim to final on the same line (streaming finalize)", () => {
  const interim = transcriptLineClass({ isUser: true, isFinal: false });
  const final = transcriptLineClass({ isUser: true, isFinal: true });
  assert.ok(interim.includes(" interim"), "interim must carry the marker");
  assert.ok(!final.includes(" interim"), "final must drop the marker");
});
