import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  invalidateLiveApplyVersions,
  nextLiveApplyVersion,
  shouldApplyLiveConfig,
} from "./liveApplyVersions.ts";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("live apply acks stay valid across close without reopen", () => {
  const currentEpoch = 7;
  const initial = { persona: 0, mode: 0, model: 0 };
  const apply = nextLiveApplyVersion(initial, "persona");

  assert.equal(
    shouldApplyLiveConfig(
      currentEpoch,
      currentEpoch,
      apply.versions,
      "persona",
      apply.version,
    ),
    true,
  );
});

test("settings reopen invalidates old acks without blocking new applies", () => {
  const currentEpoch = 7;
  const initial = { persona: 0, mode: 0, model: 0 };
  const firstApply = nextLiveApplyVersion(initial, "persona");
  const reopened = invalidateLiveApplyVersions(firstApply.versions);
  const secondApply = nextLiveApplyVersion(reopened, "persona");

  assert.equal(
    shouldApplyLiveConfig(
      currentEpoch,
      currentEpoch,
      secondApply.versions,
      "persona",
      firstApply.version,
    ),
    false,
  );
  assert.equal(
    shouldApplyLiveConfig(
      currentEpoch,
      currentEpoch,
      secondApply.versions,
      "persona",
      secondApply.version,
    ),
    true,
  );
});

test("segmented controls can shrink within narrow panels", () => {
  const css = read("./globals.css");

  assert.match(css, /\.seg \{[\s\S]*?width: 100%;[\s\S]*?min-width: 0;/);
  assert.match(css, /\.seg button \{[\s\S]*?flex: 1 1 0;[\s\S]*?min-width: 0;/);
  assert.match(css, /\.seg button \{[\s\S]*?white-space: normal;/);
});
