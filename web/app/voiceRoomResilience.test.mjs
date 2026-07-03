import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("G5: LiveKitRoom wires onDisconnected + onError for terminal-disconnect recovery", () => {
  const src = read("./VoiceRoom.tsx");

  // Without these, a terminal disconnect (server restart / network death past the
  // reconnect budget) leaves a dead TalkingScreen whose only recovery is End.
  assert.match(src, /onDisconnected=\{/, "must wire onDisconnected on <LiveKitRoom>");
  assert.match(src, /onError=\{/, "must wire onError on <LiveKitRoom>");

  // An unexpected disconnect must return to setup (drop the token) with a note,
  // not silently leave the room mounted. End/New are intentional teardowns and
  // must be distinguished so they don't masquerade as a lost connection.
  assert.match(src, /intentionalTeardownRef/, "must track intentional End/New teardown");
  assert.match(src, /DISCONNECT/, "must surface a terminal-disconnect message");
});

test("G5: intentional End/New teardown is flagged before dropping the token", () => {
  const src = read("./VoiceRoom.tsx");
  // The teardown flag must be set inside BOTH endSession and newSession, ahead of
  // their setToken(null), so the resulting onDisconnected is treated as expected.
  const endSession = src.match(/function endSession\(\)[\s\S]*?\n {2}\}/);
  const newSession = src.match(/function newSession\(\)[\s\S]*?\n {2}\}/);
  assert.ok(endSession, "endSession must exist");
  assert.ok(newSession, "newSession must exist");
  assert.match(endSession[0], /intentionalTeardownRef\.current = true/, "endSession flags teardown");
  assert.match(newSession[0], /intentionalTeardownRef\.current = true/, "newSession flags teardown");
});
