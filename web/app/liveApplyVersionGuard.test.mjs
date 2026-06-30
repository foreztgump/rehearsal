import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("live config updates are gated by same-session field versions", () => {
  const voiceRoom = read("./VoiceRoom.tsx");
  const talkingScreen = read("./TalkingScreen.tsx");
  const settingsDrawer = read("./SettingsDrawer.tsx");
  const panels = [
    read("./PersonaPanel.tsx"),
    read("./InterviewPanel.tsx"),
    read("./ModelPanel.tsx"),
  ].join("\n");

  assert.match(voiceRoom, /type LiveConfigField = "persona" \| "mode" \| "model"/);
  assert.match(voiceRoom, /liveApplyVersionRef = useRef\(\{ persona: 0, mode: 0, model: 0 \}\)/);
  assert.match(voiceRoom, /beginLiveConfigApply\(field: LiveConfigField\): number/);
  assert.match(voiceRoom, /version !== liveApplyVersionRef\.current\[field\]/);
  assert.match(talkingScreen, /onBeginConfigApply/);
  assert.match(settingsDrawer, /onBeginConfigApply\("persona"\)/);
  assert.match(settingsDrawer, /onBeginConfigApply\("mode"\)/);
  assert.match(settingsDrawer, /onBeginConfigApply\("model"\)/);
  assert.match(panels, /onApplyStart\?\.\(\) \?\? 0/);
  assert.match(panels, /onApplied\?\.\([^,\n]+, applyVersion\)/);
});

test("segmented controls can shrink within narrow panels", () => {
  const css = read("./globals.css");

  assert.match(css, /\.seg \{[\s\S]*?width: 100%;[\s\S]*?min-width: 0;/);
  assert.match(css, /\.seg button \{[\s\S]*?flex: 1 1 0;[\s\S]*?min-width: 0;/);
  assert.match(css, /\.seg button \{[\s\S]*?white-space: normal;/);
});
