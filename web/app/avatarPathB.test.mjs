import assert from "node:assert/strict";
import test from "node:test";
import {
  activeVisemeAt,
  advancePathB,
  queueSchedule,
  scheduleToTimeline,
} from "./avatarPathB.ts";

test("scheduleToTimeline splits real word timing into viseme spans", () => {
  const timeline = scheduleToTimeline([{ w: "cat", s: 0.2, e: 0.8 }]);

  assert.deepEqual(
    timeline.map((span) => span.m),
    ["viseme_kk", "viseme_aa", "viseme_DD"],
  );
  assert.equal(timeline[0].s, 0.2);
  assert.equal(timeline.at(-1).e, 0.8);
});

test("advancePathB anchors the first schedule on audible audio", () => {
  const first = queueSchedule({ seq: 1, words: [{ w: "hello", s: 0, e: 0.4 }] });

  assert.ok(first);

  const result = advancePathB(
    { active: null, queue: [first] },
    { now: 10, audible: true },
  );

  assert.equal(result.anchoredSeq, 1);
  assert.equal(result.active?.seq, 1);
  assert.equal(result.active?.anchor, 10);
  assert.equal(result.queue.length, 0);
});

test("advancePathB chains the next sentence without a silence gap", () => {
  const first = queueSchedule({ seq: 1, words: [{ w: "hello", s: 0, e: 0.4 }] });
  const second = queueSchedule({ seq: 2, words: [{ w: "again", s: 0, e: 0.3 }] });

  assert.ok(first);
  assert.ok(second);

  const started = advancePathB(
    { active: null, queue: [first, second] },
    { now: 10, audible: true },
  );
  const chained = advancePathB(
    { active: started.active, queue: started.queue },
    { now: 10.56, audible: true },
  );

  assert.equal(chained.anchoredSeq, 2);
  assert.equal(chained.active?.seq, 2);
  assert.equal(chained.active?.anchor, 10.4);
  assert.equal(chained.queue.length, 0);
});

test("advancePathB waits while audio is silent", () => {
  const first = queueSchedule({ seq: 1, words: [{ w: "hello", s: 0, e: 0.4 }] });

  assert.ok(first);

  const result = advancePathB(
    { active: null, queue: [first] },
    { now: 10, audible: false },
  );

  assert.equal(result.anchoredSeq, null);
  assert.equal(result.active, null);
  assert.equal(result.queue.length, 1);
});

test("activeVisemeAt returns the scheduled viseme for the current audio time", () => {
  const queued = queueSchedule({ seq: 1, words: [{ w: "go", s: 0, e: 0.4 }] });

  assert.ok(queued);

  const active = { seq: queued.seq, timeline: queued.timeline, anchor: 5 };

  assert.equal(activeVisemeAt(active, 5.05), "viseme_kk");
  assert.equal(activeVisemeAt(active, 6), null);
});
