import assert from "node:assert/strict";
import test from "node:test";
import {
  DEFAULT_INTERVIEW,
  MODE_DRILL,
  MODE_INTERVIEW,
  MODE_LEARN,
  interviewTargetForPersona,
  isInterviewMode,
  selfCheck,
  withPracticeMode,
} from "./practiceFlow.ts";

test("practice flow self-check passes", () => {
  selfCheck();
});

test("obvious persona names seed matching interview targets", () => {
  assert.equal(interviewTargetForPersona("Software Engineering Mentor"), "software_engineer");
  assert.equal(interviewTargetForPersona("AI/ML Coach"), "ai_ml_practitioner");
  assert.equal(interviewTargetForPersona("Cybersecurity Trainer"), "cybersecurity");
  assert.equal(interviewTargetForPersona("Product Manager Coach"), "product_manager");
  assert.equal(interviewTargetForPersona("GRC / Policy Advisor"), "grc_policy");
});

test("unknown persona names fall back to general professional", () => {
  assert.equal(interviewTargetForPersona("Voice Fluency Coach"), "general_professional");
  assert.equal(interviewTargetForPersona("My Saved Persona"), "general_professional");
});

test("switching into interview seeds target once from persona", () => {
  const next = withPracticeMode(DEFAULT_INTERVIEW, MODE_INTERVIEW, "Software Engineering Mentor");

  assert.deepEqual(next, { mode: MODE_INTERVIEW, role_key: "software_engineer" });
});

test("leaving interview keeps the last target but hides it in UI", () => {
  const next = withPracticeMode(
    { mode: MODE_INTERVIEW, role_key: "cybersecurity" },
    MODE_DRILL,
    "AI/ML Coach",
  );

  assert.deepEqual(next, { mode: MODE_DRILL, role_key: "cybersecurity" });
  assert.equal(isInterviewMode(next), false);
});

test("switching between non-interview modes does not rewrite role key", () => {
  const next = withPracticeMode(
    { mode: MODE_LEARN, role_key: "product_manager" },
    MODE_DRILL,
    "Cybersecurity Trainer",
  );

  assert.deepEqual(next, { mode: MODE_DRILL, role_key: "product_manager" });
});

test("re-entering interview keeps a user's explicit interview target", () => {
  const current = { mode: MODE_DRILL, role_key: "cybersecurity" };
  const next = withPracticeMode(current, MODE_INTERVIEW, "AI/ML Coach");

  assert.deepEqual(next, { mode: MODE_INTERVIEW, role_key: "cybersecurity" });
});
