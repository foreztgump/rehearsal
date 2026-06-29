# R5 Expressive Avatar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make avatar-on conversations feel like an expressive presenter and fix Path-B multi-sentence lip-sync anchoring.

**Architecture:** Keep the work in the existing avatar path. Extract only the pure lip-sync scheduling helpers so the Path-B bug has a no-DOM Node test; keep TalkingHead mood and gesture calls inside `AvatarStage.tsx`.

**Tech Stack:** Next.js 16, React 19, LiveKit components, vendored TalkingHead, TypeScript 6, Node 24 native test runner.

---

## File Structure

- Create `web/app/avatarPathB.ts`: pure word-to-viseme, schedule timeline, and Path-B anchoring helpers. No React, DOM, LiveKit, or TalkingHead imports.
- Create `web/app/avatarPathB.test.mjs`: Node native tests for the pure Path-B helpers. Imports `avatarPathB.ts` through Node 24 type stripping.
- Modify `web/app/AvatarStage.tsx`: import the helper functions, use continuous Path-B anchoring, map conversation state to mood, and trigger light speaking gestures.

No `package.json` changes. There is no frontend test dependency today, and Node 24 already has the needed built-in test runner.

---

### Task 1: Path-B Schedule Helper And Test

**Files:**
- Create: `web/app/avatarPathB.ts`
- Create: `web/app/avatarPathB.test.mjs`
- Modify: `web/app/AvatarStage.tsx`

- [ ] **Step 1: Write the failing Path-B test**

Create `web/app/avatarPathB.test.mjs`:

```js
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
```

- [ ] **Step 2: Run the test and verify it fails because the helper does not exist**

Run:

```bash
node --experimental-strip-types --test web/app/avatarPathB.test.mjs
```

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `web/app/avatarPathB.ts`.

- [ ] **Step 3: Add the pure Path-B helper**

Create `web/app/avatarPathB.ts`:

```ts
export type ScheduleWord = { w: string; s: number; e: number };
export type LipsyncSchedule = { seq: number; words: ScheduleWord[] };
export type VisemeSpan = { m: string; s: number; e: number };
export type QueuedSchedule = LipsyncSchedule & { timeline: VisemeSpan[] };
export type ActiveSchedule = { seq: number; timeline: VisemeSpan[]; anchor: number };
export type PathBInput = {
  active: ActiveSchedule | null;
  queue: QueuedSchedule[];
};
export type PathBStep = { now: number; audible: boolean };
export type PathBResult = PathBInput & { anchoredSeq: number | null };

const PATH_B_END_GRACE_SECONDS = 0.15;

export function wordToVisemes(word: string): string[] {
  const w = word.toLowerCase().replace(/[^a-z]/g, "");
  const out: string[] = [];
  let i = 0;
  const push = (m: string) => {
    if (out.length === 0 || out[out.length - 1] !== m) out.push(m);
  };

  while (i < w.length) {
    const two = w.slice(i, i + 2);
    if (two === "th") {
      push("viseme_TH");
      i += 2;
      continue;
    }
    if (two === "sh" || two === "ch") {
      push("viseme_CH");
      i += 2;
      continue;
    }
    if (two === "ph") {
      push("viseme_FF");
      i += 2;
      continue;
    }
    if (two === "ck") {
      push("viseme_kk");
      i += 2;
      continue;
    }
    if (two === "qu") {
      push("viseme_kk");
      push("viseme_U");
      i += 2;
      continue;
    }
    if (two === "wh") {
      push("viseme_U");
      i += 2;
      continue;
    }

    const c = w[i];
    i += 1;
    switch (c) {
      case "a":
        push("viseme_aa");
        break;
      case "e":
        push("viseme_E");
        break;
      case "i":
      case "y":
        push("viseme_I");
        break;
      case "o":
        push("viseme_O");
        break;
      case "u":
      case "w":
        push("viseme_U");
        break;
      case "m":
      case "b":
      case "p":
        push("viseme_PP");
        break;
      case "f":
      case "v":
        push("viseme_FF");
        break;
      case "t":
      case "d":
        push("viseme_DD");
        break;
      case "n":
      case "l":
        push("viseme_nn");
        break;
      case "k":
      case "g":
      case "c":
      case "q":
      case "x":
        push("viseme_kk");
        break;
      case "j":
        push("viseme_CH");
        break;
      case "s":
      case "z":
        push("viseme_SS");
        break;
      case "r":
        push("viseme_RR");
        break;
      default:
        break;
    }
  }

  return out.length === 0 ? ["viseme_aa"] : out;
}

export function scheduleToTimeline(words: ScheduleWord[]): VisemeSpan[] {
  const spans: VisemeSpan[] = [];
  for (const word of words) {
    const dur = Math.max(0, word.e - word.s);
    if (dur <= 0 || !word.w) continue;
    const visemes = wordToVisemes(word.w);
    const step = dur / visemes.length;
    for (let j = 0; j < visemes.length; j++) {
      spans.push({
        m: visemes[j],
        s: word.s + j * step,
        e: word.s + (j + 1) * step,
      });
    }
  }
  return spans;
}

export function queueSchedule(schedule: LipsyncSchedule): QueuedSchedule | null {
  const timeline = scheduleToTimeline(schedule.words);
  return timeline.length ? { ...schedule, timeline } : null;
}

export function advancePathB(input: PathBInput, step: PathBStep): PathBResult {
  const queue = input.queue.slice();
  let active = input.active;
  let anchor = step.now;

  if (active) {
    const end = active.anchor + timelineEnd(active.timeline);
    if (step.now > end + PATH_B_END_GRACE_SECONDS) {
      anchor = end;
      active = null;
    }
  }

  if (!active && step.audible && queue.length > 0) {
    const next = queue.shift()!;
    active = { seq: next.seq, timeline: next.timeline, anchor };
    return { active, queue, anchoredSeq: next.seq };
  }

  return { active, queue, anchoredSeq: null };
}

export function activeVisemeAt(
  active: ActiveSchedule | null,
  now: number,
): string | null {
  if (!active) return null;
  const t = now - active.anchor;
  if (t < 0 || t > timelineEnd(active.timeline) + PATH_B_END_GRACE_SECONDS) {
    return null;
  }
  for (const span of active.timeline) {
    if (t >= span.s && t < span.e) return span.m;
  }
  return null;
}

function timelineEnd(timeline: VisemeSpan[]): number {
  return timeline.length ? timeline[timeline.length - 1].e : 0;
}
```

- [ ] **Step 4: Run the helper test and verify it passes**

Run:

```bash
node --experimental-strip-types --test web/app/avatarPathB.test.mjs
```

Expected: PASS, with all five `avatarPathB.test.mjs` tests passing.

- [ ] **Step 5: Wire the helper into `AvatarStage.tsx`**

At the top of `web/app/AvatarStage.tsx`, add this import after the `avatarConfig` import:

```ts
import {
  activeVisemeAt,
  advancePathB,
  queueSchedule,
  type ActiveSchedule,
  type LipsyncSchedule,
  type QueuedSchedule,
} from "./avatarPathB";
```

Delete the local `ScheduleWord`, `LipsyncSchedule`, `VisemeSpan`, `wordToVisemes`, and `scheduleToTimeline` definitions. Keep `VISEME_MORPHS` in `AvatarStage.tsx`; the per-frame mouth writer still needs it.

Replace the Path-B refs with:

```ts
  const scheduleQueueRef = useRef<QueuedSchedule[]>([]);
  const activeRef = useRef<ActiveSchedule | null>(null);
  const lastSeqRef = useRef(-1);
```

Replace the successful schedule enqueue block inside `onLipsync` with:

```ts
      const queued = queueSchedule(obj);
      if (!queued) return;
      scheduleQueueRef.current.push(queued);
```

Replace the current audio-onset anchoring block in the rAF `tick` with:

```ts
        const audible = !mutedRef.current && rms > RMS_HI;
        const pathB = advancePathB(
          { active: activeRef.current, queue: scheduleQueueRef.current },
          { now: ctx.currentTime, audible },
        );
        activeRef.current = pathB.active;
        scheduleQueueRef.current = pathB.queue;
```

Replace the Path-B viseme selection block with:

```ts
        const scheduledViseme = activeVisemeAt(activeRef.current, ctx.currentTime);
        if (scheduledViseme) {
          target = scheduledViseme;
        } else if (!mutedRef.current && smooth > 0.06) {
```

Remove the now-unused `wasAudibleRef` declaration and reset line.

- [ ] **Step 6: Run tests and typecheck**

Run:

```bash
node --experimental-strip-types --test web/app/avatarPathB.test.mjs
npm --prefix web run typecheck
```

Expected:

- Node test: PASS.
- Typecheck: exits 0.

- [ ] **Step 7: Commit Task 1**

Run:

```bash
git add web/app/avatarPathB.ts web/app/avatarPathB.test.mjs web/app/AvatarStage.tsx
git commit -m "fix: anchor multi-sentence avatar lip-sync"
```

Expected: commit succeeds and only those three files are staged.

---

### Task 2: Presenter Mood And Light Gestures

**Files:**
- Modify: `web/app/AvatarStage.tsx`

- [ ] **Step 1: Extend the TalkingHead type**

In `TalkingHeadInstance`, add `speakWithHands`:

```ts
  speakWithHands: (delay?: number, prob?: number) => void;
```

- [ ] **Step 2: Add small mood and gesture helpers**

Add these constants and helper near the other top-level constants in `AvatarStage.tsx`:

```ts
const SPEAKING_GESTURE_INTERVAL_MS = 2600;
const SPEAKING_GESTURE_PROBABILITY = 0.35;

function moodForConversationState(state: string, restingMood: string): string {
  if (state === "speaking") return "happy";
  if (state === "listening" || state === "thinking") return "neutral";
  return restingMood;
}
```

- [ ] **Step 3: Track the applied mood**

After `const mutedRef = useRef(false);`, add:

```ts
  const activeMoodRef = useRef<string | null>(null);
```

After the initial `head.setMood(avatar.mood);` call in the mount effect, add:

```ts
        activeMoodRef.current = avatar.mood;
```

- [ ] **Step 4: Replace the persona-only mood effect with conversation-state mood**

Replace the existing effect headed `// --- Persona change: re-apply mood without reloading the head (AVTR-04). ---` with:

```ts
  // --- Conversation-state mood (R5): deterministic presenter expression. ---
  useEffect(() => {
    const head = headRef.current;
    if (!head || status !== "ready") return;

    const mood = moodForConversationState(state, avatar.mood);
    if (activeMoodRef.current === mood) return;

    try {
      head.setMood(mood);
      activeMoodRef.current = mood;
    } catch {
      /* non-fatal */
    }
  }, [avatar.mood, state, status]);
```

- [ ] **Step 5: Add light hand/arm gestures while speaking**

Add this effect after the mood effect:

```ts
  // --- Speaking gestures (R5): light presenter hand motion, no custom scheduler. ---
  useEffect(() => {
    const head = headRef.current;
    if (!head || status !== "ready" || state !== "speaking") return;

    let disposed = false;
    const gesture = () => {
      if (disposed) return;
      try {
        head.speakWithHands(0, SPEAKING_GESTURE_PROBABILITY);
      } catch {
        /* non-fatal */
      }
    };

    gesture();
    const interval = window.setInterval(gesture, SPEAKING_GESTURE_INTERVAL_MS);
    return () => {
      disposed = true;
      window.clearInterval(interval);
    };
  }, [state, status]);
```

- [ ] **Step 6: Run tests and typecheck**

Run:

```bash
node --experimental-strip-types --test web/app/avatarPathB.test.mjs
npm --prefix web run typecheck
```

Expected:

- Node test: PASS.
- Typecheck: exits 0.

- [ ] **Step 7: Commit Task 2**

Run:

```bash
git add web/app/AvatarStage.tsx
git commit -m "feat: add expressive presenter avatar motion"
```

Expected: commit succeeds and only `web/app/AvatarStage.tsx` is staged.

---

### Task 3: R5 Verification And Closeout Notes

**Files:**
- Modify: `.planning/ROADMAP.md`
- Create or modify: `.planning/v1.2-R5-VERIFY.md`

- [ ] **Step 1: Run sandbox verification**

Run:

```bash
node --experimental-strip-types --test web/app/avatarPathB.test.mjs
npm --prefix web run typecheck
python3 tests/test_captioned_gate.py
git diff --check
```

Expected:

- Node test: PASS.
- Typecheck: exits 0.
- Captioned gate test prints `ok: captioned gate truth table`.
- `git diff --check` prints nothing and exits 0.

- [ ] **Step 2: Rebuild the web image before the live smoke**

Run on the GPU host:

```bash
docker compose build web
./up.sh -d
docker compose ps
```

Expected:

- `web` image rebuild succeeds.
- The stack starts.
- `docker compose ps` shows `web`, `agent`, `livekit-server`, `ollama`, `kokoro`, and the selected STT service running or healthy.

- [ ] **Step 3: Manual avatar-on smoke**

Open `http://localhost:3000` in Chromium or Chrome and run this smoke:

```text
1. Turn Avatar mode ON.
2. Start talking.
3. Ask for a multi-sentence response, for example:
   "Give me two short sentences about why phishing training matters."
4. Confirm voice input reaches the agent and voice output returns.
5. Confirm the avatar shifts state while listening, thinking, and speaking.
6. Confirm light hand/arm gestures appear while the avatar speaks.
7. Confirm lip-sync stays aligned across both sentences.
```

Expected: full voice-to-voice flow works and avatar-on behavior reads as an expressive presenter.

- [ ] **Step 4: Measure only if smoke feels slow**

Run this step only if avatar-on first audio feels clearly slower than avatar-off.

```text
1. Turn Avatar mode OFF and do three short voice turns.
2. Turn Avatar mode ON and do the same three short voice turns.
3. Compare perceived first-audio delay.
4. If avatar ON is clearly slower, record it in R5 verification and scope the captioned-TTS streaming fix as follow-up.
```

Expected: no streaming rewrite is added during R5 unless this comparison shows a clear regression.

- [ ] **Step 5: Write R5 verification note**

Create `.planning/v1.2-R5-VERIFY.md`:

```md
---
title: v1.2 R5 Expressive Avatar Verification
status: closed-pending-user-acceptance
date: 2026-06-29
---

# v1.2 R5 - Expressive Avatar Verification

## Summary

R5 implemented the Expressive Presenter slice:

- conversation-state avatar moods
- light presenter hand/arm gestures while speaking
- Path-B multi-sentence lip-sync anchoring fix

Captioned-TTS streaming was not rewritten because the R5 design made it
measure-first fallback work.

## Sandbox Checks

- `node --experimental-strip-types --test web/app/avatarPathB.test.mjs`:
  PASS
- `npm --prefix web run typecheck`:
  PASS
- `python3 tests/test_captioned_gate.py`:
  PASS
- `git diff --check`:
  PASS

## Live Smoke

- Avatar ON full-stack voice-to-voice smoke:
  pending operator result
- Multi-sentence Path-B visual alignment:
  pending operator result
- Light hand/arm gesture visibility:
  pending operator result

## Deferred

- LLM emotion metadata
- local sentiment analysis
- Kokoro captioned-TTS streaming rewrite, unless avatar-on first-audio timing
  regresses
```

- [ ] **Step 6: Mark R5 closed after user acceptance**

After the user confirms the live smoke passes, update `.planning/v1.2-R5-VERIFY.md`:

```md
status: closed-smoke-accepted
```

Replace the `Live Smoke` section with:

```md
## Live Smoke

- Avatar ON full-stack voice-to-voice smoke:
  PASS by operator acceptance
- Multi-sentence Path-B visual alignment:
  PASS by operator acceptance
- Light hand/arm gesture visibility:
  PASS by operator acceptance
```

Update the R5 row in `.planning/ROADMAP.md` to:

```md
| R5 | Expressive avatar + word-accurate lip-sync hardening | req #36, **15b** | **closed 2026-06-29** by avatar-on expressive-presenter smoke and Path-B anchoring test |
```

- [ ] **Step 7: Commit Task 3**

Run:

```bash
git add .planning/v1.2-R5-VERIFY.md .planning/ROADMAP.md
git commit -m "docs: close r5 expressive avatar"
```

Expected: commit succeeds after user acceptance and only the R5 verification/roadmap files are staged.

---

## Final Verification Checklist

- [ ] `node --experimental-strip-types --test web/app/avatarPathB.test.mjs`
- [ ] `npm --prefix web run typecheck`
- [ ] `python3 tests/test_captioned_gate.py`
- [ ] `git diff --check`
- [ ] `docker compose build web`
- [ ] `./up.sh -d`
- [ ] Manual avatar-on full-stack smoke passes
- [ ] User accepts R5 closeout
