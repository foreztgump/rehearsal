import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  AVATAR_UPDATE_MAX_RETRIES,
  retryTickForSend,
  shouldScheduleRetry,
} from "./avatarRetry.ts";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("F32: a new toggle resets the retry budget to 0", () => {
  // Budget exhausted on the previous target (tick at max, no success).
  const exhausted = AVATAR_UPDATE_MAX_RETRIES;
  // A NEW toggle (target changed) must start a fresh budget…
  assert.equal(retryTickForSend(exhausted, true), 0, "new toggle must reset the budget");
  // …so the very next failure is still allowed to schedule a retry.
  assert.equal(shouldScheduleRetry(retryTickForSend(exhausted, true)), true);
});

test("F32: a same-target retry keeps the running tick", () => {
  assert.equal(retryTickForSend(2, false), 2, "a retry of the same value keeps the tick");
});

test("F32: retries stop once the budget is spent on the same target", () => {
  assert.equal(shouldScheduleRetry(AVATAR_UPDATE_MAX_RETRIES), false);
  assert.equal(shouldScheduleRetry(AVATAR_UPDATE_MAX_RETRIES - 1), true);
});

test("F32: ApplyAvatarMode resets the retry budget when the target toggles", () => {
  // Source-inspection: the effect must derive THIS send's tick through the
  // helper (which collapses the budget to 0 for a new target), keyed on whether
  // the target changed — not only re-arm on a successful send.
  const src = read("./ApplyAvatarMode.tsx");
  assert.match(src, /from "\.\/avatarRetry"/, "must import the extracted retry helpers");
  assert.match(src, /retryTickForSend\(/, "must derive the send tick via retryTickForSend");
  assert.match(src, /shouldScheduleRetry\(/, "must gate the retry via shouldScheduleRetry");
});
