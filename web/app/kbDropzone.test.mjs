import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("F14: both KB dropzones handle drag/drop instead of navigating away", () => {
  const src = read("./KbPanel.tsx");

  // A file dropped on an element with no onDrop handler triggers the browser
  // default (navigate to the file), which unmounts the app and, in the live
  // path, tears down <LiveKitRoom> and ends the session. Both dropzones must
  // preventDefault on dragover AND route the dropped files through the existing
  // size-gated queue()/upload() paths.
  const dropzones = src.match(/className="dropzone"/g) ?? [];
  assert.equal(dropzones.length, 2, "expected exactly the two known dropzones");

  const dragOvers = src.match(/onDragOver=\{/g) ?? [];
  const drops = src.match(/onDrop=\{/g) ?? [];
  assert.equal(dragOvers.length, 2, "both dropzones must preventDefault on dragOver");
  assert.equal(drops.length, 2, "both dropzones must handle onDrop");

  // The drop handler must read dataTransfer.files and feed the existing paths.
  assert.match(src, /dataTransfer\.files/, "onDrop must read e.dataTransfer.files");
  assert.match(src, /queue\(e\.dataTransfer\.files\)/, "setup dropzone routes through queue()");
  assert.match(src, /upload\(e\.dataTransfer\.files\)/, "live dropzone routes through upload()");
});
