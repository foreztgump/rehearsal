---
phase: 14
plan: 14-03
slug: voice-avatar-stage
depends_on: [14-02]
status: ready
files_modified:
  - web/app/AvatarStage.tsx     # idle-fix (release morph tier) + responsive setView
  - web/app/avatarConfig.ts     # viewForWidth() + breakpoint constants
  - web/app/TalkingScreen.tsx   # verify fluid-fill (already done) — change only if gap
requirements: [AVTR-10, AVTR-11]
---

# Plan 14-03 — Voice/Avatar Stage: Idle Fix + Responsive Framing

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:executing-plans`. Read
> `14-00-STATE-AND-SEQUENCING.md` first. The voice-only orb is already done — its
> verification lives in **14-08**, not here (DRY). This plan does the two genuinely
> unbuilt pieces: the **idle-freeze fix** and **responsive avatar framing**. No web
> test runner exists (`package.json` has only `dev`/`build`/`start`) — verify with
> `tsc --noEmit` + `npm run build` + manual browser checks (`chrome-devtools` MCP).

**Goal:** Make the avatar read as *engaged* when the agent isn't speaking (idle
micro-expressions, breathing, blink, gaze run — no frozen mouth), and reframe the
avatar responsively (head → upper → half-body) by viewport.

**Architecture:** The freeze is a morph-tier priority bug. TalkingHead drives idle
mouth morphs (`mouthPucker/mouthStretch*/mouthRoll*`) on its `newvalue` animation
tier; `AvatarStage` pins the **higher-priority `realtime` tier** to `0` for
`mouthOpen` + every viseme whenever the agent isn't speaking, which overrides idle and
freezes the mouth. Fix: **release** the realtime tier (`realtime = null`) on
non-speaking states instead of pinning it to `0`, so idle shows through — while still
clearing the active lip-sync schedule (barge-in preserved). For framing, call the
runtime `head.setView('head'|'upper'|'full')` on breakpoint crossings; TalkingHead's
own `ResizeObserver` already handles canvas/aspect resize.

**Tech Stack:** React 19, vendored TalkingHead (`web/public/vendor/talkinghead/
talkinghead.mjs`), `setView` at line 1424, `mtAvatar[mt].realtime` tier.

**Current state (vs PRD §2):** Fluid-fill is **already done** (`TalkingScreen.tsx:97`
= `height:100%; minHeight:320px`, not a fixed 360px) — verify, don't rebuild. The idle
zeroing (`AvatarStage.tsx:677-692`) and the static `CAMERA_VIEW="upper"`
(`avatarConfig.ts:7`) are real and unfixed.

## Global Constraints
Inherit `14-00 §5`. Plan-specific: keep the avatar dynamic-import (`ssr:false`) +
importmap contract; voice-only bundle must stay free of 3D deps; graceful degradation
(WebGL-unavailable → existing fallback) preserved; target ~30fps.

---

## Task 1: Idle-freeze fix — release the morph tier instead of zeroing it

**Files:**
- Modify: `web/app/AvatarStage.tsx` (the `setRealtime` helper 53-59; the state-change
  effect 670-692; the Path-A tick muted path ~510-608).

**Interfaces:**
- Produces: `releaseRealtime(head, mt)` helper; non-speaking states no longer pin the
  mouth — TalkingHead idle animations resume.

- [ ] **Step 1: Add a `releaseRealtime` helper next to `setRealtime`**

In `web/app/AvatarStage.tsx`, just below the existing `setRealtime` (lines 53-59), add:
```typescript
// Release a morph's realtime override so TalkingHead's own animation tiers (idle
// micro-expressions, mood baseline) drive it again. Setting realtime = null (NOT 0)
// is the fix for the "frozen mouth" idle bug: 0 pins the high-priority realtime tier
// shut and overrides the lib's idle mouthPucker/Stretch/Roll loop; null yields it.
function releaseRealtime(head: TalkingHeadInstance, mt: string) {
  const o = head.mtAvatar[mt];
  if (o) {
    o.realtime = null;
    o.needsUpdate = true;
  }
}
```
(`MorphTier.realtime` is already typed `number | null` at line 39 — no type change.)

- [ ] **Step 2: Release (don't zero) in the state-change effect**

In the effect at ~670-692, keep the barge-in schedule cleanup but swap the zeroing for
release. Replace the `try { setRealtime(head,"mouthOpen",0); for (…) setRealtime(…,0) }`
block with:
```typescript
      // Barge-in / turn end: drop the active word schedule (a stale timeline must not
      // replay against the next utterance) AND release the mouth morphs so idle
      // micro-expressions resume — do NOT pin them to 0 (that froze the mouth).
      activeRef.current = null;
      scheduleQueueRef.current = [];
      wasAudibleRef.current = false;
      try {
        releaseRealtime(head, "mouthOpen");
        for (const v of VISEME_MORPHS) releaseRealtime(head, v);
      } catch {
        /* non-fatal */
      }
```

- [ ] **Step 3: Release + skip the lip-sync drive in the Path-A tick when muted**

In the rAF `tick` (~510-608), add an early guard at the top of the body (right after
the `const h = headRef.current; if (!h || disposed) return;` lines) so a muted turn
yields the mouth to idle instead of writing 0 every frame:
```typescript
        if (mutedRef.current) {
          // Not the agent's turn: release the realtime mouth tier so the lib's idle
          // animation shows, reset the envelope so the next onset starts closed, and
          // skip the energy/viseme drive entirely this frame.
          releaseRealtime(h, "mouthOpen");
          for (const key of VISEME_MORPHS) releaseRealtime(h, key);
          smooth = 0;
          raf = requestAnimationFrame(tick);
          return;
        }
```
Leave the speaking path (envelope + Path-B/Path-A viseme selection + the per-frame
zeroing of *non-active* visemes) unchanged — zeroing inactive visemes **while
speaking** is correct and must stay.

- [ ] **Step 4: Typecheck + build**

Run:
```bash
cd web && npx tsc --noEmit && npm run build
```
Expected: green (no type errors; `releaseRealtime` resolves; build completes).

- [ ] **Step 5: Manual — idle reads as engaged**

`npm run dev`, start a session with Avatar ON, and let the agent sit idle (not
speaking). Expected: the mouth shows subtle idle motion (pucker/stretch/roll) plus
breathing, blinking, and gaze — **not** a frozen-open or frozen-shut mouth. Then speak:
the agent's reply still lip-syncs; when you barge in, the mouth stops lip-syncing and
returns to idle (not a stuck shape).

- [ ] **Step 6: Commit**

```bash
cd .. && git add web/app/AvatarStage.tsx
git commit -m "fix(14-03): release morph realtime tier on idle so micro-expressions resume (AVTR-11)"
```

---

## Task 2: Responsive avatar framing via runtime `setView`

**Files:**
- Modify: `web/app/avatarConfig.ts` (add `viewForWidth` + breakpoint constants)
- Modify: `web/app/AvatarStage.tsx` (extend `TalkingHeadInstance` type with `setView`;
  apply the view at mount + on breakpoint crossing)

**Interfaces:**
- Consumes: `head.setView(view)` (vendored TalkingHead runtime API, line 1424).
- Produces: `viewForWidth(width) -> "head"|"upper"|"full"`; avatar reframes by viewport.

- [ ] **Step 1: Add the pure framing selector + breakpoints to `avatarConfig.ts`**

Append to `web/app/avatarConfig.ts` (it is dependency-free/pure — keep it that way):
```typescript
// Responsive framing (AVTR-10). The default GLB is a half-body model; frame tighter
// on small viewports so the face stays readable. TalkingHead views: head < upper <
// mid < full. Mobile → head; tablet → upper (head-and-shoulders); desktop → full
// (half-body). Pure helper so the breakpoints are named, not magic.
export const AVATAR_VIEW_MOBILE_MAX_PX = 600;
export const AVATAR_VIEW_TABLET_MAX_PX = 1024;

export function viewForWidth(width: number): "head" | "upper" | "full" {
  if (width <= AVATAR_VIEW_MOBILE_MAX_PX) return "head";
  if (width <= AVATAR_VIEW_TABLET_MAX_PX) return "upper";
  return "full";
}
```

- [ ] **Step 2: Teach the `TalkingHeadInstance` type about `setView`**

In `web/app/AvatarStage.tsx`, add to the `TalkingHeadInstance` type (lines 39-49):
```typescript
  setView: (view: string, opt?: Record<string, number> | null) => void;
```

- [ ] **Step 3: Import the selector**

Add `viewForWidth` to the existing `avatarConfig` import in `AvatarStage.tsx`:
```typescript
import { /* …existing… */ viewForWidth } from "./avatarConfig";
```

- [ ] **Step 4: Apply the view at mount + on breakpoint crossing**

In the mount effect, after `head.showAvatar(...)` and `head.setMood(...)` succeed (the
load block ~314-401), add a breakpoint-aware view applier that only re-frames when the
bucket actually changes (so a drag-resize doesn't spam camera animations):
```typescript
        // Responsive framing (AVTR-10). TalkingHead's own ResizeObserver already
        // handles canvas/aspect; we only switch the VIEW bucket by breakpoint.
        let lastView = "";
        const applyView = () => {
          const next = viewForWidth(window.innerWidth);
          if (next !== lastView) {
            lastView = next;
            head.setView(next);
          }
        };
        applyView();
        window.addEventListener("resize", applyView);
        viewCleanupRef.current = () => window.removeEventListener("resize", applyView);
```
Declare `const viewCleanupRef = useRef<(() => void) | null>(null);` near the other
refs, and call `viewCleanupRef.current?.()` in the component's existing dispose/cleanup
return (alongside `head.dispose()`), so the listener is removed on unmount.

- [ ] **Step 5: Typecheck + build**

Run: `cd web && npx tsc --noEmit && npm run build`
Expected: green.

- [ ] **Step 6: Manual — framing reflows by viewport**

`npm run dev`, Avatar ON. Resize (chrome-devtools `resize_page`) across 375 → 768 →
1280px. Expected: ≤600px frames the head; 601–1024px frames head-and-shoulders;
>1024px frames the half-body. No clipping; the avatar stays centered and fills the
stage section.

- [ ] **Step 7: Commit**

```bash
cd .. && git add web/app/AvatarStage.tsx web/app/avatarConfig.ts
git commit -m "feat(14-03): responsive avatar framing via runtime setView by breakpoint (AVTR-10)"
```

---

## Task 3: Verify fluid-fill + full-stage manual sign-off

**Files:**
- Modify: `web/app/TalkingScreen.tsx` **only if** a fill gap is found (expected: none).

- [ ] **Step 1: Confirm fluid-fill is already satisfied**

Run:
```bash
cd web && grep -n "minHeight\|height: \"100%\"" app/TalkingScreen.tsx
```
Expected: line 97 shows `height:"100%"` + `minHeight:"320px"` inside a `1fr` grid row
when `showAvatar` — i.e. already fluid, no fixed 360px. If (and only if) the avatar
visibly fails to fill on desktop, raise `minHeight` or set the wrapper to `flex:1`;
otherwise make no change.

- [ ] **Step 2: Manual — idle + framing + perf together**

With Avatar ON: confirm (a) idle reads engaged (Task 1), (b) framing reframes (Task 2),
(c) ~30fps under a `chrome-devtools` performance trace during a spoken reply,
(d) zero console errors across toggle Avatar OFF→ON→OFF, (e) WebGL-blocked fallback
still degrades gracefully (force-disable WebGL and confirm no crash).

- [ ] **Step 3: Record sign-off**

Append a verification record to this plan file: idle (AVTR-11) PASS, framing (AVTR-10)
PASS, fluid-fill confirmed, fps + console + degradation observations. Commit:
```bash
cd .. && git add .planning/phases/14-release-polish-conversation-feel-ui-avatar-lifecycle/14-03-voice-avatar-stage-PLAN.md
git commit -m "docs(14-03): sign avatar idle + responsive-framing verification"
```

## Verification (summary)
- `cd web && npx tsc --noEmit && npm run build` green.
- Idle (Avatar ON, agent not speaking): mouth shows idle micro-expressions + breathing
  + blink + gaze — not frozen. Barge-in returns the mouth to idle, not a stuck shape.
- Framing: head ≤600px, upper ≤1024px, full >1024px; reframes on resize.
- Fluid-fill confirmed (no fixed 360px). ~30fps; no console errors; graceful WebGL
  degradation preserved.

## Artifacts this plan produces
- **MODIFIED** `web/app/AvatarStage.tsx` — `releaseRealtime` idle fix; responsive
  `setView` wiring; `TalkingHeadInstance.setView` type.
- **MODIFIED** `web/app/avatarConfig.ts` — `viewForWidth()` + named breakpoints.
- **(Verify only)** `web/app/TalkingScreen.tsx` — fluid-fill confirmed; orb verified in 14-08.
