---
phase: 14
plan: 14-00
slug: state-and-sequencing
kind: overview
status: ready
---

# Plan 14-00 — Actual State, Corrected Scope & Sequencing

> **For agentic workers:** This is the orientation document for the nine Phase-14
> plans (`14-01`…`14-09`). Read it before executing any of them. It records where
> the codebase has already moved past the PRD's §2 "Current State," so each plan
> targets the *real* remaining work — not a greenfield rebuild of work that is
> already in `master`.

**Why this exists:** the Phase-14 PRD was authored during brainstorming (2026-06-27)
on a snapshot that predates commit `e5f9389 feat(ui): redesign landing/talking
screens with runtime theme switcher` plus the uncommitted working-tree changes to
`agent/main.py`, `web/app/AvatarStage.tsx`, `web/app/avatarConfig.ts`, and the new
`agent/captioned_tts.py`. Several PRD problem statements are therefore stale. The
nine plans below were written against a fresh code read (file + line verified), not
the PRD's narrative.

---

## 1. Actual state vs PRD §2 (verified by file read)

| PRD §2 claim | Reality in the tree | Consequence for the plan |
|---|---|---|
| "v4 design language + switchable themes are not implemented." | **Built.** `web/app/ui/tokens.ts` is CSS-variable-driven; `web/app/globals.css` carries all six `[data-theme]` palettes (lines 35–166), the ambient backdrop (28s/32s, lines 189–243), grain (SVG `fractalNoise` 0.025, line 245), the frosted topbar (`backdrop-filter`, line 589), and a `prefers-reduced-motion` block (832). `web/app/ui/ThemeProvider.tsx` persists to `localStorage` (`adept.theme`) SSR-safely; `web/app/ThemeDots.tsx` is the picker, mounted in `SetupScreen` and `SettingsDrawer`. Default = `eclipse-aurora`. | **14-02 is a verify-and-close-gaps plan, not a build.** |
| "Build eclipse first; the other five are ports… a curated subset can ship." | **All six already ported.** `web/app/Visualizer.tsx` has `drawHalo/drawBloom/drawSonar/drawBlob/drawPrism/drawAurora`, state-reactive via `useVoiceAssistant`, with DPR + `ResizeObserver` + a reduced-motion static frame. | **14-08 is a verify plan, not a port.** |
| "Lip-sync Path-B is *already drafted but unwired*." | **Wired.** `agent/captioned_tts.py` exists; `CaptionedTTS` is the session TTS (`agent/main.py:233-236`) and is `attach_room`'d (`386-387`). The Path-B viseme scheduler is live in `AvatarStage.tsx`. | **14-04 is the inverse of the PRD: the work is *gating it OFF* for voice-only, not wiring it on.** Today voice-only is **not** byte-for-byte identical — the agent always hits `/dev/captioned_speech` and always publishes `lk.avatar.lipsync`. |
| "Avatar doesn't fill its stage (fixed 360px)." | Already fluid: `TalkingScreen.tsx:97` is `height:100%; minHeight:320px`. | **14-03 drops the fluid-fill task; idle-fix + responsive framing remain real.** |
| "Avatar looks 'lost' when idle… zeros *all* mouth morphs." | **Real and unfixed.** `AvatarStage.tsx:677-692` pins `mouthOpen` + every `VISEME_MORPHS` entry to `0` via the `realtime` tier whenever `state !== "speaking"`. | **14-03 idle-fix is real.** |
| "Endpointing… ships a CONVERSATIONAL profile but never uses it… pinned to the INTERVIEW floor." | **Confirmed.** `agent/main.py:107-108` pins `ENDPOINTING_*` to the INTERVIEW constants; the CONVERSATIONAL constants (78-79) are dead. | **14-01 is real and is the headline plan.** |
| "Session lifecycle + graceful failure unbuilt." | **Confirmed.** `onLeave` only does `setToken(null)` (`VoiceRoom.tsx`). No reset/end teardown, no transcript export, no mic-denied prompt, no garbled-finalize gate (`NemoSTT._emit_final` emits empty text unfiltered). | **14-06 is real.** |
| "Install is manual; no `install.sh`, no `down.sh`." | **Confirmed** (both absent; `up.sh`, `scripts/gpu-doctor.sh`, `ollama/pull-and-pin.sh` exist). | **14-07 is real.** |

**Net:** the genuinely-unbuilt work is **14-01, 14-03 (idle + framing), 14-04 (the
OFF-gate), 14-05, 14-06, 14-07, 14-09**. **14-02 and 14-08 are verification.**

---

## 2. Corrected per-plan scope

- **14-01 — Conversation feel retune** *(build)*. Mode-aware endpointing via a pure
  `endpointing_for_mode()` selector; VAD / interrupt / STT-chunk / lookahead retune
  to named, documented constants.
- **14-02 — v4 design + theme system** *(verify + small gaps)*. Prove the built
  system: build, typecheck, six themes apply + persist, reduced-motion, no console
  errors setup→talk. Close only genuine gaps (drawer parity, theme-as-a-preference).
- **14-03 — Voice/avatar stage** *(build: idle + framing; verify: orb)*. Release the
  `realtime` mouth tier on non-speaking states (idle micro-expressions resume);
  responsive `head.setView()` by breakpoint; verify the orb.
- **14-04 — Word-accurate lip-sync gate** *(build)*. Introduce an avatar-on flag
  (`avatar.update` RPC + participant signal); `CaptionedTTS` publishes timestamps
  **only when on**; voice-only path emits no schedule channel; Path-A fallback;
  document the Phase-12 isolation-gate retirement.
- **14-05 — Persona + avatar presets** *(build)*. Frontend preset table
  (persona ↔ voice ↔ mood ↔ GLB, default GLB reused), setup chooser pre-filling the
  still-editable persona fields.
- **14-06 — Session lifecycle + graceful failure** *(build)*. SESS-01..04 +
  REL-01/02, with a teardown audit checklist.
- **14-07 — Install bootstrap + clean stop** *(build)*. `install.sh` + `down.sh` +
  README, PATH-shim tested like `scripts/test_gpu_doctor.sh`.
- **14-08 — Theme orb ports** *(verify)*. Prove all six renderers + reduced-motion.
- **14-09 — Latency verification + release gate** *(runbook)*. PERF-04 + discharge
  the pending 9/10/11 operator gates on the RTX 5090.

---

## 3. Execution order & dependencies

```
14-01  (agent/STT only — no UI dep)            ── independent, do first
14-02  (verify themes)                          ── independent
14-08  (verify orbs)                            ── independent (pairs with 14-02)
14-03  (idle + framing)  ── depends on 14-02 (theme/orb harness already exists)
14-04  (lipsync OFF-gate) ── depends on 14-03 (touches AvatarStage + main.py TTS)
14-05  (presets)         ── depends on 14-02 (setup-screen surface)
14-06  (lifecycle)       ── independent of A–E; touches main.py + several web files
14-07  (install)         ── independent
14-09  (release gate)    ── LAST; depends on 14-01 (tuned STT) + 14-04 (the gate
                            is what makes "voice-only zero-VRAM / no-regression" true)
```

Recommended pass order: **14-01 → 14-02 → 14-08 → 14-03 → 14-04 → 14-05 → 14-06 →
14-07 → 14-09**.

---

## 4. Cross-plan interfaces (the shared seams)

These are the only contracts that span plan boundaries. Keep the names identical
across the plans that touch them.

- **`avatar.update` RPC (introduced by 14-04).** Method name `"avatar.update"`,
  payload `{"on": boolean}`, returns `"applied"`/`"error"` — mirrors the existing
  `mode.update`/`model.update` handler shape (`agent/main.py`). Frontend sends it
  from the avatar toggle (`VoiceRoom`/`TalkingScreen`) and from
  `ApplySetupOnConnect` (initial state). **14-03 must not also add an avatar signal**
  — it consumes nothing here; 14-04 owns this seam.
- **`avatarOn` frontend state** already lives in `SessionConfig.avatarOn`
  (`VoiceRoom.tsx`) and flows to `TalkingScreen` via the existing
  `onToggleAvatar`. 14-04 taps this same state to drive the new RPC; it does **not**
  add a second source of truth.
- **Theme/orb harness (owned by the existing `Visualizer.tsx` + `ui/themes.ts`).**
  14-03/14-05/14-08 read `getTheme()`, `THEMES`, `useTheme()` — they do not
  re-architect the theme registry.
- **`endpointing_for_mode(mode)` (introduced by 14-01, `agent/main.py`).** Pure
  function returning `{"mode","min_delay","max_delay"}`. 14-06's reset/end handlers
  must not reset mode in a way that bypasses it.
- **Persona apply path (unchanged).** 14-05 presets and 14-06 reset both reuse the
  existing `persona.update` RPC and `current_persona[0]` holder — no new persona RPC.

---

## 5. Global constraints (apply to every Phase-14 plan)

Copied verbatim from the PRD + `CODE_PRINCIPLES.md`; every task inherits these.

- **Local-first (hard).** No audio/transcript/KB leaves the LAN; no cloud inference;
  keep the local `MultilingualModel` turn detector (never the cloud
  `inference.TurnDetector`).
- **Latency is the design driver.** Named budgets are constants, never inline
  numbers: EOU ≤300ms, STT ≤150ms, LLM TTFT ≤300ms (`agent/metrics.py:BUDGET_MS`).
  Never add blocking work between STT-final and the first TTS sentence without
  measuring TTFT.
- **Voice-only isolation is the new auditable invariant** (replaces the Phase-12
  frontend-only gate): with Avatar OFF, `git diff` of the server pipeline behaviour
  is empty and no `lk.avatar.*` data channel is published. Avatar ON *may* touch the
  server pipeline (captioned TTS) — documented, intentional (14-04).
- **Code quality (hard):** SRP, no magic values (named constants), descriptive
  names, error handling on every boundary, ≤40 lines / ≤3 params / ≤3 nesting,
  no >5-line duplication, YAGNI, Law of Demeter. AAA tests.
- **Conventions:** Python `snake_case`; TS/React `camelCase`/`PascalCase`.
  Conventional Commits. Pin image tags (never `:latest`). Branch before committing
  if on the default branch. Commit/push only when the user asks.
- **Boundaries that always need error handling:** mic-permission denial, empty/
  garbled STT, KB upload/parse failure, Ollama/Kokoro/Whisper sidecar unreachable,
  LiveKit disconnect.

---

## 6. Test infrastructure reality (so plans don't fabricate runners)

- **Python (`agent/`, `stt/`, `tests/`):** no pytest dependency required; the repo
  uses **pure-stdlib `__main__` self-check harnesses** run directly:
  `python3 tests/test_placement.py`, `python3 agent/metrics.py`,
  `python3 stt/test_dispatch.py`. New agent logic gets a real failing-test → pass
  cycle in this style (sandbox-safe: no livekit/GPU import at module top).
- **Shell (`scripts/`):** PATH-shim scenario tests (`scripts/test_gpu_doctor.sh`)
  plus `bash -n` syntax checks. `install.sh`/`down.sh` follow this pattern.
- **Web (`web/`):** **no test runner** (`package.json` has only `dev`/`build`/
  `start`). Web tasks verify with `npx tsc --noEmit` + `npm run build` + explicit
  manual/console checks. Plans do **not** invent Jest/Vitest — adding a web test
  runner is out of scope (YAGNI).

---

## 7. Operator-gated items (cannot be self-signed)

14-09 and the PERF/STT gates need the RTX 5090. Where a plan's acceptance depends on
real GPU hardware, it is marked **OPERATOR** and deferred to 14-09's runbook; the
self-checkable parts (build green, server-diff empty, pure-function tests) are signed
in-plan.
