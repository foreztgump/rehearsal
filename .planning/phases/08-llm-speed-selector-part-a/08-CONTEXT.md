# Phase 8: LLM Speed Selector (Part A) - Context

**Gathered:** 2026-06-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace the single stock LLM with two user-selectable Ollama models (Fast E2B default / Better E4B) exposed via a plain-language UI picker, session-persisted, switchable on the next turn without session teardown — while preserving the latency optimizations (thinking-off / streaming / keep-alive / flash-attn / lean-context / capped num_predict) and verifying per-build that the abliterated community GGUFs have a sane chat template, leak no reasoning artifacts, and leave the persona prompt as the sole intact content guardrail.

Covers requirements LLM-01 through LLM-06. Server pipeline (STT/TTS) untouched; only the LLM leg and a new UI picker change.

</domain>

<decisions>
## Implementation Decisions

### LLM Picker UI
- New `web/app/ModelPanel.tsx` side panel, mirroring the established InterviewPanel / PersonaPanel side-panel pattern (renders inside `<LiveKitRoom>` for room context)
- Two-option segmented control / select with plain-language labels — "Fast (snappier)" / "Better (more thoughtful)" — NEVER raw Ollama tags (LLM-01)
- Default selection = Fast (E2B), configurable-default per LLM-02
- Reuse InterviewPanel's `performRpc` + `ApplyState` (idle→applying→applied→error) ack pattern; the native RPC return string IS the ack

### Agent-Side Model Switch Mechanism
- New `model.update` RPC, cloning the `mode.update` handler exactly: validate the incoming choice BEFORE committing the shared holder, then ack ("applied"/"error")
- Swap the live LLM in place via `session.llm.update_options(model=tag)` if the installed livekit-plugins-openai exposes it; else mutate the existing LLM instance's model attribute in place. NO AgentSession/Agent teardown, NO TTS recreation — effective on the next turn (same cost model as the persona/mode hot-swap). The exact setter is a `[VM-INTROSPECT]` probe against the installed signature; the in-place mutation fallback ships if no clean setter exists.
- Session persistence via a mutable holder `current_model[0]` alongside `current_persona` / `current_mode` / `current_role`; the client persists the selection in session state. A switch takes effect on the next turn without interrupting current TTS (LLM-02)
- Tag source: two env vars `OLLAMA_MODEL_FAST` / `OLLAMA_MODEL_BETTER` — the agent maps Fast/Better → tag. NO hardcoded gemma tag anywhere (continues the v1.0 no-hardcoded-tag invariant; `resolved_llm_tag()` generalizes to a Fast/Better resolver)

### Per-Build Verification (LLM-05 / LLM-06)
- Standalone verification script (`ollama/verify-build.sh` or `.py`) run at pull time, mirroring the `scripts/vram-validate.sh` operator-gate style — NOT an inline agent-startup check (avoids boot-latency cost)
- Checks: (a) chat template is present and sane, (b) thinking-off actually suppresses reasoning — no stray `<think>` / `<|channel|>` / `<|analysis|>` artifacts in streamed output (LLM-05)
- Fallback on a misbehaving build: documented + script-driven fall back to stock `gemma4:e2b` / `gemma4:e4b` (extend the pull ladder per model)
- Persona-guardrail check (LLM-06): a scripted abliterated-model probe asserting the persona's ethical boundary holds (security at interview-appropriate level, not step-by-step attack instructions). Operator-gated like the interview strong-vs-weak critique gate — documented runbook, signed on the real GPU

### Model Pull & Latency Preservation
- Extend `ollama/pull-and-pin.sh` to pull BOTH community tags and pin both env vars, each with its own fallback ladder rung (Fast → `gemma4:e2b`, Better → `gemma4:e4b`)
- Apply the SAME latency settings to both models — `reasoning_effort="none"` (thinking-off over Ollama /v1), token streaming, OLLAMA_KEEP_ALIVE, flash attention — no per-model divergence (LLM-04)
- Keep existing `num_ctx=8192` and the capped `num_predict` for both models, unchanged from v1.0
- VRAM safety: only ONE model resident at a time (keep-alive evicts the prior model on switch). Note the operator VRAM gate; defer the co-residency / placement story to Phase 10 (Part C)

### the agent's Discretion
- Exact RPC payload shape, holder naming, env-var defaults, and script language (bash vs python) are at the agent's discretion within the decisions above.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `web/app/InterviewPanel.tsx` — canonical side-panel + `performRpc` + `ApplyState` ack pattern to clone for ModelPanel (mode/role select → mode.update RPC)
- `web/app/PersonaPanel.tsx`, `web/app/KbPanel.tsx` — sibling side panels; ModelPanel slots alongside them
- `agent/main.py` `handle_mode_update` / `handle_persona_update` — validate-before-commit RPC handler pattern with mutable epoch holders (`current_mode`, `current_role`, `current_persona`) to clone for `current_model`
- `agent/main.py` `resolved_llm_tag()` — single-source-the-tag-from-env helper to generalize into a Fast/Better resolver
- `agent/main.py` `build_session()` — `openai.LLM.with_ollama(model=..., reasoning_effort="none")` is where the model tag is wired; the swap targets this LLM instance
- `ollama/pull-and-pin.sh` — fallback-ladder pull+pin script to extend for two models
- `scripts/vram-validate.sh` — operator-gate script style to mirror for `verify-build`

### Established Patterns
- RPC hot-swap: client `room.localParticipant.performRpc({ method, payload })` ↔ agent `register_rpc_method(...)` returning a native ack string ("applied"/"error")
- Mutable epoch holders (`current_*[0]`) compose rather than clobber; validate the untrusted RPC payload BEFORE mutating the shared holder (the Phase-6 mode.update fix)
- No hardcoded model tags — every tag resolves from an env var (`OLLAMA_MODEL` → now `OLLAMA_MODEL_FAST`/`OLLAMA_MODEL_BETTER`)
- Stack runs from baked Docker images: a phase touching agent/web MUST `docker compose build web agent && up -d` before live verification
- Operator-gated VM proofs are documented runbooks (`*-VERIFY.md`), unsigned until run on the real GPU

### Integration Points
- `web/app/VoiceRoom.tsx` — where the new ModelPanel is mounted alongside the other panels
- `agent/main.py` `entrypoint()` — register the new `model.update` RPC after `session.start`, add the `current_model` holder
- `docker-compose.yml` / `.env` — add `OLLAMA_MODEL_FAST` / `OLLAMA_MODEL_BETTER` env vars
- `ollama/pull-and-pin.sh` — extend to pull+pin both tags

</code_context>

<specifics>
## Specific Ideas

- Fast tag: `evalengine/unbound-e2b:latest`; Better tag: `defyma85/gemma-4-E4B-it-ultra-uncensored-heretic-Q4_K_M_gguf:latest` (from PROJECT.md / REQUIREMENTS.md LLM-03)
- Picker labels are OUTCOME labels only — no latency/token-speed numbers in the UI (REQUIREMENTS.md out-of-scope)
- Exactly two curated options — no model zoo (REQUIREMENTS.md out-of-scope)
- Per-session persistence; apply next turn — no per-turn / always-prompting switch (REQUIREMENTS.md out-of-scope)
- Persona prompt is UNCHANGED — it is the sole content guardrail (REQUIREMENTS.md out-of-scope: changing the persona prompt)

</specifics>

<deferred>
## Deferred Ideas

- Per-persona model defaults (LLM-F1) — future release
- A larger "Best" model tier on 24GB hardware (LLM-F2) — future release
- Two-model VRAM co-residency / STT placement coupling — Phase 10 (Part C)

</deferred>
