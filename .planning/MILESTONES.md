# Milestones

## v1.0-rc1 MVP Release Candidate (Shipped: 2026-06-26)

**Phases completed:** 6 phases, 15 plans, 56 tasks
**Stats:** 112 commits · 113 files · ~21,180 LOC added · 2026-06-24 → 2026-06-26 · git range `75513c3 → 33ee386`
**Scope:** Interim release candidate — Phases 1-6 (the full conversational MVP: foundation, voice loop, persona, KB, history, interview). Phase 7 (Polish & Reliability) is deferred to v1.0.

### Known Gaps

Deferred to Phase 7 / v1.0 (not in this RC):

- [ ] **SESS-01**: User can start a new session (Phase 7)
- [ ] **SESS-02**: User can reset the current session (Phase 7)
- [ ] **SESS-03**: User can end the session, clearing ephemeral state incl. KB (Phase 7)
- [ ] **SESS-04**: User can export/download the session transcript (Phase 7)
- [ ] **REL-01**: Clear mic-permission-denied prompt, not a silent failure (Phase 7)
- [ ] **REL-02**: Garbled/empty-transcription reprompt instead of responding to noise (Phase 7)

Requirements coverage at close: **36/42 v1 requirements complete** (the 6 above are the Phase 7 remainder).

Known deferred items at close: 9 (see STATE.md Deferred Items) — 6 Phase 7 requirements, 2 UAT phases (0 pending scenarios each), 1 bundle of VM operator-gated verification proofs.

**Deferred verification:** Several Phase 4/6 proofs are operator-runbook gates requiring the live RTX VM (KB flat-TTFT turn-2≪turn-1, three-models-under-16GB, strong-vs-weak critique discrimination) — documented, not yet operator-signed.

**Key accomplishments:**

- Six-service GPU Compose stack (LiveKit/Ollama/Whisper/Kokoro/agent/web) with pinned tags, LAN-only port binds, a mkcert Caddy TLS proxy, and a Next.js shell proving `navigator.mediaDevices` in a secure context.
- Resolved and pinned `gemma4:e4b-it-q4_K_M` (ladder rung 1, verified real on the RTX 5090 host), with thinking off, q8_0 KV-cache env scoped on the ollama service, a 3-model warmup emitting a real LLM TTFT, and an instrumented VRAM-under-load + flash-attn-allowlist proof script.
- Self-hosted LiveKit with LAN-pinned ICE (udp mux 7882 + node_ip, no STUN egress), a uv-built agent image that bakes the local MultilingualModel + Silero VAD weights offline, an AgentSession wired to the three local model endpoints, a per-plugin metrics scaffold that emits the warmup LLM TTFT as the one real metric, and a LiveKit JWT-mint endpoint for Phase 2.
- Single-gesture browser voice room: "Start talking" → /api/token → `<LiveKitRoom audio video={false}>` with client-side AEC, agent TTS playout, a `useVoiceAssistant().state` pill, and a `useTranscriptions()` two-sided transcript — wired to NEXT_PUBLIC_LIVEKIT_URL.
- Default Cybersecurity Trainer persona (static frozen-prefix-ready prompt) + greet-on-connect via `session.generate_reply` + live thinking-OFF over Ollama's `/v1` via `with_ollama(reasoning_effort="none")` — the bare voice loop is now wired to speak.
- Endpointing pinned on the non-deprecated `turn_handling` dict (dynamic, min_delay 0.3s, MultilingualModel nested), barge-in gate tuned (min_duration 0.3s + false-interruption resume), Silero VAD threshold raised to 0.65, and real per-turn voice-to-voice metrics via a speech_id-keyed buffer that computes `e2e_ms` and emits rolling P50/P95 — all API surfaces source-verified against tagged livekit-agents (1.5.0–1.6.4) rather than guessed.
- Lifted the static PERSONA_INSTRUCTIONS literal into a pure `agent/persona.py` config module — `Persona` dataclass, difficulty/verbosity/correction enum→fixed-string knob tables (CORRECTION is PERS-07), curated Kokoro voice list, and a byte-stable `render_persona` — then wired `main.py` to render `DEFAULT_PERSONA`, hold a named `agent` ref, and source the TTS voice from the persona, with zero behavior change today.
- Added a `PersonaPanel.tsx` side-panel editor (role/name/difficulty/verbosity/correction/voice) whose Apply sends a full persona snapshot over the native `persona.update` LiveKit RPC, mounted it inside `<LiveKitRoom>`, and registered an agent-side handler that hot-swaps the persona in place via `update_instructions` + `session.tts.update_options(voice=)` — no AgentSession restart, metrics contract untouched.
- Ephemeral KB ingest vertical slice: per-file LiveKit byte-stream upload → pure livekit-free per-type parser (pymupdf4llm/python-docx) with extraction-quality gate + extracted-token size guard + four typed errors → in-memory doc accumulation → kb.state-driven KB-active indicator panel — distillation/injection deferred to 04-02.
- Setup-time distillation vertical slice: concatenated docs → one off-hot-path Ollama call (`distill()`, think=false, no structured-output schema #15260-safe) → compact prose brief + verbatim `FACTS:` anchors → injected ONCE into the frozen `KB_SLOT` via `render_prompt(persona, brief)` + `update_instructions` → composed with persona edits → priming turn warms the prefill — paid for once at session start, never re-charged per turn.
- The keystone verification slice: pinned `ollama/Modelfile` `num_ctx` at 8192 with explicit persona+brief+history+headroom accounting (coupled to `BRIEF_TOKEN_BUDGET`/`KB_MAX_TOKENS`), added an additive `--with-kb`/`KB_FIXTURE` peak-VRAM re-check mode to `scripts/vram-validate.sh`, and authored `04-KB-VERIFY.md` — the operator runbook proving turn-2 `llm_ttft_ms` ≪ turn-1 with a large KB (KB-05), the Ollama prefix-cache hit, the brief-token→num_ctx measurement, and three-models-under-16GB with q8_0 engaged — all deferred VM gates, `agent/metrics.py` untouched.
- The Phase-4 gap-closure slice: after live-stack UAT surfaced 2 HIGH gaps, pinned the effective Ollama context to 8192 via service env (was a silently-truncated 4096), made `distill()` honor the FACTS-anchor contract with a one-shot off-hot-path repair (KB-04 grounding), added a brief-gated persona cite-nudge, aligned the whisper-warmup default to large-v3, then rebuilt + force-recreated the stack and re-ran the UAT proxies — GAP-1 and GAP-2 RESOLVED, Proofs A/C/D verified-proxy, `agent/metrics.py` untouched.
- Per-turn ChatContext item-list capping via `truncate(max_items=20)` + `update_chat_ctx` in the repo's first `Agent` subclass, keeping TTFT flat over a long session without ever touching the cached persona+KB `instructions` prefix.
- Single prompt-shaped Interview Mode (Option B): a `mode.update` RPC hot-swaps a byte-stable Interview system block — one-question-at-a-time, then critique + strong model answer — composed with persona × KB, driven from a cloned PersonaPanel.
- A four-dimension qualitative critique rubric (no numeric score) frozen into `agent/interview.py`, a slow-speech interview endpointing profile (min_delay 0.7 / max_delay 5.0) with the profile-switch mechanism flagged `[VM-INTROSPECT]`, and a strong-vs-weak critique discrimination operator runbook that gates the E4B-depth blocker and documents (not builds) the 24GB `OLLAMA_MODEL` fallback.

---
