import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("F33: SettingsDrawer exports the End-confirm copy for single-sourcing", () => {
  const src = read("./SettingsDrawer.tsx");
  assert.match(src, /export const END_CONFIRM/, "END_CONFIRM must be exported to share the copy");
});

test("F33: the top-bar End is gated by a two-step confirm, not a direct destroy", () => {
  const src = read("./TalkingScreen.tsx");

  // The top-bar End must not call onEnd directly on first click — it must arm a
  // confirm first, mirroring SettingsDrawer's deliberate two-step for the same
  // destructive action.
  assert.doesNotMatch(
    src,
    /className="btn-ghost danger"\s+onClick=\{onEnd\}/,
    "top-bar End must not destroy the session with zero confirmation",
  );
  assert.match(src, /confirmEnd/, "must track a two-step confirm state");
  assert.match(src, /END_CONFIRM/, "must reuse the shared End-confirm copy");
  // A confirm affordance actually calls onEnd; the initial button only arms it.
  assert.match(src, /onClick=\{onEnd\}/, "the confirm step calls onEnd");
  assert.match(src, /setConfirmEnd\(true\)/, "the first click arms the confirm");
});
