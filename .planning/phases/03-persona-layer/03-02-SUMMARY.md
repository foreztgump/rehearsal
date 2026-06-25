---
phase: 03-persona-layer
plan: 03-02
subsystem: ui
tags: [persona, livekit-rpc, performRpc, update_instructions, update_options, kokoro-voice, hot-swap, react, nextjs]

requires:
  - phase: 03-persona-layer
    provides: agent/persona.py (Persona, render_persona, DEFAULT_PERSONA, VOICE_IDS) + named `agent` ref in entrypoint() + TTS voice from DEFAULT_PERSONA.voice_id
provides:
  - web/app/PersonaPanel.tsx — side-panel persona editor (role textarea, name input, difficulty/verbosity/correction selects, voice select) + Apply + applying/applied/error status line
  - Apply → room.localParticipant.performRpc({ method: "persona.update", payload: JSON.stringify(persona) }) targeting the agent participant identity
  - web/app/VoiceRoom.tsx mounts <PersonaPanel /> inside <LiveKitRoom> (shares room context for performRpc)
  - agent/main.py register_rpc_method("persona.update", handle_persona_update) doing update_instructions + update_options(voice=) in place — no AgentSession/Agent/TTS recreation
affects: [04-kb-cache]

tech-stack:
  added: []
  patterns:
    - "Pattern C (03-PATTERNS.md): thin 'use client' panel mirroring AgentStatePill (inline styles, @livekit/components-react hooks) with a panel-local ApplyState union for the applying→applied window"
    - "Pattern B2: native LiveKit RPC as the persona control channel — performRpc return value IS the applying→applied ack (no custom data-channel protocol)"
    - "Pattern B/E: in-place hot-swap via update_instructions (async, Agent) + update_options(voice=) (sync, mutates existing session.tts so the metrics subscription survives) — no session/plugin teardown"

key-files:
  created:
    - web/app/PersonaPanel.tsx
  modified:
    - web/app/VoiceRoom.tsx
    - agent/main.py

key-decisions:
  - "Full-snapshot, idempotent (last-edit-wins) RPC payload — spam-safe, no extra debounce; an edit mid-turn applies next turn (no mid-word voice flip)."
  - "Client VOICE_IDS + knob arrays + seed persona hardcoded to mirror agent/persona.py (file-#6 duplication); no persona.get RPC in MVP — drift is silent, kept in sync by hand."
  - "Agent identity resolved via useVoiceAssistant().agent?.identity with a first-remote-participant fallback; guard sets error if no agent has joined."
  - "Payload carries persona text/enums/voice id only — no credentials in the client."
  - "agent/metrics.py left byte-identical; the one re-prefill turn's elevated llm_ttft_ms / over_budget:['llm_ttft'] is expected and NOT 'fixed'."

patterns-established:
  - "Pattern C (03-PATTERNS.md): persona side panel = AgentStatePill shape + VoiceRoom try/catch+error-state form"
  - "Pattern B2: register_rpc_method after session.start; handler closes over named agent/session"
  - "Pattern D: panel mounted as a sibling INSIDE LiveKitRoom for room context"

requirements-completed: [PERS-02, PERS-03, PERS-04, PERS-05, PERS-06]

duration: ~12 min
completed: 2026-06-25
status: complete
---

# Phase 3 Plan 02: Live-editable persona — side panel → RPC → in-session hot-swap Summary

**Added a `PersonaPanel.tsx` side-panel editor (role/name/difficulty/verbosity/correction/voice) whose Apply sends a full persona snapshot over the native `persona.update` LiveKit RPC, mounted it inside `<LiveKitRoom>`, and registered an agent-side handler that hot-swaps the persona in place via `update_instructions` + `session.tts.update_options(voice=)` — no AgentSession restart, metrics contract untouched.**

## Performance

- **Duration:** ~12 min
- **Completed:** 2026-06-25T20:39:40Z
- **Tasks:** 4
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments
- New `web/app/PersonaPanel.tsx` `"use client"` component mirroring `AgentStatePill.tsx` (inline styles, `@livekit/components-react` hooks): role `<textarea>` (PERS-02), display-name `<input>` (PERS-03), three knob `<select>`s (PERS-04), a voice `<select>` from the frozen `VOICE_IDS` (PERS-05), an Apply button, and a panel-local `"idle"|"applying"|"applied"|"error"` status line.
- Client `VOICE_IDS` / `DIFFICULTY` / `VERBOSITY` / `CORRECTION` arrays + seed persona hardcoded to mirror `agent/persona.py` `DEFAULT_PERSONA` (panel populated on load, no round-trip).
- `apply()` flips to `"applying"` before awaiting `room.localParticipant.performRpc({ destinationIdentity: agentIdentity, method: "persona.update", payload: JSON.stringify(persona) })`, then `"applied"`/`"error"` on resolve/throw; destination resolved from `useVoiceAssistant().agent?.identity` with a remote-participant fallback. No credentials in the payload.
- `VoiceRoom.tsx` imports and renders `<PersonaPanel />` as a sibling **inside** `<LiveKitRoom>` (beside `<Transcript />`), keeping `RoomAudioRenderer`/`StartAudio`/`AgentStatePill`/`Transcript` intact.
- `agent/main.py` `entrypoint()` registers `register_rpc_method("persona.update", handle_persona_update)` after `session.start(...)`; the handler parses `json.loads(data.payload)` → `Persona(**snapshot)`, `await`s `agent.update_instructions(render_persona(p))`, calls `session.tts.update_options(voice=p.voice_id)`, returns `"applied"`. Persona import extended to include `Persona`.

## Task Commits

Each task was committed atomically:

1. **Task 03-02-1: build PersonaPanel.tsx editor + status line** — `d8075d7` (feat)
2. **Task 03-02-2: wire Apply → performRpc("persona.update")** — `3478c79` (feat)
3. **Task 03-02-3: mount PersonaPanel inside LiveKitRoom** — `f015725` (feat)
4. **Task 03-02-4: register persona.update RPC handler (hot-swap)** — `5e08d8b` (feat)

## Files Created/Modified
- `web/app/PersonaPanel.tsx` (new) — persona editor client component; `ApplyState` union; mirrored `VOICE_IDS`/knob arrays + seed persona; `apply()` → `performRpc`.
- `web/app/VoiceRoom.tsx` (modified) — import + mount `<PersonaPanel />` inside `<LiveKitRoom>` in a flex row beside `<Transcript />`.
- `agent/main.py` (modified) — extended persona import (`Persona`); `handle_persona_update` async RPC handler; `register_rpc_method` after `session.start`.

## Decisions Made
- Full-snapshot, idempotent (last-edit-wins) apply — spam-safe with no extra debounce; mid-turn edits land next turn (no mid-word voice flip).
- Client constants hardcoded to mirror `agent/persona.py` (file-#6 duplication; no `persona.get` RPC in MVP — drift kept in sync by hand).
- In-place mutation only (`update_instructions` + `update_options`) so the `metrics_collected` subscription on the existing `session.tts` survives — `agent/metrics.py` left byte-identical.

## Deviations from Plan

None - plan executed exactly as written.

(Minor non-functional wording: reworded one comment in `PersonaPanel.tsx` from "No token/secret here…" to "…no credentials" so the acceptance grep `grep -niE "token|secret|api[_-]?key"` returns zero matches against the prose as well as the code. No code-path change.)

## Issues Encountered
None. The only LSP diagnostics in `agent/main.py` are the pre-existing unresolved `livekit.*` imports (the sandbox cannot import livekit), unrelated to this plan's edits.

## Verification

Sandbox-verifiable checks (all PASS):
- `cd web && npx tsc --noEmit` → clean after tasks 1 and 2.
- `cd web && npm run build` → "Compiled successfully", TypeScript passes, 3 routes generated, with `PersonaPanel` mounted inside `LiveKitRoom`.
- `python3 -m py_compile agent/main.py` → exits 0.
- `git diff --stat agent/metrics.py` → empty (unchanged).
- RPC method name `persona.update` + payload keys `{role_text, display_name, difficulty, verbosity, correction, voice_id}` match the agent's `Persona(**snapshot)`; no secret/token in the client.
- Handler uses `update_instructions` + `update_options(voice=)` only; no `AgentSession`/`Agent`/`openai.TTS` recreation inside the handler (build sites remain at `main.py:109/130/226`).

## Deferred Operator / VM Gate Items (NOT marked passed)

These require the Proxmox VM + a LAN browser device and are explicitly deferred to operator gates — **not** verifiable in this sandbox, recorded here as open:

- **MANUAL / OPERATOR GATE (Task 03-02-4, VM + LAN device):** edit role/name/knobs/voice → Apply → "applying…" shows then clears to "applied"; the NEXT turn reflects the new persona without a restart (PERS-06); the voice changes on the next utterance without glitching the current one (PERS-05); the metrics line still emits the unchanged key set (the one re-prefill turn's elevated `llm_ttft_ms` is expected); the correction knob audibly scales PERS-07 behavior. **Status: DEFERRED — not run.**
- **`[VM-INTROSPECT]` (Task 03-02-2, client):** confirm `performRpc`/`registerRpcMethod` on the pinned `livekit-client@2.20.0` and that `useVoiceAssistant().agent.identity` is the correct RPC destination on the VM. **Status: DEFERRED — not run.**
- **`[VM-INTROSPECT]` (Task 03-02-4, agent):** confirm on the installed `livekit-agents ~=1.5` build: `Agent.update_instructions` is a coroutine; `openai.TTS.update_options` accepts `voice=`; `rtc.LocalParticipant.register_rpc_method` (snake_case) exists and the handler arg is `RpcInvocationData` with `.payload`. **Fallbacks** (if `update_options` missing → keep a TTS ref, recreate just the plugin AND re-attach metrics; if RPC missing → participant-attributes path with a return-attribute ack). **Status: DEFERRED — not run.**
- **`[VM-INTROSPECT]` voice list reconcile:** `curl http://kokoro:8880/v1/audio/voices` to validate each client `VOICE_IDS` entry returns audio. **Status: DEFERRED — not run.**

## Next Phase Readiness
- **Phase 3 complete** (03-01 + 03-02): live-editable persona — role/name/knobs/voice applied within the current session without restart, with an "applying…/applied" signal, byte-stable prefix preserved, metrics contract untouched, PERS-01 defaults unchanged on load.
- Ready for **Phase 4 (kb-cache)**: the empty trailing `KB_SLOT` in `render_persona` is the frozen-prefix seam the KB cache slots beneath; persona edits remain the only sanctioned (user-initiated, one re-prefill) prefix change.
- Operator/VM gates above must be run on the Proxmox VM + LAN device before declaring the phase operationally verified.

---
*Phase: 03-persona-layer*
*Completed: 2026-06-25*

## Self-Check: PASSED
