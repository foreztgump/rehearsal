import assert from "node:assert/strict";
import test from "node:test";
import { PERSONA_FIELDS, parseSavedPersonas, selfCheck } from "./savedPersonas.ts";

test("saved persona storage self-check passes", () => {
  selfCheck();
});

test("F31: a loaded persona carries exactly the known fields (no extras)", () => {
  // A stale / hand-edited localStorage record with an EXTRA key. The agent applies
  // it via exact-keys Persona(**snapshot) and rejects unknown keys, so the loader
  // must strip anything outside PERSONA_FIELDS.
  const raw = JSON.stringify([
    {
      id: "one",
      name: "Legacy",
      createdAt: "2026-06-30T00:00:00.000Z",
      updatedAt: "2026-06-30T00:00:00.000Z",
      persona: {
        role_text: "You are a coach.",
        display_name: "Coach",
        difficulty: "intermediate",
        verbosity: "balanced",
        correction: "gentle",
        voice_id: "af_bella",
        legacy_extra: "should be dropped",
        tone: "should also be dropped",
      },
    },
  ]);

  const parsed = parseSavedPersonas(raw);
  assert.equal(parsed.length, 1, "valid record must survive parsing");
  const keys = Object.keys(parsed[0].persona).sort();
  assert.deepEqual(keys, [...PERSONA_FIELDS].sort(), "persona must carry EXACTLY the known fields");
  assert.ok(!("legacy_extra" in parsed[0].persona), "extra keys must be stripped on load");
});
