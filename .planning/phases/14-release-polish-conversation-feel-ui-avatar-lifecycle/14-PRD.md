# Phase 14 PRD — Release Polish: Conversation Feel, v4 UI/UX, Avatar & Lifecycle

**Status:** Draft (brainstorming approved 2026-06-27)
**Milestone:** v1.1 — Local-First Pipeline Swap + Avatar
**Phase:** 14 (renamed from "Deferred v1.0 Polish, Optimization & Pre-Release Hardening")
**Depends on:** Phase 13 (UI/UX overhaul — setup-before-connect shell + talking screen)
**Mode:** ui + mvp (mixed)
**Supersedes:** the unstarted v1.0 Phase 7 (SESS/REL/latency scope folded in here)

> **Phase split (decided 2026-06-27):** the original Phase-14 "optimization & hardening" scope is split. **Phase 14 = the felt-quality release polish** (this document). The two heavy infrastructure swings — **sub-8GB VRAM mode** and **AMD GPU support** — move to a new fast-follow **Phase 15 — "Broaden Hardware Reach"** (captured in §11). Phase 14 is the last phase before the v1.1 release; Phase 15 broadens the hardware story immediately after.

---

## 1. Goal & Core Value

Make the shipped v1.1 pipeline *feel* live and look finished.

**Core value (unchanged):** the user holds a natural spoken conversation with a credible expert persona at voice-to-voice latency that feels live (P50 < 1.0s) — practicing speaking a domain out loud.

Phase 14 closes the gap between "the pipeline works" and "the product feels finished":

1. **Fix the conversational regression** introduced by the Whisper→NeMo swap (sluggish replies, missed interrupts, dropped opening words).
2. **Land the v4 design language** with user-switchable themes (eclipse-aurora default).
3. **Make the avatar fill its stage, animate naturally, and lip-sync to actual words.**
4. **Complete session lifecycle + graceful-failure handling** (the carried v1.0 polish).
5. **Ship a one-command install** with a clean start/stop story.
6. **Sign the latency release gate** (PERF-04) on real hardware.

---

## 2. Background & Current State

**Shipped:** v1.0-rc1 (Phases 1–6) and v1.1 Phases 8–13:
- Phase 8: two user-selectable Ollama LLMs (Fast E2B / Better E4B), in-place tag swap.
- Phase 9: faster-whisper replaced by NeMo Nemotron streaming STT behind a local WS server.
- Phase 10: VRAM-aware STT placement (GPU-NeMo vs CPU-ONNX), resolved once at session start.
- Phase 11: `docker compose up` consumer-GPU deployment + advise-only `gpu-doctor.sh`.
- Phase 12: optional frontend-only 3D TalkingHead avatar with Path-A energy/formant lip-sync.
- Phase 13: setup-before-connect shell (SetupScreen → TalkingScreen → SettingsDrawer), auto-scroll transcript, shared design tokens.

**Known issues entering Phase 14 (from code review during brainstorming):**

- **Conversation feel regressed.** `agent/main.py` ships a CONVERSATIONAL endpointing profile (`min_delay 0.3s`/`max_delay 3.0s`, lines ~78–79) **but never uses it** — the single active profile is pinned to the INTERVIEW floor (`min_delay 0.7s`/`max_delay 5.0s`, lines ~82–83, applied at ~281–293). On top of that the NeMo path adds latency/robustness knobs Whisper didn't have: STT `STREAM_CHUNK_MS=560` (`stt/server.py:75`), autonomous `ENDPOINT_SILENCE_MS=700` (`stt/server.py:90`), `att_context_size` lookahead (deployed `[56,3]` via `.env.example`; code fallback `[70,6]` at `stt/backend_nemo.py:78`), VAD `activation_threshold=0.65` (`agent/main.py:312`), and interrupt `min_duration=0.3` (`agent/main.py:288–292`). These stack into "longer pause before reply," "interrupt didn't register," and "dropped the words I said."
- **Avatar looks "lost" when idle.** `AvatarStage.tsx` (~670–691) zeros *all* mouth morphs whenever the agent is not speaking — which also kills TalkingHead's built-in idle micro-expressions, freezing the mouth while eyes/head keep moving (uncanny).
- **Avatar doesn't fill its stage.** The avatar region is a fixed `360px` height (`TalkingScreen.tsx:110`); framing is static `cameraView="upper"` (`avatarConfig.ts:7`).
- **Voice-only mode shows no visualization** — the stage is empty unless Avatar is on. The v4 mockups fill it with an animated orb.
- **Lip-sync is approximate.** Path-A (energy + formant) is consonant-blind. A word-accurate Path-B path is *already drafted but unwired*: `agent/captioned_tts.py` (pulls word timestamps from Kokoro `/dev/captioned_speech`, publishes on `lk.avatar.lipsync`) and the frontend Path-B viseme scheduler in `AvatarStage.tsx` (~94–223, 530–557).
- **Session lifecycle + graceful failure unbuilt.** SettingsDrawer "Leave session" is explicitly "no room teardown yet (Phase 14)." No reset/end teardown, no transcript export, no mic-denied prompt, no garbled-transcription reprompt.
- **Install is manual.** `up.sh` + advise-only `gpu-doctor.sh` exist; there is **no** `install.sh`, **no** `down.sh`, and model pull (`ollama/pull-and-pin.sh`) is a manual post-`up` step.

---

## 3. Scope

### In scope (Phase 14)

A. Conversation feel retune (endpointing, VAD, barge-in, STT chunk/lookahead).
B. v4 design language + six-theme system (eclipse-aurora default), switchable on setup.
C. Voice/avatar stage: orb (voice-only), responsive 3D avatar framing, fluid-fill, idle fix.
D. Word-accurate lip-sync via `captioned_tts` (avatar-on only).
E. Persona + avatar presets (reusing the default GLB initially) with a setup chooser.
F. Session lifecycle (new/reset/end + full ephemeral teardown) + transcript export.
G. Graceful failure (mic-permission-denied prompt; empty/garbled-transcription reprompt).
H. Install bootstrap (`install.sh`) + clean stop (`down.sh`) + start/stop docs.
I. Latency verification + release gate (PERF-04) and discharge of pending 9/10/11 operator gates.

### Out of scope (deferred to Phase 15 — "Broaden Hardware Reach")

- Sub-8GB VRAM mode (one small LLM warm, gray out E4B under threshold, add tiny models to the picker, unload-on-swap / keep-alive + lean KV/context).
- AMD GPU support (Ollama-ROCm + Whisper STT + Kokoro-ROCm + `rocm-smi` doctor + `/dev/kfd`+`/dev/dri`).

### Explicitly NOT in this release

- Per-persona distinct avatar GLBs (presets reuse the default GLB; per-persona avatars are a later drop-in — no architecture change required).
- Public hosting URL for the `curl | sh` one-liner (`install.sh` ships in-repo and is `curl|sh`-compatible; the hosted URL is a flip once the repo is published).
- Changing the persona prompt (still the sole content guardrail; abliterated-model risk remains accepted per Phase 8).
- Multilingual STT, in-browser TTS, webcam capture, cross-session persistence (unchanged v1.1 exclusions).

---

## 4. Workstreams

### Workstream A — Conversation Feel *(highest priority)*

**Problem:** the pipeline feels slower and less interruptible than the Whisper era.

**Design:**
- **Mode-aware endpointing.** Use the existing CONVERSATIONAL profile (`~0.3s` min_delay) for normal Converse mode and the INTERVIEW profile (`~0.7s`) for Interview mode, switched by the existing mode toggle with no session teardown (`agent/main.py` endpointing dict). The deliberate floor stays *only* where it belongs (long interview answers).
- **Barge-in & dropped-words retune.** Empirically tune, against the felt regression:
  - VAD `activation_threshold` (currently 0.65) — lower if speech onsets are missed; balance against open-mic false triggers.
  - interrupt `min_duration` (0.3s) and `resume_false_interruption` behavior so real interrupts reliably cancel TTS.
  - STT `STREAM_CHUNK_MS` (560ms) and `att_context_size` right-context (`[56,3]`) so the start of an utterance isn't buffered away and finalize stays snappy.
  - autonomous `ENDPOINT_SILENCE_MS` (700ms) vs the turn-detector flush — avoid premature/late finals.
- **Document the tuned values** with rationale so they're not silently regressed.

**Files:** `agent/main.py` (endpointing, VAD, interruption), `stt/server.py` (chunk/silence), `stt/backend_nemo.py` + `.env.example` (att_context_size), `agent/metrics.py` (validate against budgets).

**Success:** normal chat feels as responsive as the Whisper era; interrupts reliably cut TTS; opening words are not swallowed; interview mode keeps its patience; no metric regression beyond the intended interview `eou` allowance.

### Workstream B — v4 UI/UX + Theme System

**Problem:** Phase 13 delivered structure on a single GitHub-dark token set; the v4 design language and switchable themes are not implemented.

**Design:**
- **Apply the v4 design language** over the Phase-13 structure: ambient backdrop (two drifting radial gradients, 28–32s), grain texture (SVG fractal-noise ~0.025 opacity), frosted-glass top bar (`backdrop-filter`), refined typography/shadows. Add as app-wide layers (`globals.css` + a layout wrapper).
- **Theme system.** Six themes selectable on the setup screen, **eclipse-aurora default**: `eclipse-aurora` (jade), `nebula-bloom` (magenta), `sonar-pulse` (cyan), `liquid-ember` (amber), `prism-wave` (purple), `aurora-veil` (rose). A theme = a palette (token override) + an orb renderer (Workstream C). Persist the choice as a user preference (localStorage). Respect `prefers-reduced-motion`.
- **Refactor tokens** (`web/app/ui/tokens.ts`) from a locked palette into a theme-parameterized set (CSS custom properties), so palette swaps are instant and component code is palette-agnostic.
- **Build eclipse first**; the other five are ports of the existing mockup canvas draw-loops (`design-mockups/v4/*.html`), so a curated subset can still ship if time-constrained.

**Files:** `web/app/ui/tokens.ts`, `web/app/globals.css`, `web/app/layout.tsx`, new theme module + a theme picker in `SetupScreen.tsx` (and optionally `SettingsDrawer.tsx`).

**Success:** consistent, polished, animated UI matching v4; theme switch is instant and persists; reduced-motion respected; no console errors through setup→talk.

### Workstream C — Voice/Avatar Stage

**Problem:** voice-only is visually empty; the avatar is a fixed 360px crop; idle looks "lost."

**Design:**
- **Orb (voice-only).** A canvas orb fills the stage in voice-only mode, reactive to **both** inbound audio level **and** agent state (`useVoiceAssistant().state`: listening/thinking/speaking/idle). Each theme provides its orb variant via a shared canvas/RAF/DPR harness (one renderer interface, six draw implementations ported from the mockups).
- **Responsive 3D avatar (avatar mode).** Reframe by viewport: head (mobile) → upper/head-and-shoulders (tablet) → half-body (desktop) via TalkingHead `cameraView`; make the stage fluid-height so it fills the section (replace the fixed `360px`). The default GLB is already a half-body model.
- **Idle fix.** Stop zeroing all mouth morphs when the agent isn't speaking. Separate "mute lip-sync during the user's turn" (keep, for barge-in) from "freeze the whole mouth" (remove), so TalkingHead's idle micro-expressions (mouthPucker/Stretch/Roll), breathing, blink, and gaze read as attentive rather than dazed.

**Files:** `web/app/AvatarStage.tsx`, `web/app/avatarConfig.ts`, `web/app/TalkingScreen.tsx`, new orb renderer module(s).

**Success:** voice-only feels alive and on-theme; the avatar fills its stage and reframes responsively; idle reads as engaged, not frozen; ~30fps maintained, graceful degradation preserved.

### Workstream D — Word-Accurate Lip-Sync

**Problem:** Path-A energy/formant lip-sync is consonant-blind and approximate.

**Design:**
- **Wire `agent/captioned_tts.py`** as the agent TTS so Kokoro word-level timestamps publish on `lk.avatar.lipsync`; the frontend Path-B viseme scheduler consumes them.
- **Scope the blast radius:** Path-B is active **only when Avatar is ON**. Voice-only / Avatar-OFF stays byte-for-byte identical (stock TTS path, no schedule channel). Fall back to Path-A energy if timestamps are unavailable for an utterance.
- **Retire the Phase-12 isolation gate explicitly:** the avatar now *may* touch the server pipeline (captioned TTS), documented as an intentional, avatar-on-only relaxation. Voice-only isolation is preserved and is the new auditable invariant.
- **No server VRAM / identical audio:** captioned TTS reuses the existing Kokoro service (it only adds a word-timestamp request + a data-channel publish), so it adds **zero** server VRAM and the synthesized audio is identical to the stock path — consistent with PERF-04.

**Files:** `agent/captioned_tts.py` (wire into `agent/main.py` session build, behind an avatar/captioned flag), `web/app/AvatarStage.tsx` (Path-B already present; verify anchoring + Path-A fallback).

**Success:** with Avatar on, lip-sync visibly tracks words (consonants/vowels), not just energy; voice-only path unchanged; missing timestamps degrade to Path-A without breakage.

### Workstream E — Persona + Avatar Presets

**Problem:** only the default cyber-trainer persona + one avatar ship; no chooser.

**Design:**
- **Preset library:** a small set of persona presets, each mapping persona text ↔ Kokoro voice ↔ avatar mood ↔ avatar GLB. Seed set aligned to the existing domains: **Cybersecurity Trainer** (default) + the interview roles already supported (**SOC Analyst**, **Security Engineer**, **GRC**), optionally a general **Domain Expert**.
- **Chooser** on the setup screen; selecting a preset pre-fills the (still live-editable) persona fields, voice, and mood.
- **Assets:** all presets **reuse the existing default GLB** initially (distinct voice/mood per persona). Per-persona avatars are a later drop-in (no architecture change). This sidesteps per-GLB sourcing/licensing for the release.

**Files:** persona/preset config (frontend preset table + `web/app/avatarConfig.ts`), `web/app/PersonaPanel.tsx` / `SetupScreen.tsx` (preset chooser), agent persona apply path (unchanged RPC).

**Success:** the user picks a preset in setup and starts talking to it; presets remain fully editable; switching presets applies persona+voice+mood live; default GLB used throughout.

### Workstream F — Session Lifecycle + Graceful Failure *(carried v1.0 polish)*

**Design:**
- **SESS-01 new session / SESS-02 reset (clear context, same session) / SESS-03 end.** End performs a **full ephemeral teardown audit** clearing: KB brief, conversation history, transcript, model choice, STT decoder cache, and any avatar GLB — and tears the LiveKit room down cleanly (wire the SettingsDrawer "Leave session" two-step to real teardown → return to setup without a broken state).
- **SESS-04 transcript export:** client-side download (txt + md), speaker labels + timestamps, no server round-trip.
- **REL-01 mic-permission-denied:** a clear, actionable prompt (how to grant), no silent failure.
- **REL-02 garbled/empty finalized transcription:** the agent reprompts ("didn't catch that") instead of generating a response to noise (built on the Part-B finalize).

**Files:** `web/app/VoiceRoom.tsx`, `web/app/SettingsDrawer.tsx`, `web/app/TalkingScreen.tsx`, `web/app/Transcript.tsx` (export), `agent/main.py` (reset/end RPCs + decoder-cache reset, empty/garbled gate), `agent/nemo_stt.py` (garbled detection hook).

**Success:** all three lifecycle actions work and leave no ephemeral residue; transcript exports correctly; mic denial and garbled audio both produce clear, non-silent behavior.

### Workstream G — Install Bootstrap + Lifecycle

**Design:**
- **`install.sh`** (ships in-repo, `curl | sh`-compatible): detect OS + Docker/Compose + GPU vendor → scaffold `.env` with an **auto-generated `LIVEKIT_API_SECRET`** → print a **setup plan** (services, GPU/CPU placement, VRAM budget) and **ask for confirmation** → build images + first-run model pull (`ollama/pull-and-pin.sh`) → print exact **start/stop** commands. When Docker/driver/toolkit are missing, **guide** the user with the right per-OS commands (don't auto-install).
- **`down.sh`** + documented clean stop (`docker compose down`), surfaced by the installer's closing message.

**Files:** new `install.sh`, new `down.sh`, `up.sh` (align), `scripts/gpu-doctor.sh` (reuse detection), `README.md` (install/start/stop), `.env.example`.

**Success:** a new user runs one script, confirms a plan, and ends up with a running stack and clear start/stop instructions; a missing prerequisite yields an actionable message, not a hang.

### Workstream H — Latency Verification + Release Gate

**Design:**
- **PERF-04:** sign P50 < 1.0s / P95 < 1.5s for **both** LLM choices with the retuned STT leg; confirm the STT finalize leg trends toward sub-100ms; confirm Avatar mode adds **no** latency regression and **zero** server VRAM (voice-only byte-for-byte identical).
- Use the final tuning pass to also **discharge the pending operator GPU gates** from Phases 9/10/11 (STT correctness, placement co-residency matrix, deployment doctor) on the RTX 5090.

**Files:** `agent/metrics.py` (P50/P95 readout), `scripts/vram-validate.sh`, the 9/10/11 `*-VERIFY.md` runbooks.

**Success:** PERF-04 signed on real hardware; pending gates signed or explicitly re-deferred with reason.

---

## 5. Requirements

### New

**FEEL — Conversation Feel**
- **FEEL-01:** Endpointing is mode-aware — Converse uses a snappy profile (~0.3s min_delay), Interview uses a deliberate one (~0.7s), switched by the existing mode toggle with no session teardown.
- **FEEL-02:** Barge-in is reliable and openings aren't dropped — VAD/interrupt/STT-chunk/lookahead knobs are tuned so interrupts consistently cancel TTS and the start of an utterance is transcribed; tuned values documented.

**UI — v4 Design & Themes**
- **UI-01:** The v4 design language (ambient backdrop, grain, frosted glass, typography, shadows) is applied app-wide over the Phase-13 structure.
- **UI-02:** Six themes are selectable on the setup screen (eclipse-aurora default), each a palette + orb renderer; the choice persists; `prefers-reduced-motion` is respected.
- **UI-03:** The UI is responsive (mobile→desktop) and accessible (keyboard-navigable primary actions, focus-visible), with no console errors across setup→connect→talk.

**AVTR — Avatar (extends Phase 12)**
- **AVTR-09:** In voice-only mode an audio- and agent-state-reactive orb fills the stage (per the active theme).
- **AVTR-10:** Avatar mode reframes responsively (head→upper→half-body by viewport) and the stage fluid-fills its section (no fixed height).
- **AVTR-11:** Idle reads as engaged — built-in idle micro-expressions run; lip-sync is muted only during the user's turn (barge-in preserved), not frozen wholesale.
- **AVTR-12:** Lip-sync is word-accurate via captioned-TTS Path-B when Avatar is ON; Voice-only / Avatar-OFF stays byte-for-byte unchanged; Path-A energy is the fallback when timestamps are unavailable. The Phase-12 frontend-only isolation gate is documented as intentionally retired (avatar-on only).
- **AVTR-13:** A persona+avatar preset library is selectable on setup (persona↔voice↔mood↔avatar), presets remain live-editable, and presets reuse the default GLB initially.

**DEPLOY — Install (extends Phase 11)**
- **DEPLOY-06:** An install bootstrap (`install.sh`, `curl|sh`-compatible) detects OS/Docker/GPU, scaffolds `.env` with an auto-generated secret, shows a plan and confirms, builds + pulls models, and prints start/stop — guiding (not auto-installing) missing prerequisites.
- **DEPLOY-07:** A clean stop path (`down.sh` + documented `docker compose down`) is provided and surfaced to the user.

### Carried (from v1.0 Phase 7 / v1.1 REQUIREMENTS.md)
- **SESS-01:** start a new session.
- **SESS-02:** reset the current session (cleared context, same session).
- **SESS-03:** end the session, clearing all ephemeral state (KB brief, history, transcript, model choice, decoder cache, avatar GLB).
- **SESS-04:** export/download the session transcript (txt/md, speaker labels + timestamps, no server round-trip).
- **REL-01:** clear, actionable mic-permission-denied prompt (no silent failure).
- **REL-02:** empty/garbled finalized transcription → reprompt instead of responding to noise.
- **PERF-04:** P50 < 1.0s / P95 < 1.5s for both LLMs with the new STT leg; avatar adds no latency regression and zero server VRAM.

---

## 6. Suggested Sequencing (plans)

Dependency-ordered; each is a candidate plan for `/gsd-plan-phase 14`.

1. **14-01 Conversation feel retune** (A) — highest value, mostly agent/STT config; verify against the felt regression and metrics. *No UI dependency.*
2. **14-02 v4 design language + theme system** (B) — token refactor + ambient/grain/frosted layers + theme picker + eclipse orb. Foundation for C/E.
3. **14-03 Voice/avatar stage: orb + responsive framing + idle fix** (C) — depends on 14-02's theme/orb harness.
4. **14-04 Word-accurate lip-sync** (D) — wire captioned_tts; avatar-on only; Path-A fallback. Depends on 14-03.
5. **14-05 Persona + avatar presets** (E) — setup chooser; depends on 14-02 setup-screen work.
6. **14-06 Session lifecycle + graceful failure** (F, G-partial) — SESS-01..04, REL-01/02.
7. **14-07 Install bootstrap + clean stop** (G) — install.sh/down.sh + README.
8. **14-08 Remaining theme ports** (B-tail) — port the other five orb renderers (can interleave/parallel after 14-03 if time allows).
9. **14-09 Latency verification + release gate** (H) — PERF-04 + discharge 9/10/11 operator gates on the RTX 5090.

> Eclipse-first ordering means a curated-subset of themes can ship if time runs short (14-08 is the compressible tail).

---

## 7. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Six audio/state-reactive orb renderers × screen sizes × reduced-motion is a large QA surface | Theme polish slips | Eclipse-first; shared canvas/RAF/DPR harness; the other five are ports of working mockup code; 14-08 is the compressible tail |
| Feel retune is empirical and hardware-dependent | Over/under-tuned endpointing | Tune on the target GPU against the actual felt regression; document values + metrics; keep mode-aware split so interview patience is preserved |
| captioned_tts adds a Kokoro `/dev/captioned_speech` dependency | Lip-sync breaks if endpoint/timestamps change | Strictly avatar-on-gated; Path-A energy fallback per-utterance; voice-only path untouched |
| Persona presets imply per-GLB licensing | Asset/legal drag | Reuse the default GLB for all presets now; per-persona avatars deferred (no arch change) |
| PERF-04 + 9/10/11 gates need real GPU | Release can't be signed without hardware | Operator (RTX 5090) signs during 14-09; document any re-deferral with reason |
| Session "end" must clear *all* ephemeral state | Privacy/state leak across sessions | Explicit teardown audit checklist (KB, history, transcript, model choice, decoder cache, avatar GLB) verified |

---

## 8. Verification & Release Gates

- **Automated/self-check:** agent + web build green; no console errors across setup→connect→talk; reduced-motion honored; voice-only-vs-avatar server diff empty except the documented avatar-on captioned-TTS path.
- **Operator GPU gates (RTX 5090):** PERF-04 (P50<1.0s/P95<1.5s both LLMs; avatar no-regression/zero-VRAM); plus discharge of the pending Phase 9 (STT correctness/finalize), Phase 10 (placement co-residency matrix), and Phase 11 (deployment doctor) runbooks.
- **UAT:** conversation-feel A/B vs the pre-retune build; theme switching; avatar framing + idle + lip-sync (avatar on/off); session new/reset/end teardown; transcript export; mic-denied + garbled-reprompt; full install→start→stop on a clean machine.

---

## 9. Assumptions

- The operator has NVIDIA GPU hardware (RTX 5090) to sign PERF-04 and the carried gates.
- `install.sh` ships in-repo and is `curl|sh`-compatible; a public hosting URL is a later flip once the repo is published.
- Presets reuse the default GLB; per-persona avatars are deferred.
- The persona prompt remains the sole content guardrail (unchanged); abliterated-model risk stays accepted.

---

## 10. Open Questions

- Final tuned values for FEEL-01/02 (resolved empirically during 14-01 on target hardware).
- Exact preset roster for AVTR-13 (seed: Cyber Trainer + SOC/SecEng/GRC + optional Domain Expert) — adjustable.
- Whether theme choice also belongs in the in-room SettingsDrawer (not only setup) — default: setup only, optional drawer entry.

---

## 11. Phase 15 Preview — "Broaden Hardware Reach" *(captured, not built in 14)*

**Goal:** broaden the hardware the stack runs on — smaller VRAM budgets and AMD GPUs.

**Sub-8GB VRAM mode:**
- Keep only **one small LLM warm** at a time (STT + TTS + one LLM); stop pinning both models resident (`OLLAMA_KEEP_ALIVE` tuning / unload-on-swap in `handle_model_update`).
- **Gray out the E4B "Better" model** in the picker under a VRAM threshold (it peaks ~8.9GB alone).
- **Add tiny models** to the picker — *intentionally reverses* the current "exactly two models / no model-zoo" constraint (REQUIREMENTS.md Out of Scope). Each new model still needs per-build template/thinking-off verification + a placement story.
- Lean KV/context (smaller `num_ctx`, q-cache) to fit the budget; update `placement.py` table + `vram-validate.sh` ceiling for the new target.

**AMD GPU support:**
- **LLM:** Ollama ROCm path.
- **STT:** **Whisper** (whisper.cpp/faster-whisper, ROCm or CPU) instead of NeMo (NeMo has no ROCm); the existing CPU-ONNX NeMo backend is also available.
- **TTS:** **Kokoro-ROCm** — the upstream repo ships a `docker/rocm/` compose variant and `ghcr.io/remsky/kokoro-fastapi-rocm:latest` (PyTorch ROCm 6.4, x86_64-only, `--device=/dev/kfd --device=/dev/dri`, ~10× CPU once MIOpen caches warm; newer iGPUs like Strix Halo gfx1151 need a ROCm 7.2 bump).
- **Doctor/passthrough:** `rocm-smi`-based GPU doctor; `/dev/kfd` + `/dev/dri` device passthrough; vendor detection in `install.sh`.

---

*PRD authored 2026-06-27 via brainstorming. Next: user review → `/gsd-plan-phase 14` (or superpowers writing-plans) to decompose into the 14-0x plans above.*
