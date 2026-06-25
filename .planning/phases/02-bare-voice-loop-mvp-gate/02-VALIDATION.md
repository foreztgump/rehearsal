---
phase: 2
slug: bare-voice-loop-mvp-gate
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2025-06-24
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | {pytest 7.x (agent) / vitest (web) — confirm against Phase 1 setup} |
| **Config file** | {path or "none — Wave 0 installs"} |
| **Quick run command** | `{quick command}` |
| **Full suite command** | `{full command}` |
| **Estimated runtime** | ~{N} seconds |

---

## Sampling Rate

- **After every task commit:** Run `{quick run command}`
- **After every plan wave:** Run `{full suite command}`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** {N} seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 2-01-01 | 01 | 1 | VOICE-06 | — | N/A | unit | `{command}` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*The planner refines this map per-task during planning. Manual/operator-gated verifications (browser audio, AEC, P50 latency) are expected for this phase — see Manual-Only Verifications below.*

---

## Wave 0 Requirements

- [ ] {test stubs for VOICE-0x — planner determines}
- [ ] {shared fixtures}
- [ ] {framework install — if not present from Phase 1}

*If none: "Existing infrastructure covers all phase requirements."*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Speak → hear spoken response (full mic→STT→LLM→TTS loop) | VOICE-01 | Requires real browser + mic + audio | Operator gate: load SPA, speak, confirm agent responds |
| Open-mic VAD hands-free (no push-to-talk) | VOICE-05 | Requires real browser + mic | Operator gate: confirm conversation runs hands-free via VAD |
| Instant barge-in | VOICE-03 | Requires live audio interruption timing | Operator gate: interrupt agent mid-speech, confirm immediate stop |
| Browser-side AEC/noise suppression | VOICE-05/PERF-03 | Requires acoustic echo conditions | Operator gate: open-mic with speaker output, confirm no echo loop |
| Per-turn voice-to-voice latency instrumented & visible | VOICE-08 | Requires end-to-end real-time measurement | Operator gate: run N turns, read instrumented per-turn metrics |
| Voice-to-voice P50 < ~1.2s (this phase) | PERF-01 | Requires end-to-end real-time measurement | Operator gate: run N turns, compute P50 from instrumented metrics |

*Sandbox limitation (from RESEARCH.md): no Docker/browser in planning sandbox — these are operator-gated.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < {N}s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
