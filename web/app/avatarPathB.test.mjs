import assert from "node:assert/strict";
import test from "node:test";
import {
  acceptScheduleSequence,
  activeVisemeAt,
  advancePathB,
  queueSchedule,
  scheduleToTimeline,
} from "./avatarPathB.ts";
import {
  applySpeakingGazeLock,
  TALKINGHEAD_SPEAKING_BEHAVIOR,
  TALKINGHEAD_SPEAKING_GAZE_LOCKS,
} from "./avatarConfig.ts";

test("scheduleToTimeline splits real word timing into viseme spans", () => {
  const timeline = scheduleToTimeline([{ w: "cat", s: 0.2, e: 0.8 }]);

  assert.deepEqual(
    timeline.map((span) => span.m),
    ["viseme_kk", "viseme_aa", "viseme_DD"],
  );
  assert.equal(timeline[0].s, 0.2);
  assert.equal(timeline.at(-1).e, 0.8);
});

test("queueSchedule rejects malformed boundary fields", () => {
  assert.equal(
    queueSchedule({ seq: NaN, words: [{ w: "cat", s: 0, e: 0.4 }] }),
    null,
  );
  assert.equal(
    queueSchedule({ seq: 1, words: [{ w: "cat", s: NaN, e: 0.4 }] }),
    null,
  );
  assert.equal(
    queueSchedule({ seq: 1, words: [{ w: 123, s: 0, e: 0.4 }] }),
    null,
  );
});

test("queueSchedule drops malformed word timing from queued schedules", () => {
  const queued = queueSchedule({
    seq: 1,
    words: [
      { w: "bad", s: NaN, e: 0.2 },
      { w: "ok", s: 0, e: 0.3 },
      { w: "bad", s: 0.3, e: Infinity },
    ],
  });

  assert.ok(queued);
  assert.deepEqual(queued.words, [{ w: "ok", s: 0, e: 0.3 }]);
  assert.equal(queued.timeline.at(-1).e, 0.3);
});

test("acceptScheduleSequence allows seq reset on a new request_id", () => {
  const first = queueSchedule({
    seq: 4,
    request_id: "old",
    words: [{ w: "old", s: 0, e: 0.2 }],
  });
  const restarted = queueSchedule({
    seq: 1,
    request_id: "new",
    words: [{ w: "new", s: 0, e: 0.2 }],
  });

  assert.ok(first);
  assert.ok(restarted);

  const afterFirst = acceptScheduleSequence(
    { requestId: null, lastSeq: -1 },
    first,
    true,
  );

  assert.deepEqual(afterFirst, { requestId: "old", lastSeq: 4 });
  assert.equal(acceptScheduleSequence(afterFirst, first, true), null);
  assert.deepEqual(acceptScheduleSequence(afterFirst, restarted, true), {
    requestId: "new",
    lastSeq: 1,
  });
});

test("acceptScheduleSequence rejects late schedules while not speaking", () => {
  const late = queueSchedule({
    seq: 5,
    request_id: "interrupted",
    words: [{ w: "late", s: 0, e: 0.2 }],
  });

  assert.ok(late);
  assert.equal(
    acceptScheduleSequence({ requestId: null, lastSeq: -1 }, late, false),
    null,
  );
});

test("queueSchedule neutralizes an unknown mood", () => {
  const queued = queueSchedule({
    seq: 1,
    mood: "furious",
    words: [{ w: "hi", s: 0, e: 0.2 }],
  });

  assert.ok(queued);
  assert.equal(queued.mood, "neutral");
});

test("queueSchedule defaults a missing mood to neutral and keeps a valid one", () => {
  const missing = queueSchedule({ seq: 1, words: [{ w: "hi", s: 0, e: 0.2 }] });
  const sad = queueSchedule({
    seq: 1,
    mood: "sad",
    words: [{ w: "hi", s: 0, e: 0.2 }],
  });

  assert.ok(missing);
  assert.ok(sad);
  assert.equal(missing.mood, "neutral");
  assert.equal(sad.mood, "sad");
});

test("advancePathB carries the schedule mood onto the anchored active", () => {
  const sad = queueSchedule({
    seq: 1,
    mood: "sad",
    words: [{ w: "hello", s: 0, e: 0.4 }],
  });

  assert.ok(sad);

  const result = advancePathB(
    { active: null, queue: [sad] },
    { now: 10, audible: true },
  );

  assert.equal(result.anchoredSeq, 1);
  assert.equal(result.active?.mood, "sad");
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

test("speaking avatar holds eye contact and faces the user (no head turns)", () => {
  // While speaking the trainer looks straight and holds eye contact: eye contact is
  // biased ON and the gaussian head-TURN probability is 0 (turns are what break eye
  // contact mid-sentence). Both the head-rotate and eye-rotate axes are gaze-locked so
  // the head faces forward; the volume-synced neck bob is independent of these morphs,
  // so the head still reads as alive rather than frozen.
  assert.equal(TALKINGHEAD_SPEAKING_BEHAVIOR.avatarSpeakingEyeContact, 1);
  assert.equal(TALKINGHEAD_SPEAKING_BEHAVIOR.avatarSpeakingHeadMove, 0);
  assert.deepEqual(TALKINGHEAD_SPEAKING_GAZE_LOCKS, [
    ["headRotateX", 0],
    ["headRotateY", 0],
    ["headRotateZ", 0],
    ["eyesRotateX", 0],
    ["eyesRotateY", 0],
  ]);
});

test("applySpeakingGazeLock fixes and releases the head + eye targets", () => {
  const calls = [];
  const head = {
    setFixedValue(mt, val) {
      calls.push([mt, val]);
    },
  };

  applySpeakingGazeLock(head, true);
  applySpeakingGazeLock(head, false);

  assert.deepEqual(calls, [
    ["headRotateX", 0],
    ["headRotateY", 0],
    ["headRotateZ", 0],
    ["eyesRotateX", 0],
    ["eyesRotateY", 0],
    ["headRotateX", null],
    ["headRotateY", null],
    ["headRotateZ", null],
    ["eyesRotateX", null],
    ["eyesRotateY", null],
  ]);
});
