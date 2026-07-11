import assert from "node:assert/strict";
import test from "node:test";
import {
  PERSONA_FIELDS,
  PERSONA_VOICE_IDS,
  formatVoiceLabel,
  parseSavedPersonas,
  selfCheck,
} from "./savedPersonas.ts";

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

test("formatVoiceLabel: standard mode decodes accent + gender from the id", () => {
  // a*=US, b*=British; *f_=female, *m_=male; name is capitalized.
  assert.equal(formatVoiceLabel("af_bella"), "Bella — US, female");
  assert.equal(formatVoiceLabel("bm_daniel"), "Daniel — British, male");
  assert.equal(formatVoiceLabel("bf_alice"), "Alice — British, female");
});

test("formatVoiceLabel: expressive mode shows the mapped Chatterbox voice (gender only)", () => {
  // The persona voice maps to a gender-matched Chatterbox voice; the label must match
  // what is HEARD (Olivia, not Bella) and omits accent (the map does not preserve it).
  assert.equal(formatVoiceLabel("af_bella", true), "Olivia — female");
  assert.equal(formatVoiceLabel("am_michael", true), "Michael — male");
  assert.equal(formatVoiceLabel("bm_daniel", true), "Thomas — male");
});

test("formatVoiceLabel: every persona voice id maps to a real Chatterbox name in expressive mode", () => {
  // Guards web voiceMap.ts against drift: no id may fall through to the raw id (which
  // would mean a missing mapping). Every expressive label must be "<Name> — <gender>".
  for (const id of PERSONA_VOICE_IDS) {
    const label = formatVoiceLabel(id, true);
    assert.match(label, /^[A-Z][a-z]+ — (female|male)$/, `${id} -> ${label}`);
    assert.ok(!label.includes(id), `${id} must not fall through to the raw id`);
  }
});

test("formatVoiceLabel: an unknown id shape falls back to the raw id", () => {
  assert.equal(formatVoiceLabel("weird"), "weird");
});
