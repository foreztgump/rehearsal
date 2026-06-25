---
status: human_needed
phase: 02-bare-voice-loop-mvp-gate
verified: 2026-06-25
requirement_ids: [VOICE-01, VOICE-02, VOICE-03, VOICE-04, VOICE-05, VOICE-06, VOICE-07, VOICE-08, PERS-01, PERF-01, DEPLOY-03]
---

# Phase 02 — Bare Voice Loop (Hard MVP Gate): VERIFICATION

**Verified:** 2026-06-25
**Phase goal:** Ship the hard MVP gate — a browser SPA where the user speaks open-mic and holds a fully streamed near-real-time conversation with the default Cybersecurity Trainer: VAD → semantic turn-detect → STT → LLM → first-sentence TTS, with instant barge-in, an agent-state indicator, a live two-sided transcript, and per-turn latency instrumentation.
**Phase requirement IDs:** VOICE-01, VOICE-02, VOICE-03, VOICE-04, VOICE-05, VOICE-06, VOICE-07, VOICE-08, PERS-01, PERF-01, DEPLOY-03
**Verdict:** PASS at the committed-artifact level — every client-verifiable criterion is satisfied. The audible/live acceptance criteria are **operator-gated human-verification items** (no Docker daemon / GPU / browser / importable `livekit-agents` in the sandbox), appropriately deferred per the MVP-mode policy established in 01-VERIFICATION.md. **Status: `human_needed`** (operator gates remain before the gate is hardware-proven).

---

## Mode Note

This is an **MVP-mode** phase. The phase goal is dominated by acceptance criteria that require a live room join, audible greeting/replies, real barge-in timing, acoustic echo behavior, and a real end-to-end P50 — all of which need the Proxmox VM + GPU + a CA-trusted LAN device. The execution sandbox has **no Docker daemon, no GPU, no browser, and `livekit-agents` is not importable** (`ModuleNotFoundError: No module named 'livekit'`). Per the convention set in `01-VERIFICATION.md`, those live checks are classified as **operator-gated human-verification items, NOT failures**, because the committed artifacts correctly implement them. All client-verifiable criteria (file existence, grep assertions, exact version pins, `py_compile`, `next build`, prohibition greps, metric key-name contract, percentile math) were executed here and PASS.

---

## Requirement ID Cross-Reference (PLAN frontmatter ↔ REQUIREMENTS.md)

Every requirement ID claimed across the three plan frontmatters is accounted for and present in REQUIREMENTS.md, and every Phase-2 ID in REQUIREMENTS.md is covered by a plan.

| Req ID | In plan frontmatter | REQUIREMENTS.md status | Accounted |
|--------|---------------------|------------------------|-----------|
| VOICE-01 | 02-02 | Complete (line 12) | ✅ |
| VOICE-02 | 02-02 | Complete (line 13) | ✅ |
| VOICE-03 | 02-03 | Complete (line 14) | ✅ |
| VOICE-04 | 02-03 | Complete (line 15) | ✅ |
| VOICE-05 | 02-01 | Complete (line 16) | ✅ |
| VOICE-06 | 02-01 | Complete (line 17) | ✅ |
| VOICE-07 | 02-01 | Complete (line 18) | ✅ |
| VOICE-08 | 02-03 | Complete (line 19) | ✅ |
| PERS-01 | 02-01, 02-02 | Complete (line 23) | ✅ |
| PERF-01 | 02-03 | Complete (line 66) | ✅ |
| DEPLOY-03 | 02-01 | Complete (line 71) | ✅ |

No dangling or unmapped IDs. Traceability table (REQUIREMENTS.md lines 117–158) maps all 11 IDs to Phase 2 as Complete. Union of plan frontmatter IDs = exactly the 11 phase requirement IDs.

---

## must_haves Audit (per plan)

### Plan 02-01 (Browser SPA + LiveKit SDK + pill + transcript)

| must_have | Check | Status |
|-----------|-------|--------|
| VOICE-05 open-mic, no PTT control | `LiveKitRoom audio` publish; no push-to-talk anywhere (only a comment says "no push-to-talk") | ✅ artifact |
| VOICE-06 state pill bound to `useVoiceAssistant().state` | `web/app/AgentStatePill.tsx` reads `state`, distinct color per state | ✅ artifact |
| VOICE-07 two-sided transcript by identity | `web/app/Transcript.tsx` `useTranscriptions()` split by `user-` prefix | ✅ artifact |
| DEPLOY-03 single "Start talking" entry, no config | `VoiceRoom.tsx` one button → token fetch → join | ✅ artifact |
| PERS-01 entry connects to default agent (no setup) | button → `/api/token` → `<LiveKitRoom>`; persona active server-side | ✅ artifact |
| Every new npm dep exact-pinned, lockfile committed | `livekit-client@2.20.0`, `@livekit/components-react@2.9.21` (no `^`/`~`); lockfile resolves 3× | ✅ |
| PROHIBITION: no PTT control | none added | ✅ |
| PROHIBITION: no server-side NC plugin in web/ | `rg -i "krisp\|ai_coustics\|noiseCancellation:" web/app` → none | ✅ |
| PROHIBITION: serverUrl not hardcoded | reads `process.env.NEXT_PUBLIC_LIVEKIT_URL` | ✅ |
| PROHIBITION: `LIVEKIT_API_SECRET` never NEXT_PUBLIC | only `NEXT_PUBLIC_LIVEKIT_URL` exposed; comment confirms secrets server-side | ✅ |
| PROHIBITION: token route reused unchanged | last touch is `12d80c8` (01-03); no Phase-2 commit touches it | ✅ |

### Plan 02-02 (greeting + per-turn loop + persona)

| must_have | Check | Status |
|-----------|-------|--------|
| VOICE-01 spoken reply via full mic→STT→LLM→TTS loop | pipeline wired; automatic per-turn reply relied on | ✅ artifact / ⏳ audible gate |
| VOICE-02 first-sentence TTS streaming (framework, verified) | no hand-rolled splitter; framework behavior | ✅ artifact / ⏳ audible gate |
| PERS-01 default Cybersecurity Trainer active + greets, no setup | `PERSONA_INSTRUCTIONS` + greeting `generate_reply` after `session.start` | ✅ artifact / ⏳ audible gate |
| Thinking/reasoning suppressed every live turn | `with_ollama(reasoning_effort="none")` over `/v1` | ✅ artifact / ⏳ `<think>`-leak gate |
| Persona static top-block, no volatile data | parenthesized string literal (no f-string/.format) | ✅ |
| PROHIBITION: no hand-rolled sentence splitter | none | ✅ |
| PROHIBITION: no manual per-turn orchestration | `grep -c generate_reply` = 1 (greeting only) | ✅ |
| PROHIBITION: no second hardcoded LLM tag | model resolves from `OLLAMA_MODEL` via `resolved_llm_tag()` | ✅ |
| PROHIBITION: no volatile data in system prompt | static literal | ✅ |
| PROHIBITION: no re-plumbing of Phase-1 transport/STT/LLM/TTS/turn detector | only persona + greeting + `reasoning_effort` added | ✅ |

### Plan 02-03 (barge-in + endpointing + AEC + per-turn metrics)

| must_have | Check | Status |
|-----------|-------|--------|
| VOICE-03 barge-in cancels TTS (framework, tuned) | `allow_interruptions` not disabled; `interruption.min_duration 0.3` | ✅ artifact / ⏳ timing gate |
| VOICE-04 semantic endpointing `MultilingualModel`, min ~250–350ms | `turn_handling` dict, `endpointing.min_delay 0.3` ∈ [0.25,0.35], `MultilingualModel()` nested | ✅ artifact / ⏳ slow-speech gate |
| VOICE-08 per-turn line w/ real `e2e_ms` + rolling P50/P95 | turn-keyed buffer flushes one `emit_turn` w/ computed `e2e_ms`; `emit_rolling_summary()` | ✅ artifact / ⏳ live-numbers gate |
| PERF-01 instrumented v2v rolling P50 < ~1.2s | budget `e2e: 1200`; instrumentation present | ✅ artifact / ⏳ real-P50 gate |
| Per-turn metric key names unchanged (flat-TTFT contract) | keys `eou_ms/stt_ms/llm_ttft_ms/tts_ttfb_ms/e2e_ms/over_budget` — `_self_check` asserts exact set | ✅ |
| PROHIBITION: no endpointing kwarg without introspection | surface source-verified (livekit-agents 1.5.0–1.6.4); documented in comment | ✅ |
| PROHIBITION: no server-side cloud NC plugin | `rg -i "ai_coustics\|krisp\|noise_cancellation" agent/ web/app` → none | ✅ |
| PROHIBITION: no external telemetry export | `rg -i "prometheus\|opik\|otel\|grafana" agent/metrics.py` → none | ✅ |
| PROHIBITION: `allow_interruptions` not disabled | no `enabled: False` | ✅ |
| PROHIBITION: no change to per-turn JSON key names | unchanged (asserted by `_self_check`) | ✅ |

---

## Static Verification Run (sandbox — executed here)

| Check | Result |
|-------|--------|
| `python3 -m py_compile agent/main.py agent/metrics.py` | COMPILE OK |
| `python3 agent/metrics.py` (`_self_check`) | OK — e2e p50=1050.0 p95=1270.0; key-name contract asserted; rolling summary emitted |
| `npm run build` (web, Next.js 16.2.9) | ✓ Compiled + TypeScript OK; 3 routes generated; exit 0 |
| `livekit-client` / `@livekit/components-react` exact pins | `2.20.0` / `2.9.21` (no `^`/`~`) |
| `livekit-client` is 2.x (matches self-hosted server v1.10.x) | ✅ |
| lockfile resolves new deps | `grep -c '"livekit-client"'` = 3 |
| `NEXT_PUBLIC_LIVEKIT_URL` in `.env.example` (with comment) + `.env` | ✅ (`wss://<lan-host>:7443` / `wss://127.0.0.1:7443`) |
| Only `NEXT_PUBLIC_` var is the WS URL (no secret) | ✅ |
| `grep -c generate_reply agent/main.py` | 1 (greeting only) |
| `MultilingualModel()` retained as turn detector | ✅ (nested in `turn_handling`) |
| endpointing `min_delay 0.3` ∈ [0.25, 0.35], exactly one surface | ✅ |
| `interruption.min_duration 0.3`; VAD `activation_threshold=0.65` | ✅ |
| persona references Cybersecurity/security + gentle correction | ✅ |
| persona is plain literal (no f-string/.format) | ✅ |
| `Agent(instructions=PERSONA_INSTRUCTIONS)` still consumes it | ✅ |
| web AEC `echoCancellation/noiseSuppression/autoGainControl: true` | ✅ (3 matches) |
| `e2e` added to recorded rolling windows | ✅ (metrics.py:169, 194) |
| prohibition greps (NC plugin web/, NC agent+web, telemetry) | all empty (pass) |
| token route (`web/app/api/token/route.ts`) Phase-2 untouched | ✅ (last commit 01-03) |
| Task commits present | 16 feat/docs commits across 02-01/02/03 |

---

## Claimed-vs-Actual (SUMMARY cross-check)

All files listed in the three SUMMARY `key-files.created/modified` blocks exist on disk with content matching the claims:
- Created: `web/app/VoiceRoom.tsx`, `web/app/AgentStatePill.tsx`, `web/app/Transcript.tsx` — present, shapes match.
- Modified: `web/package.json` + `web/package-lock.json` (exact pins + lock), `web/app/page.tsx` (renders `<VoiceRoom/>`, SecureContextProbe removed), `.env.example`/`.env` (`NEXT_PUBLIC_LIVEKIT_URL`), `agent/main.py` (persona + greeting + `reasoning_effort="none"` + `turn_handling` dict + VAD threshold), `agent/metrics.py` (turn-keyed buffer + `e2e` + rolling summary + `_self_check`).
- `ollama/Modelfile` correctly **unchanged** (thinking-OFF path (a) chosen — `reasoning_effort="none"` over `/v1`, no Modelfile edit), consistent with 02-02-SUMMARY.

One documented planning-premise correction in 02-03 (the "two mutually-incompatible endpointing surfaces = TypeError" BLOCKER is disproven by reading tagged source; both coexist, direct kwargs are deprecated-but-migrated). The dict surface was still used (one surface only), satisfying the acceptance criteria. No code discrepancies found.

---

## Operator Gates (human-verification items — run on the Proxmox VM + LAN device)

These are the audible/live acceptance criteria that CANNOT execute in the sandbox. They are **not failures** — the committed artifacts implement them correctly. Prereqs: stack up via `docker compose up`, `LIVEKIT_NODE_IP` set, `NEXT_PUBLIC_LIVEKIT_URL` → `wss://<vm-lan-host>:7443`, UDP 7882 / TCP 7881 open, CA-trusted LAN device.

### Deferred introspection (livekit not importable here — confirm on installed build)
1. `AgentSession.__init__` signature — confirm `turn_handling: NotGivenOr[TurnHandlingOptions]` present and the `endpointing`/`interruption` dict keys accepted (grounded on 1.5.0–1.6.4 source).
2. `AgentSession.generate_reply` signature + fire-once-on-join trigger semantics.
3. `with_ollama` forwards `reasoning_effort="none"` on the `/v1` request (and exposes the param).
4. `silero.VAD.load` accepts `activation_threshold` (default 0.5).
5. `preemptive_generation` kwarg — add `=True` only if verified present (currently conservatively omitted).
6. No single end-to-end v2v field on `MetricsReport`/`EOUMetrics` (none in 1.5.0–1.6.4; prefer it over computed `e2e_ms` if a later build adds one).

### Deferred MANUAL gates (audible / live)
7. **[02-01] Room join + audio + pill + transcript:** page-load → one "Start talking" button → join within seconds, hands-free (open-mic, no PTT); agent TTS plays; pill shows listening/thinking/speaking matching reality; both sides stream live into the transcript (DEPLOY-03, PERS-01, VOICE-05/06/07).
8. **[02-02] Greeting + per-turn loop + first-sentence + no `<think>`:** on join the agent audibly greets exactly once as the Cybersecurity Trainer; speak → relevant spoken reply via the full streamed loop, beginning on its first completed sentence; no `<think>` preamble in the transcript and TTFT not inflated (VOICE-01, VOICE-02, PERS-01).
9. **[02-03] Barge-in + slow-speech endpointing + acoustic echo + real P50:** talking over the agent stops it within ~1 frame, no self-interrupt on echo tail/backchannel (VOICE-03); hesitant speech is not cut off mid-thought, no dead air after a clear finish (VOICE-04); laptop speakers + built-in mic in a small room — no self-echo interruption, headphones path clean (VOICE-08 echo defense); over N turns per-turn lines show populated stage numbers and rolling e2e **P50 < ~1.2s** (VOICE-08, PERF-01).

---

## Conclusion

All 11 requirement IDs (VOICE-01..08, PERS-01, PERF-01, DEPLOY-03) are accounted for, consistent between the three PLAN frontmatters and REQUIREMENTS.md, and every must_have is satisfied at the committed-artifact level. Every client-verifiable criterion — exact npm pins + lockfile, `py_compile`, `next build`, metric key-name contract + percentile math, persona/greeting/thinking-OFF wiring, endpointing/barge-in/VAD tuning on the verified surface, and all prohibition greps — PASSES in the sandbox. The remaining items are live operator gates (audible loop, real barge-in timing, acoustic echo, real e2e P50) deferred to the Proxmox VM per MVP-mode policy.

**Phase 02 goal achieved at the artifact level. Status: `human_needed` — operator gates above must be cleared on the VM to declare the hard MVP gate hardware-proven.**
