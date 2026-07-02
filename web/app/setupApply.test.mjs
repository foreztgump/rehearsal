import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { ackApplied, agentReadyForApply } from "./setupApply.ts";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("F13: agent is ready to apply only in a live post-start state", () => {
  for (const live of ["listening", "thinking", "speaking"]) {
    assert.equal(agentReadyForApply(live), true, `${live} must be ready`);
  }
});

test("F13: agent is NOT ready before session.start publishes a live state", () => {
  for (const pre of [undefined, "", "initializing", "connecting", "disconnected"]) {
    assert.equal(agentReadyForApply(pre), false, `${String(pre)} must not be ready`);
  }
});

test("F13: only an 'applied' ack counts as success", () => {
  assert.equal(ackApplied("applied"), true);
  assert.equal(ackApplied("error"), false);
  assert.equal(ackApplied(""), false);
  assert.equal(ackApplied("ok"), false);
});

test("F13: ApplySetupOnConnect gates on state, checks acks, and guards after success", () => {
  const src = read("./ApplySetupOnConnect.tsx");
  assert.match(src, /from "\.\/setupApply"/, "must import the readiness/ack helpers");
  assert.match(src, /agentReadyForApply\(\s*state\s*\)/, "must gate on the live agent state");
  assert.match(src, /ackApplied\(/, "must check the RPC ack, not just transport errors");
  // The once-guard must be set INSIDE a success branch, not immediately on entry.
  assert.match(
    src,
    /if \(allOk\)[\s\S]*?applied\.current = true/,
    "once-guard must only be set after all sends succeed",
  );
});
