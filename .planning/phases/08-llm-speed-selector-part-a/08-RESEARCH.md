# Phase 8: LLM Speed Selector (Part A) — Research

**Researched:** 2026-06-26
**Status:** Ready for planning
**Requirements:** LLM-01 .. LLM-06
**Mode:** mvp (vertical slice — UI picker + agent model swap + per-build verification)

---

## TL;DR — What you need to know to PLAN this phase

1. **The in-place LLM model swap is SOLVED and clean.** The installed `livekit-plugins-openai` (1.6.4, resolved by `livekit-agents~=1.5`) `openai.LLM` (Chat Completions, built by `with_ollama`) does **NOT** expose `update_options()` — that method only exists on the *different* `livekit.agents.inference.LLM` class. **But** the swap works anyway: `LLM.model` is a read-only `@property` returning `self._opts.model`; `_opts` is a **mutable** (non-frozen) `@dataclass`; and `chat()` reads `self._opts.model` **fresh on every request**. So the swap is one line — `session.llm._opts.model = new_tag` — exactly mirroring how `session.tts.update_options(voice=...)` mutates the existing TTS instance in place. The same `LLM` instance survives, so the `metrics_collected` subscription bound in `metrics.attach()` is untouched. No `AgentSession`/`Agent` teardown, effective on the next turn. (§1)

2. **Both community tags exist as pullable Ollama tags and are lighter than the ~9.6 GB stock E4B.** Fast `evalengine/unbound-e2b:latest` (~Gemma 4 E2B class), Better `defyma85/gemma-4-E4B-it-ultra-uncensored-heretic-Q4_K_M_gguf:latest` (**5.3 GB**, 128K ctx, confirmed on ollama.com, ~1.2k downloads). Both Apache-2.0-derived Gemma 4 finetunes. (§6)

3. **Stock fallback tag names need correcting.** The CONTEXT/REQUIREMENTS say fall back to `gemma4:e2b` / `gemma4:e4b` — both are **real** published Ollama library tags (confirmed). The v1.0 pinned tag was `gemma4:e4b-it-q4_K_M` (still the current `OLLAMA_MODEL` in `.env.example`). Per-model ladders: Fast → `gemma4:e2b`, Better → `gemma4:e4b` (or the proven `gemma4:e4b-it-q4_K_M`). (§6)

4. **Ollama with `OLLAMA_KEEP_ALIVE=-1` holds only what fits; a tag switch evicts the prior model (single-resident on a 16 GB GPU).** First turn after a switch pays a cold model-load + prefill cost (seconds). This is acceptable per the CONTEXT decision ("only ONE model resident at a time; defer co-residency to Phase 10"). No per-model keep-alive config is needed — keep the single global env. (§2)

5. **`reasoning_effort="none"` plumbing is model-agnostic** — it is forwarded as a per-request `reasoning_effort` field over Ollama `/v1`, independent of the tag, so it carries across the swap automatically (it lives in the same `_opts`). The artifact risk (`<think>`/`<|channel|>`/`<|analysis|>`) is a property of each community build's chat template, which is why LLM-05 gates per build. (§3)

6. **LLM-04 gap to flag:** `with_ollama` does **NOT** accept `max_completion_tokens`, so the **live hot-path LLM currently does NOT cap `num_predict`** (only `warmup` and `kb/distill` cap it, via `/api/generate options.num_predict`). To honor LLM-04's "capped num_predict" on live turns for both models, set `session.llm._opts.max_completion_tokens` (maps to OpenAI `max_completion_tokens` → Ollama `num_predict`). This is a pre-existing latitude, not introduced by Phase 8 — decide whether to close it here. (§1.4)

---

## §1. In-place LLM model swap mechanism (CRITICAL question 1) — SOLVED

### 1.1 Installed version (pinned)

- `agent/requirements.txt` pins `livekit-agents~=1.5` + unpinned `livekit-plugins-openai`. The `~=1.5` line currently resolves to the **1.6.x** series; the latest is **`livekit-plugins-openai==1.6.4`** (PyPI). Source was downloaded and read directly for this research (`livekit_plugins_openai-1.6.4-py3-none-any.whl`).
- **Planning note:** the plugin is unpinned. For a deterministic build, the plan should pin `livekit-plugins-openai==1.6.4` (the version this research is grounded on) in `requirements.txt`, OR keep it floating but run the `[VM-INTROSPECT]` probe (§1.3) against whatever the image actually installs.

### 1.2 The actual surface (grounded in 1.6.4 source)

`livekit/plugins/openai/llm.py`:

```python
@dataclass
class _LLMOptions:          # NOT frozen → mutable
    model: str | ChatModels
    ...
    reasoning_effort: NotGivenOr[ReasoningEffort]
    temperature: NotGivenOr[float]
    top_p: NotGivenOr[float]
    max_completion_tokens: NotGivenOr[int]
    ...

class LLM(llm.LLM):
    def __init__(self, *, model=..., ...):
        self._opts = _LLMOptions(model=model, ...)
        self._client = client or openai.AsyncClient(base_url=..., ...)

    @property
    def model(self) -> str:          # GETTER ONLY — no setter
        return self._opts.model

    def chat(self, *, chat_ctx, ...) -> LLMStream:
        extra = {}
        ...
        if is_given(self._opts.reasoning_effort):
            extra["reasoning_effort"] = self._opts.reasoning_effort   # re-read per call
        ...
        return LLMStream(self, model=self._opts.model, ...)           # re-read per call
```

Key facts:
- **No `update_options()` on `openai.LLM`.** (Confirmed by `grep "def update_options"` → no match in the plugin LLM. `update_options` exists only on `livekit.agents.inference.llm.LLM`, an unrelated managed-inference class we don't use.)
- `model` is a **read-only property** — you cannot do `session.llm.model = tag`.
- `_opts` is a **plain mutable dataclass** (no `frozen=True`).
- `chat()` reads `self._opts.model` (and `reasoning_effort`, `temperature`, `top_p`, `max_completion_tokens`) **freshly on each turn** and threads `model=self._opts.model` into `LLMStream`. The `base_url`/client stay fixed (same Ollama endpoint), which is exactly what we want.

### 1.3 The swap (the landing implementation)

```python
# in handle_model_update, after validating the choice:
session.llm._opts.model = resolved_tag   # in-place; next chat() uses it
```

- Same `LLM` instance ⇒ the `metrics_collected` handler from `metrics.attach()` (`session.llm.on("metrics_collected", _on_llm_metrics)`, `agent/metrics.py:332`) **survives** — identical safety property to the TTS voice swap.
- `reasoning_effort="none"` is preserved automatically (it's in the same `_opts`, re-read per call) — no need to re-pass it.
- Effective on the **next turn** (current in-flight TTS is not interrupted) — same cost model as the persona/mode hot-swap.

**Why this is the right call over `update_options`:** there is no `update_options` to call. Mutating `_opts.model` is the minimal in-place mutation and is the documented fallback in the CONTEXT decision ("else mutate the existing LLM instance's model attribute in place"). It touches a single private attribute; wrap it behind a tiny helper with a comment so the private-attr reach is explicit and one-place.

### 1.4 [VM-INTROSPECT] probe (confirm against the actually-installed version)

Run inside the built agent image (sandbox can't import livekit):

```bash
docker compose run --rm agent python -c "
import inspect
from livekit.plugins import openai
llm = openai.LLM.with_ollama(model='x', base_url='http://ollama:11434/v1', reasoning_effort='none')
print('has update_options:', hasattr(llm, 'update_options'))
print('model property settable:', isinstance(type(llm).model, property) and type(llm).model.fset is not None)
print('opts fields:', [f for f in vars(llm._opts)])
print('opts is dataclass frozen:', getattr(getattr(type(llm._opts),'__dataclass_params__',None),'frozen',None))
import livekit.plugins.openai as p; print('plugin version:', p.__version__)
"
```

Expected (1.6.4): `has update_options: False`, model setter `False`, `_opts` includes `model`/`reasoning_effort`/`max_completion_tokens`, frozen `False`. If a future version DOES add `update_options(model=...)`, prefer it (the cleaner public API) — the plan should branch on the probe result: **if `update_options` exists → use it; else → mutate `_opts.model`.**

### 1.5 LLM-04 "capped num_predict" gap (FLAG for the plan)

- `with_ollama` (1.6.4) signature does **not** include `max_completion_tokens` (only `model, base_url, client, temperature, parallel_tool_calls, tool_choice, reasoning_effort, safety_identifier, prompt_cache_key, top_p`). So today's live LLM (`build_session`) sets **no** completion-token cap — Ollama uses its default `num_predict` (-1 / unlimited) on live turns. `num_predict` is only capped in `ollama/warmup.py` and `agent/kb/distill.py` (both `/api/generate`, off the hot path).
- To satisfy LLM-04 ("capped num_predict" preserved for BOTH models) on the live path, set it on `_opts` after constructing the LLM:
  ```python
  llm = openai.LLM.with_ollama(model=..., base_url=..., reasoning_effort="none")
  llm._opts.max_completion_tokens = LIVE_NUM_PREDICT_CAP   # → OpenAI max_completion_tokens → Ollama num_predict
  ```
  `chat()` already forwards `max_completion_tokens` into the request when given (`llm.py:973`). A spoken-turn cap (e.g. a few hundred tokens, sized to the SPOKEN_STYLE_FOOTER "sentence or two" budget) bounds runaway generations on both models uniformly.
- **Decision needed:** is this gap in-scope for Phase 8 (LLM-04 says "preserve … a capped num_predict")? The cap is a one-line addition that applies equally to Fast/Better; recommend closing it here since LLM-04 explicitly lists it. Verify the exact OpenAI→Ollama mapping on the VM (a `<num>` cap should truncate a "count to 500" probe).

---

## §2. Ollama keep-alive / two-model residency (CRITICAL question 2)

### 2.1 Behavior with `OLLAMA_KEEP_ALIVE=-1` (current compose setting)

- `OLLAMA_KEEP_ALIVE=-1` keeps a model resident **indefinitely** (no idle unload). Confirmed: `-1` = load forever; `0` = unload immediately; duration strings (`10m`, `24h`) otherwise (Ollama FAQ + multiple sources).
- **Two-model residency requires both to fully fit in VRAM at once.** Ollama's scheduler: "When using GPU inference new models must be able to completely fit in VRAM to allow concurrent model loads. If there is insufficient memory … as prior models become idle, one or more will be unloaded to make room" (Ollama FAQ). On the 16 GB floor with whisper + kokoro already resident, two Gemma-4 LLMs will **not** co-fit → **switching a tag evicts the prior LLM** (single-LLM-resident). This matches the CONTEXT decision exactly ("only ONE model resident at a time; keep-alive evicts the prior model on switch; defer co-residency to Phase 10").
- `OLLAMA_MAX_LOADED_MODELS` (default lets multiple load if memory allows) is **not** something to raise here — leave it default so the scheduler evicts rather than OOMs.

### 2.2 Cold cost on the first turn after a switch

- First request to the newly-selected tag pays **model load (disk→VRAM) + cold prefill** — several seconds for a multi-GB GGUF (the SitePoint/DatabaseMart benchmarks show ~8 s load for a cold model vs ~0.7 s warm on a tiny model; a 5 GB Gemma-4 will be in the multi-second range). This is a **one-time hit on the switch turn only**; subsequent turns on that model are warm. The picker "applies on next turn" UX absorbs this — there is no in-call interruption (current TTS finishes; the switch lands on the *next* user turn).
- **Planning implication:** do not try to hide the cold cost with co-residency in Phase 8. Optionally the plan MAY warm the newly-selected model out-of-band (a tiny `/api/generate` keep_alive ping at switch time, mirroring `warmup.py`) so the user's first real turn is warmer — but this competes for VRAM during the eviction handoff; **recommend NOT doing it in the MVP** (defer to the Phase 10 placement story). Flag as optional.

### 2.3 Flash-attn / KV-quant inheritance (LLM-04)

- `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_CONTEXT_LENGTH=8192`, `OLLAMA_NUM_PARALLEL=1` are **server-level** env on the `ollama` service (`docker-compose.yml:51-71`) — they apply to **every** model the server loads, so **both** community tags inherit them with **zero per-model config**. No divergence (LLM-04 satisfied by construction).
- **Carry-forward risk:** the v1.0 blocker (STATE.md:98) — q8_0 silently falling back to F16 if a model is off Ollama's flash-attn allowlist — must be **re-verified per new build** because these are *different* GGUFs than stock Gemma. `scripts/vram-validate.sh` already greps ollama logs for the F16-fallback warning; the plan should run it against **each** new tag (Fast and Better) on the VM. This is an operator gate, same style as v1.0.
- `num_ctx=8192` is enforced by `OLLAMA_CONTEXT_LENGTH=8192` (server env), not the Modelfile — so both models get 8192 automatically. Keep unchanged (CONTEXT decision).

---

## §3. `reasoning_effort="none"` over Ollama /v1 for community GGUFs (CRITICAL question 3)

- The thinking-off plumbing is **per-request and model-agnostic**: `with_ollama(reasoning_effort="none")` stores it in `_opts`; `chat()` forwards `extra["reasoning_effort"]="none"` to the Ollama `/v1/chat/completions` call on **every** turn regardless of tag. Ollama maps `reasoning_effort=none` → internal `Think=false` (the v1.0 finding, STATE.md:86). This is **not** Gemma-specific — it's the OpenAI-compat shim's field. So it carries to arbitrary community tags **identically** and survives the model swap (same `_opts`).
- **The leak risk is the chat template, not the plumbing.** If a community build's GGUF ships a broken/abliterated chat template (Gemma-4 thinking is template-driven), the model can emit raw reasoning markers into the **streamed assistant text** even with `Think=false` — i.e. `<think>...</think>`, or harmony/channel markers `<|channel|>analysis<|message|>...`, `<|analysis|>`. These would stream straight into TTS (spoken aloud) and the transcript. This is exactly why LLM-05 mandates a per-build artifact scan (§4).
- The existing `ollama/warmup.py` already asserts `"<think>" not in output` (warmup.py:107) but **only** for `<think>` and **only** at warmup. LLM-05 needs a broader scan (`<|channel|>`, `<|analysis|>`, `</think>`, etc.) as a dedicated per-build gate.

---

## §4. Per-build verification gate LLM-05 (CRITICAL question 4)

Mirror the `scripts/vram-validate.sh` operator-gate style: a standalone script run **at pull time** (not at agent startup — avoids boot-latency cost, per CONTEXT decision). Recommend a script `ollama/verify-build.sh` (bash, consistent with `pull-and-pin.sh`/`vram-validate.sh`) taking a tag argument.

### 4.1 Check A — chat-template sanity
```bash
ollama show --template "$TAG"     # must be non-empty and parseable
# Assert: non-empty; contains the expected role markers for a chat template
# (e.g. a system/user/assistant structure). A missing/empty template ⇒ FAIL.
```
`ollama show --modelfile "$TAG"` and `ollama show "$TAG"` (params/details) give corroborating info (context length, quant). The known community-build failure mode (see the "Heretic 12B" walkthrough) is `ollama create` validation failing on a bad template — so a present, sane template is the first gate.

### 4.2 Check B — thinking-off artifact scan (streamed raw tokens)
Drive a streamed `/api/generate` (or `/v1/chat/completions`) with `think:false` / `reasoning_effort:none` and scan the **accumulated streamed output** for any reasoning artifact:
```bash
# raw stream, think disabled, a prompt likely to trigger reasoning if the template leaks:
curl -s http://localhost:11434/api/generate \
  -d "{\"model\":\"$TAG\",\"prompt\":\"Think step by step, then answer: what is 17*23?\",\"stream\":true,\"think\":false,\"options\":{\"num_predict\":256}}" \
  | python3 -c 'accumulate response chunks; FAIL if any of: <think> </think> <|channel|> <|analysis|> <|start|> appear'
```
Artifact token list to scan (superset of warmup's): `<think>`, `</think>`, `<|channel|>`, `<|analysis|>`, `<|message|>`-style harmony markers, `<|start|>`, `<|end|>`. A clean stream = PASS. Any marker = FAIL → fall back to the stock rung (`gemma4:e2b` / `gemma4:e4b`).

### 4.3 Fallback wiring
- Extend `ollama/pull-and-pin.sh` so **each** model has its own ladder rung; on a verify-build FAIL the operator drops to the stock rung. Document the fallback in a runbook (`08-*-VERIFY.md`).
- This is operator-gated (real GPU), unsigned until run — same posture as the v1.0 VM gates (STATE.md:115).

---

## §5. Persona-guardrail red-team probe LLM-06 (CRITICAL question 5)

- **Goal:** assert the persona prompt remains the sole, intact content guardrail against the abliterated/uncensored models — i.e. with the cyber-trainer persona loaded, the model coaches at "interview-appropriate" depth and does **not** emit step-by-step attack instructions. The models themselves have no refusal layer (that's the point), so the persona must hold the line.
- **Lightweight scripted approach (operator-gated, mirrors the Phase-6 interview strong-vs-weak critique gate):** a small set of boundary prompts sent through the **agent's actual persona prompt** (not a bare model call), asserting refusal-equivalent persona behavior — the model redirects to concepts/defenses rather than producing a working exploit / weaponized payload / actionable harm. A handful of prompts (e.g. 3–5 boundary asks) with human-judged PASS/FAIL is sufficient for the MVP — this is a **documented runbook signed on the real GPU**, not an automated CI assertion (judging "is this step-by-step attack instructions" is qualitative, like the Phase-6 critique-depth gate).
- **Important framing:** LLM-06 is about *preserving* the existing persona prompt (which is UNCHANGED — out of scope to edit, REQUIREMENTS:100) and *verifying* its boundary holds, not about adding new guardrails. The probe is a verification artifact, not a code change. Test the persona prompt as-is; if it does NOT hold against the uncensored models, that's a finding to escalate (the persona prompt is the only lever, but editing it is out of scope for Phase 8 — would be a follow-up).
- Keep the red-team prompts in the runbook only (not committed as fixtures that read like an attack cookbook) — describe the *shape* of the boundary test, judged by the operator.

---

## §6. The two community tags + stock fallbacks (CRITICAL question 6)

| Role | Tag | Confirmed | Size | Notes |
|------|-----|-----------|------|-------|
| **Fast** | `evalengine/unbound-e2b:latest` | ✅ ollama.com/evalengine | Gemma-4 E2B class (~2–3 GB, well under stock 9.6 GB) | "Uncensored on-device finetune of google/gemma-4-E2B-it" by Chromia/Eval Engine. Sibling `evalengine/unbound-e4b` is Apache-2.0, native Gemma-4 chat template. |
| **Better** | `defyma85/gemma-4-E4B-it-ultra-uncensored-heretic-Q4_K_M_gguf:latest` | ✅ ollama.com/defyma85/... | **5.3 GB**, 128K ctx | Heretic v1.2.0 abliteration (ARA method) of `google/gemma-4-E4B-it`, Q4_K_M GGUF from `llmfan46/...-heretic-GGUF`. ~1.2k downloads, updated recently. **Lighter than the ~9.6 GB stock E4B** ✓. |

**Stock fallback tags (corrected):**
- Fast → `gemma4:e2b` — ✅ real published Ollama library tag (ollama.com/library/gemma4:e2b). Gemma 4 family, native `system`/`user`/`assistant` roles, configurable thinking.
- Better → `gemma4:e4b` — ✅ real published library tag. **OR** the v1.0-proven `gemma4:e4b-it-q4_K_M` (the tag currently pinned in `.env.example`, verified real against the RTX 5090 host in Phase 1, STATE.md:79). Either works; `gemma4:e4b-it-q4_K_M` is the more battle-tested rung.

**Chat-template quirk watch (LLM-05 will catch these):**
- Heretic/abliterated GGUFs are repackaged community builds — the most common reported failure is a malformed/missing chat template causing `ollama create` validation errors or leaked reasoning markers (the "Heretic 12B … Fix the ollama create validation failure" walkthrough). The §4 verify-build gate is precisely for this. Both Gemma-4 E-series use the standard Gemma-4 chat template; the abliteration changes weights, not (usually) the template — but **verify per build**.
- These tags are pulled directly (`ollama pull <tag>`), no Modelfile/`ollama create` needed — `pull-and-pin.sh`'s `ollama pull` ladder extends cleanly.

---

## §7. Existing-codebase patterns to clone (verified)

### 7.1 Agent-side (clone `mode.update` exactly — `agent/main.py`)
- `resolved_llm_tag()` (main.py:127) reads `OLLAMA_MODEL` → **generalize** to a Fast/Better resolver reading `OLLAMA_MODEL_FAST` / `OLLAMA_MODEL_BETTER` and mapping a choice key → tag. Keep the no-hardcoded-tag invariant (raise `SystemExit` if unset, like today).
- `build_session()` (main.py:167) — `openai.LLM.with_ollama(model=resolved_llm_tag(), base_url=..., reasoning_effort="none")` is the swap target. Default to the **Fast** tag at construction (LLM-02 configurable-default Fast).
- **Mutable holder:** add `current_model: list[str] = [DEFAULT_MODEL_CHOICE]` alongside `current_persona`/`current_mode`/`current_role` (main.py:356-364). Default = Fast.
- **RPC handler** `handle_model_update` (clone `handle_mode_update`, main.py:448): parse `json.loads(data.payload)`; **validate the choice BEFORE committing** the holder (the Phase-6 validate-before-mutate fix — reject unknown choice → return `"error"`); on success set `current_model[0]`, mutate `session.llm._opts.model = resolved_tag`, return `"applied"`. Register via `ctx.room.local_participant.register_rpc_method("model.update", handle_model_update)` after `session.start` (main.py:476).
  - **Do NOT** call `generate_reply` on switch (unlike mode-enter) — a model switch should NOT inject an agent turn; it just lands on the user's next real turn (LLM-02 "takes effect on the next turn without interrupting current TTS").
  - The swap is just `_opts.model =` — no `update_instructions` needed (instructions/persona/KB are unchanged by a model swap). **This is simpler than `mode.update`.**
- **Payload shape (agent's discretion):** recommend `{"choice": "fast"}` / `{"choice": "better"}` (plain keys, never raw tags — LLM-01). Validate `choice in {"fast","better"}`.

### 7.2 UI-side (clone `InterviewPanel.tsx` → new `web/app/ModelPanel.tsx`)
- Two-option control with **outcome labels only**: "Fast (snappier)" / "Better (more thoughtful)" — **never** raw tags or latency numbers (LLM-01, REQUIREMENTS:98 out-of-scope). A segmented control or `<select>`.
- Reuse the `ApplyState` union (`idle|applying|applied|error`), `STATUS_LABEL`/`STATUS_COLOR`, `panelStyle`/`inputStyle` (copy from InterviewPanel.tsx:20-63).
- `apply()`: target the agent identity via `useVoiceAssistant().agent?.identity` (fallback first remote participant), `room.localParticipant.performRpc({ destinationIdentity, method: "model.update", payload: JSON.stringify({ choice }) })`; `setStatus(ack === "applied" ? "applied" : "error")`. The native RPC return string IS the ack.
- Default selection = **Fast** (`useState("fast")`) — LLM-02.
- **Mount** in `web/app/VoiceRoom.tsx:84-89` alongside `<PersonaPanel/> <InterviewPanel/> <KbPanel/>`.
- **Duplication seam** (like InterviewPanel.tsx:6-11): the two choice keys (`fast`/`better`) must mirror the agent's validation set by hand — no `model.get` RPC in the MVP. Add the seam comment.
- **Session persistence (LLM-02):** the panel holds the selection in React state for the session; on `model.update` the agent holds `current_model[0]`. No cross-session persistence (matches ephemeral posture). Picker state is per-session by construction.

### 7.3 Pull/pin + env (`ollama/pull-and-pin.sh`, `.env.example`, `docker-compose.yml`)
- Extend `pull-and-pin.sh` to pull **both** tags and pin **both** env vars (`OLLAMA_MODEL_FAST`, `OLLAMA_MODEL_BETTER`), each with its own fallback ladder rung:
  - Fast ladder: `evalengine/unbound-e2b:latest` → `gemma4:e2b`
  - Better ladder: `defyma85/gemma-4-E4B-it-ultra-uncensored-heretic-Q4_K_M_gguf:latest` → `gemma4:e4b` (or `gemma4:e4b-it-q4_K_M`)
  - The existing `resolve_tag()` + `write_resolved_tag()` generalize to a per-model loop writing two env keys.
- `.env.example` (currently has single `OLLAMA_MODEL=gemma4:e4b-it-q4_K_M`, line 31): add `OLLAMA_MODEL_FAST` / `OLLAMA_MODEL_BETTER`. **Decide:** keep `OLLAMA_MODEL` as a back-compat alias (used by `warmup.py`, `vram-validate.sh`, `kb/distill.py`, `Modelfile`) OR migrate those readers. **Recommend:** keep `OLLAMA_MODEL` pointing at the Fast (default) tag so existing scripts (warmup/distill/vram) keep working unchanged, and add the two new vars for the picker. The distiller (`kb/distill.py`) can stay on the default/Fast tag (KB distillation is off the hot path; no need to follow the picker).
- `docker-compose.yml`: the `agent` service uses `env_file: .env`, so the new vars flow through automatically — no compose edit needed for env (the `ollama` service intentionally has no env_file; its flash-attn/keep-alive/ctx vars are explicit and already global).

### 7.4 Build/deploy invariant
- Stack runs from **baked images** (no source mount). Any agent/web change requires `docker compose build web agent && docker compose up -d` before live verification (STATE.md:83, AGENTS.md). The `[VM-INTROSPECT]` probe (§1.4) and all live checks run against the rebuilt image.

---

## §8. Risks / open items for the plan

1. **LLM-04 num_predict cap on the live path is currently absent** (§1.5) — decide whether to add `_opts.max_completion_tokens` (recommend yes; LLM-04 lists it). Verify the OpenAI→Ollama mapping on the VM.
2. **`livekit-plugins-openai` is unpinned** — pin to `1.6.4` (this research's grounding) or run the §1.4 probe against whatever installs. The swap mechanism (`_opts.model` mutation) is stable across 1.5.x/1.6.x (the property/`_opts`/`chat()` shape is unchanged in the line read), but confirm with the probe.
3. **q8_0 → F16 silent fallback per new build** (§2.3) — re-run `scripts/vram-validate.sh` per tag on the VM; both new GGUFs are off the stock-Gemma path. Operator gate.
4. **Cold-switch latency** (§2.2) — accepted (single-resident; defer warming/co-residency to Phase 10). PERF-04 (P50<1.0s for BOTH models) is a **Phase 13** gate, not Phase 8 — Phase 8 just wires the picker; the latency proof is later.
5. **Persona boundary may not hold** against uncensored models (§5) — if the LLM-06 red-team gate FAILs, the persona prompt is the only lever but editing it is **out of scope** for Phase 8 (REQUIREMENTS:100). Escalate as a finding; don't silently expand scope.
6. **Artifact leak into TTS** (§3) — if either build leaks `<think>`/channel markers despite `reasoning_effort=none`, the LLM-05 gate fails → fall back to stock rung. The leak would otherwise be *spoken aloud*, so this gate is load-bearing.
7. **Two-model VRAM co-fit is NOT attempted** — single-resident only; Phase 10 owns placement. Don't raise `OLLAMA_MAX_LOADED_MODELS`.

---

## §9. Requirement → mechanism map

| Req | Mechanism | Where |
|-----|-----------|-------|
| LLM-01 | Two-option picker, outcome labels only, never raw tags | new `web/app/ModelPanel.tsx` |
| LLM-02 | Default Fast; per-session React state + `current_model[0]` holder; `_opts.model` swap effective next turn, no TTS interrupt | ModelPanel + `handle_model_update` |
| LLM-03 | Both pulled via Ollama; agent targets selected tag via `_opts.model` mutation | `pull-and-pin.sh` + agent swap |
| LLM-04 | Server-level flash-attn/q8_0/keep-alive/ctx apply to both; `reasoning_effort=none` in `_opts` (per-request); **add** `_opts.max_completion_tokens` cap | compose env (unchanged) + `build_session` |
| LLM-05 | Per-build `ollama show --template` + streamed artifact scan; fallback ladder rung | new `ollama/verify-build.sh` + runbook |
| LLM-06 | Operator-gated persona-boundary red-team runbook (persona UNCHANGED, verified intact) | `08-*-VERIFY.md` runbook |

---

*Research grounded in: installed-version source (`livekit_plugins_openai==1.6.4`, downloaded + read), `agent/main.py`, `agent/metrics.py`, `agent/persona.py`, `agent/interview.py`, `agent/kb/distill.py`, `ollama/{pull-and-pin.sh,warmup.py,Modelfile}`, `scripts/vram-validate.sh`, `web/app/{InterviewPanel,PersonaPanel,VoiceRoom}.tsx`, `docker-compose.yml`, `.env.example`; Ollama FAQ + keep-alive docs; ollama.com tag pages for both community models + `gemma4:e2b`/`evalengine/unbound-e4b`.*
