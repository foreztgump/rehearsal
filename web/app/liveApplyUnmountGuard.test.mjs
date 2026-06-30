import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const panels = ["PersonaPanel.tsx", "InterviewPanel.tsx", "ModelPanel.tsx"];

test("live settings panels ignore apply acknowledgements after unmount", () => {
  for (const panel of panels) {
    const source = readFileSync(new URL(panel, import.meta.url), "utf8");

    assert.match(source, /useRef/);
    assert.match(source, /const mounted = useRef\(true\);/);
    assert.match(source, /mounted\.current = false;/);
    assert.match(source, /await room\.localParticipant\.performRpc[\s\S]*if \(!mounted\.current\) return;/);
  }
});
