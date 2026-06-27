---
phase: 14
plan: 14-08
slug: theme-orb-ports-verify
depends_on: [14-02]
status: ready
kind: verify + one gap-closure
files_modified:
  - web/app/Visualizer.tsx       # AVTR-09 gap: wire real inbound audio level
requirements: [AVTR-09, UI-02]
---

# Plan 14-08 — Theme Orb Ports (Verify) + Audio-Reactivity Gap

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:executing-plans`. Read
> `14-00-STATE-AND-SEQUENCING.md` first. **All six orb renderers are already ported**
> (`web/app/Visualizer.tsx`) — this is a verification plan with **one** genuine
> gap-closure: the orb reacts to agent *state* but not yet to real inbound *audio
> level*, and AVTR-09 requires both. No web test runner — verify with `tsc --noEmit`
> + `npm run build` + manual.

**Goal:** Sign off that all six theme orbs render, react to agent state, handle
DPR/resize, and honor reduced-motion — and close the one AVTR-09 gap by driving the orb
level from the real agent audio track (not only the synthetic state envelope).

**Architecture (already in tree):** `Visualizer.tsx` holds six faithful renderers —
`drawHalo` (eclipse), `drawBloom` (nebula), `drawSonar` (sonar), `drawBlob` (ember),
`drawPrism` (prism), `drawAurora` (aurora) — selected by `getTheme(themeId).vizMode`.
One rAF loop, DPR-aware canvas, `ResizeObserver` on the parent, and a reduced-motion
branch that paints a single static frame. The level envelope is currently *synthetic*,
keyed to `useVoiceAssistant().state`.

**Tech Stack:** React 19, 2D canvas, `@livekit/components-react`
(`useVoiceAssistant` gives `{state, audioTrack}`), Web Audio `AnalyserNode`.

**Current state (vs PRD §2/§C):** PRD §6 scoped 14-08 to "port the other five orb
renderers" — **already done** (all six exist). The real remaining item is AVTR-09's
*audio*-reactivity: `Visualizer` uses `state` only; `audioTrack` is unused. `AvatarStage`
already demonstrates the inbound-track `AnalyserNode` → RMS pattern to mirror.

## Global Constraints
Inherit `14-00 §5`. Plan-specific: the orb is pure 2D canvas (no WebGL, no new dep) and
must stay out of the voice-only-vs-avatar concern (it's the voice-only hero); animate
only the bitmap; honor `prefers-reduced-motion` (single static frame).

---

## Task 1: Static verification — six renderers, theme mapping, build

**Files:** none.

- [ ] **Step 1: Confirm all six renderers + the theme→viz mapping**

Run:
```bash
cd web && grep -n "function draw" app/Visualizer.tsx          # expect 6 draw* fns
grep -n "RENDERERS = {" app/Visualizer.tsx                    # halo/bloom/sonar/blob/prism/aurora
grep -n "vizMode" app/ui/themes.ts                            # each of 6 themes maps to one
```
Expected: six `draw*` functions; `RENDERERS` maps all six `vizMode` keys; every theme
in `THEMES` declares a `vizMode` that exists in `RENDERERS` (halo, bloom, sonar, blob,
prism, aurora).

- [ ] **Step 2: Build is green**

Run: `cd web && npx tsc --noEmit && npm run build`
Expected: green.

---

## Task 2: Close the AVTR-09 gap — drive the orb from real inbound audio

**Files:**
- Modify: `web/app/Visualizer.tsx` (consume `audioTrack`; add an `AnalyserNode`; feed
  real RMS into `level` when the agent is speaking).

**Interfaces:**
- Consumes: `useVoiceAssistant().audioTrack` (the agent's published audio track).
- Produces: the orb's `level` tracks real speech amplitude when speaking; falls back to
  the synthetic envelope for listening/thinking/idle (no agent audio then).

- [ ] **Step 1: Pull `audioTrack` and add an analyser ref**

In `Visualizer.tsx`, extend the hook read and add refs:
```typescript
  const { state, audioTrack } = useVoiceAssistant();
  // …existing stateRef/themeRef…
  const analyserRef = useRef<AnalyserNode | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
```

- [ ] **Step 2: (Re)build the analyser when the audio track changes**

Add an effect (mirrors `AvatarStage`'s inbound-track analyser) that wires the agent
track into an `AnalyserNode` and tears it down on change/unmount:
```typescript
  useEffect(() => {
    const mediaTrack = audioTrack?.publication?.track?.mediaStreamTrack;
    if (!mediaTrack) return;
    let ctx: AudioContext | null = null;
    try {
      ctx = new AudioContext();
      const src = ctx.createMediaStreamSource(new MediaStream([mediaTrack]));
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      src.connect(analyser);
      audioCtxRef.current = ctx;
      analyserRef.current = analyser;
    } catch {
      // Web Audio unavailable / autoplay-locked: orb stays state-reactive (graceful).
      analyserRef.current = null;
    }
    return () => {
      analyserRef.current = null;
      audioCtxRef.current = null;
      ctx?.close().catch(() => {});
    };
  }, [audioTrack]);
```
(Confirm the exact path to the `MediaStreamTrack` on `audioTrack` against the installed
`@livekit/components-react@2.9.21` — it is a `TrackReference`; `AvatarStage` reads the
same thing. Adjust `?.publication?.track?.mediaStreamTrack` to the confirmed accessor.)

- [ ] **Step 3: Feed real RMS into `level` in the frame loop**

In the `frame` loop, compute a real level when speaking and an analyser exists, else
keep the synthetic envelope:
```typescript
      const analyser = analyserRef.current;
      let target: number;
      if (speaking && analyser) {
        const buf = new Uint8Array(analyser.fftSize);
        analyser.getByteTimeDomainData(buf);
        let sumSq = 0;
        for (let i = 0; i < buf.length; i++) {
          const v = (buf[i] - 128) / 128;
          sumSq += v * v;
        }
        const rms = Math.sqrt(sumSq / buf.length);
        target = Math.min(1, rms * 6); // gain so normal speech fills the orb
      } else {
        target = noisy; // the existing synthetic state envelope
      }
      level += (target - level) * 0.16;
```
(Replace the current `level += (noisy - level) * 0.16;` with the branch above, keeping
`noisy` defined exactly as today for the non-speaking / no-analyser path.)

- [ ] **Step 4: Typecheck + build**

Run: `cd web && npx tsc --noEmit && npm run build`
Expected: green.

- [ ] **Step 5: Manual — the orb pulses to the agent's actual voice**

`npm run dev`, voice-only. While the agent speaks, the orb's amplitude visibly tracks
the cadence of the *actual words* (louder syllables → bigger), not a uniform sine.
While listening/thinking/idle it still animates via the synthetic envelope. Reduced-
motion still paints one static frame.

- [ ] **Step 6: Commit**

```bash
cd .. && git add web/app/Visualizer.tsx
git commit -m "feat(14-08): drive the voice-only orb from real inbound audio level (AVTR-09)"
```

---

## Task 3: Manual verification — six themes × state × resize × reduced-motion

**Files:** none.

- [ ] **Step 1: Every theme's orb renders**

Voice-only. Cycle all six themes (`ThemeDots`). Expected: each shows its distinct orb
(eclipse halo arcs, nebula petals, sonar rings+bars, ember blob, prism ribbons, aurora
bands), recolored to the theme, no flicker on switch.

- [ ] **Step 2: State reactivity across the four agent states**

Drive a conversation. Expected: the orb reads differently in listening / thinking /
speaking / idle (amplitude + motion change with `useVoiceAssistant().state`), and
speaking now tracks real audio (Task 2).

- [ ] **Step 3: DPR + resize**

Resize the window / stage (chrome-devtools `resize_page`) and check a HiDPI display.
Expected: the canvas stays crisp (DPR scale) and square (`aspectRatio 1/1`,
`ResizeObserver` re-fits), no blur or stretch.

- [ ] **Step 4: Reduced-motion + no console errors**

Emulate `prefers-reduced-motion: reduce`: the orb paints one static resting frame (no
rAF churn). Across the whole flow, `list_console_messages` shows zero errors.

- [ ] **Step 5: Record sign-off**

Append a verification record: six renderers PASS, audio+state reactivity PASS (AVTR-09),
DPR/resize PASS, reduced-motion PASS, console clean. Note the PRD §6 correction (the
five "remaining ports" were already done; the real work was AVTR-09 audio-reactivity).

- [ ] **Step 6: Commit the record**

```bash
git add .planning/phases/14-release-polish-conversation-feel-ui-avatar-lifecycle/14-08-theme-orb-ports-verify-PLAN.md
git commit -m "docs(14-08): sign six-orb verification + AVTR-09 audio-reactivity"
```

## Verification
- `cd web && npx tsc --noEmit && npm run build` green.
- All six orbs render + recolor per theme; react to agent state; speaking tracks real
  audio amplitude; DPR/resize crisp+square; reduced-motion static; zero console errors.

## Artifacts this plan produces
- **MODIFIED** `web/app/Visualizer.tsx` — real inbound-audio reactivity (AVTR-09).
- A **signed verification record** (in this file) for the six orbs + UI-02 theme parity.
