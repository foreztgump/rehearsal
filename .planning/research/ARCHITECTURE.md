# Architecture Research

**Domain:** v1.1 integration into a shipped local-first LiveKit voice-agent stack — user-selectable Ollama LLMs, Nemotron streaming ASR with VRAM-aware placement, and a frontend-only TalkingHead avatar
**Researched:** 2026-06-26
**Confidence:** HIGH for integration points (verified against the real agent/web/compose code); MEDIUM for two installed-API signatures (`session.llm` retarget setter, LiveKit Nemotron STT plugin shape) — flagged `[VERIFY]` where the sandbox cannot import livekit, mirroring the codebase's own `[VM-INTROSPECT]` posture.

## What This Is

This document maps the FOUR v1.1 components (Part A LLM selector, Part B Nemotron STT service, Part C VRAM-aware STT placement, Part D avatar) onto the existing, shipped v1.0 architecture. It is an *integration* document, not a greenfield one: the v1.0 architecture (six-service Compose, one `AgentSession`, `persona.update`/`mode.update` RPC, frozen-prefix prompt, KB inline-cache, `HistoryWindowAgent`, speech_id metrics buffer) is the substrate and is NOT re-derived here — see `milestones/v1.0-rc1-ROADMAP.md` and the v1.0 section of this file's git history.

The keystone invariant carried forward: **per-turn TTFT must stay flat as the session grows**, and the avatar must add **zero** server change and **zero** latency. Parts A/B/C touch the server pipeline; **Part D MUST NOT.**

## Existing System (integration substrate — verified)

```
┌───────────────────────────────────────────────────────────────────────┐
│                       BROWSER  (web/, Next.js 16)                       │
│  VoiceRoom.tsx → <LiveKitRoom audio video={false}>                     │
│    RoomAudioRenderer (inbound Kokoro audio playout)                    │
│    AgentStatePill (useVoiceAssistant().state)                         │
│    PersonaPanel  → performRpc("persona.update")  ──┐                   │
│    InterviewPanel→ performRpc("mode.update")     ──┤ RPC to agent      │
│    KbPanel       → sendFile(topic="kb.upload")   ──┤ + kb.state attr   │
│    Transcript    (useTranscriptions())             │                   │
│    api/token/route.ts → mints JWT (server-side)    │                   │
└──────────┬──────────────────────────────┬──────────┴──────────────────┘
           │ WebRTC media + data/RPC       │ /api/token (Next route)
┌──────────▼───────────────────────────────▼───────────────────────────┐
│   proxy (Caddy 2.8, mkcert TLS)  :443 → web:3000  :7443 → livekit:7880 │
└──────────┬────────────────────────────────────────────────────────────┘
┌──────────▼────────────────────────────────────────────────────────────┐
│   livekit-server v1.10  (SFU, LAN-pinned ICE udp mux 7882)             │
└──────────┬────────────────────────────────────────────────────────────┘
           │ agent joins room as participant
┌──────────▼────────────────────────────────────────────────────────────┐
│   agent  (Python, livekit-agents~=1.5)  — agent/main.py               │
│   build_session(): AgentSession(                                       │
│     vad=silero(0.65),                                                  │
│     stt = openai.STT(base_url=WHISPER_BASE_URL, model=large-v3),       │  ← Part B replaces
│     llm = openai.LLM.with_ollama(model=resolved_llm_tag(),            │  ← Part A re-targets
│            base_url=OLLAMA_BASE_URL, reasoning_effort="none"),         │
│     tts = openai.TTS(base_url=KOKORO_BASE_URL, voice=...),             │
│     turn_handling={ MultilingualModel(), dynamic endpointing, ... })  │
│   HistoryWindowAgent(instructions=render_prompt(persona, kb_brief))   │
│   RPC: persona.update, mode.update | byte-stream: kb.upload           │
│   metrics.attach(session) → per-plugin metrics_collected, speech_id   │
└───┬──────────────────────┬───────────────────────┬────────────────────┘
    │ /v1 (whisper)         │ /v1 (ollama)          │ /v1 (kokoro)
┌───▼────────┐      ┌───────▼────────┐      ┌───────▼────────┐
│  whisper   │      │    ollama      │      │    kokoro      │
│ faster-    │      │ OLLAMA_MODEL   │      │ tts-1 / voice  │
│ whisper    │      │ (one tag)      │      │                │
└────────────┘      └────────────────┘      └────────────────┘
   all three reserve `count: all` GPU via deploy.resources (shared GPU)
```

**Verified integration anchors (file:line):**
- `agent/main.py:171` `build_session()` constructs the `AgentSession`; STT at `:173`, LLM at `:187`, TTS at `:192`.
- `agent/main.py:127` `resolved_llm_tag()` reads a SINGLE `OLLAMA_MODEL` env tag.
- `agent/main.py:402` `handle_persona_update` — the verified hot-swap pattern: validate → mutate holder → `agent.update_instructions(...)` (async, next-turn) + `session.tts.update_options(voice=...)` (sync, mutates existing instance so the metrics subscription survives).
- `agent/main.py:435/476` RPC registration (`register_rpc_method`).
- `agent/main.py:344` `metrics.attach(session)` binds `metrics_collected` to the EXISTING plugin instances — this is why hot-swaps mutate-in-place rather than reassign.
- `agent/metrics.py:318` `attach()` subscribes per-plugin `session.llm/stt/tts`; `agent/metrics.py:71` keys turn buffers by `speech_id`.
- `web/app/PersonaPanel.tsx:109` the `performRpc` pattern the model selector clones.
- `web/app/VoiceRoom.tsx:73` `<LiveKitRoom>` — the avatar mounts inside this.
- `docker-compose.yml:46/87/105` ollama/whisper/kokoro services with `deploy.resources.reservations.devices` GPU passthrough.

## Component Responsibilities (v1.1 delta)

| Component | New / Modified | Responsibility | Integration point |
|-----------|----------------|----------------|-------------------|
| Model selector UI | **NEW** `web/app/ModelPanel.tsx` | Fast/Better radio, default Fast, persists choice, sends `model.update` RPC | Clone of `PersonaPanel.tsx` pattern; mount in `VoiceRoom.tsx` |
| `model.update` RPC handler | **MODIFIED** `agent/main.py` | Validate tag key → re-target LLM plugin → applies next turn | New `register_rpc_method` alongside persona/mode |
| Two-tag config | **MODIFIED** `.env` + `agent/main.py` | `OLLAMA_MODEL_FAST` / `OLLAMA_MODEL_BETTER` / `OLLAMA_MODEL_DEFAULT` | Replaces single `OLLAMA_MODEL` consumption |
| Model pull/pin | **MODIFIED** `ollama/pull-and-pin.sh` | Pull/verify BOTH community GGUFs with per-build template + thinking-off check, stock fallback ladder | Extends existing ladder |
| NeMo ASR server | **NEW** Compose service `nemo-stt` (GPU) | `nvidia/nemotron-speech-streaming-en-0.6b` behind local HTTP, streaming partials + ~100ms finalize | New service on `adept` net |
| CPU-ONNX ASR | **NEW** Compose service `nemo-stt-cpu` (no GPU) | 4-bit ONNX port, ~0.67GB RAM, off-GPU | New service; one of the two is wired per session |
| STT plugin wiring | **MODIFIED** `agent/main.py` `build_session()` | Point LiveKit STT plugin at the resolved NeMo endpoint instead of whisper | Replaces `openai.STT(...)` at `:173` |
| STT placement resolver | **NEW** `agent/placement.py` (pure module) | At session start: pick GPU-NeMo vs CPU-ONNX from selected LLM + VRAM headroom; global-CPU-ONNX fallback | Called in `entrypoint` before `build_session` |
| Avatar layer | **NEW** `web/app/avatar/*` | TalkingHead GLB render, HeadAudio Path-A lip-sync on inbound track, barge-in via existing interrupt, persona→GLB map | Mounts inside `<LiveKitRoom>`; **no server touch** |
| Avatar toggle | **NEW** in `VoiceRoom.tsx` | "Voice only / Avatar" (default Voice only); voice-only unmounts ALL avatar code | Conditional render boundary |
| Consumer-GPU passthrough | **MODIFIED** `docker-compose.yml` | `--gpus all` / NVIDIA Container Toolkit path instead of Proxmox PCIe | `deploy.resources` already correct; doc/runtime shift |

## Part A — LLM Model Selector (server pipeline)

### Integration: client UI → signal → agent re-target

**The pattern to clone is `persona.update` (verified at `agent/main.py:402–437`).** The model selector is its near-exact twin, one axis narrower (no KB compose, no TTS swap).

**1. Client (`web/app/ModelPanel.tsx`, NEW).** Copy `PersonaPanel.tsx` structure:
- State: `model: "fast" | "better"`, default `"fast"`; `ApplyState` union for the applying→applied pill.
- Persistence: `sessionStorage` (per-session, single user) — read on mount, write on change. (Server is authoritative for the *default*; the client just remembers the in-session pick.)
- On Apply: resolve `agentIdentity` (same `agent?.identity ?? fallback` guard as PersonaPanel:98), then:
  ```ts
  const ack = await room.localParticipant.performRpc({
    destinationIdentity: agentIdentity,
    method: "model.update",
    payload: JSON.stringify({ model }),   // "fast" | "better"
  });
  setStatus(ack === "applied" ? "applied" : "error");
  ```
- Mount in `VoiceRoom.tsx:84` flex row alongside the other panels.

**2. Signal.** A new LiveKit RPC method `model.update` — same transport as `persona.update`/`mode.update`. Payload is a tiny `{model: "fast"|"better"}` key, NOT a raw Ollama tag (untrusted boundary: validate the KEY, never let the client inject an arbitrary tag string).

**3. Agent re-target (`agent/main.py`, MODIFIED).** Add a `current_model` mutable holder beside `current_persona`/`current_mode`/`current_role` (the established "epoch holder" idiom at `:356–364`). Register a handler:
```python
MODEL_TAGS = {  # resolved once at startup from env
    "fast":   os.environ["OLLAMA_MODEL_FAST"],
    "better": os.environ["OLLAMA_MODEL_BETTER"],
}
current_model = [os.environ.get("OLLAMA_MODEL_DEFAULT", "fast")]

async def handle_model_update(data):
    snapshot = json.loads(data.payload)
    choice = snapshot.get("model")
    if choice not in MODEL_TAGS:
        logger.warning("model.update rejected: unknown model %r", choice)
        return "error"
    current_model[0] = choice
    # Re-target the EXISTING llm plugin instance — do NOT reassign session.llm,
    # which would drop the metrics_collected subscription bound in metrics.attach().
    session.llm.update_options(model=MODEL_TAGS[choice])   # [VERIFY] setter name
    return "applied"

ctx.room.local_participant.register_rpc_method("model.update", handle_model_update)
```

**Why no AgentSession teardown:** identical reasoning to the persona TTS swap (`agent/main.py:391–394` comment). `metrics.attach()` (`agent/metrics.py:333`) binds `metrics_collected` to the EXISTING `session.llm` instance. Mutating that instance in place preserves the subscription; reassigning `session.llm = openai.LLM.with_ollama(...)` would orphan it and break the speech_id turn buffer. So the model swap MUST be a mutate-in-place setter on the current plugin.

**`[VERIFY]` the setter.** The codebase has a verified `session.tts.update_options(voice=...)` (`agent/main.py:431`). The OpenAI LLM plugin's `update_options` accepting `model=` is the analogous call but is NOT yet exercised in this repo — confirm against the installed `livekit-plugins-openai` with `inspect.signature(openai.LLM.update_options)` (same `[VM-INTROSPECT]` discipline as `agent/main.py:221`). **Fallback if no `model` setter exists:** reassign `session.llm` AND re-run the LLM half of `metrics.attach` (re-subscribe `_on_llm_metrics` to the new instance). Add a `metrics.reattach_llm(session)` helper to keep this one-line and explicit. This fallback is robust but slightly heavier; prefer the in-place setter.

**4. Per-session persistence + next-turn application.**
- *Next-turn application* is automatic and free: `update_instructions` (persona) is async/next-turn because the agent reads instructions when it builds the next reply; likewise the LLM plugin reads its `model` option when it issues the next completion. A swap mid-turn applies to the next turn — exactly the persona semantics. No debounce needed; last-write-wins is idempotent.
- *Persistence* is two-layered: client `sessionStorage` remembers the pick across reloads within the session; the `current_model[0]` holder is the server-side source of truth for the live session. There is NO cross-session persistence (out of scope — single-user ephemeral). The configurable *default* is `OLLAMA_MODEL_DEFAULT` in `.env`, read once at `entrypoint`.

**Flat-TTFT note:** the first turn after a model switch pays a cold-prefill cost on the newly-selected tag (its KV cache is empty / it may need loading). This is the SAME expected one-turn elevation documented for persona/KB swaps (`agent/main.py:394`). To keep it bounded: both tags should stay resident (`OLLAMA_KEEP_ALIVE=-1` already set, `docker-compose.yml:59`) — but two resident models is a VRAM cost that Part C's placement math must account for (see Part C).

**5. Startup (`prewarm`/warmup, MODIFIED).** `agent/main.py:258 prewarm` and `ollama/warmup.py` warm ONE tag today. v1.1 must warm BOTH tags so the first switch isn't a cold load, OR warm only the default and accept a one-turn cold cost on first switch. Given the 16GB floor and Part C, warming both resident may not co-fit with E4B+STT+TTS — **the placement decision (Part C) and the keep-both-resident decision are coupled.** Recommended: keep the DEFAULT (Fast) resident; load Better on first selection (Ollama keep_alive holds it after). The pull/pin ladder (`ollama/pull-and-pin.sh`) extends to resolve and verify both community GGUF tags with per-build chat-template + thinking-off checks (the `warm_llm` `<think>` assertion at `ollama/warmup.py:107` becomes a per-tag gate), falling back to stock `gemma4:e2b`/`gemma4:e4b` rungs.

## Part B — Nemotron Streaming ASR Service (server pipeline)

### New Compose service + STT plugin rewire

**1. New service `nemo-stt` (GPU).** Mirrors the `whisper` service shape (`docker-compose.yml:87–103`) — GPU reservation, LAN-bound port, on the `adept` network:
```yaml
nemo-stt:
  build: ./nemo-stt        # NeMo + torch image; ~several GB, ~10-min first build
  ports:
    - "${LAN_BIND_IP:-127.0.0.1}:8010:8010"
  networks: [adept]
  deploy:
    resources:
      reservations:
        devices: [{ driver: nvidia, count: all, capabilities: [gpu] }]
  restart: unless-stopped
```
The container serves `nvidia/nemotron-speech-streaming-en-0.6b` (600M Cache-Aware FastConformer-RNNT) behind a local HTTP server exposing streaming transcription, with the `att_context_size [56,3]` knob as an env/config param. NeMo+torch is a several-GB, ~10-min first install — account for it in the build (this is a known v1.1 Context note, PROJECT.md:106).

**2. STT plugin rewire (`agent/main.py:173`, MODIFIED).** Today the STT is `openai.STT(base_url=WHISPER_BASE_URL, model=WHISPER_MODEL, ...)`. v1.1 replaces this with the LiveKit Nemotron STT plugin per LiveKit's Nemotron voice-agent example. Two shapes are possible and must be `[VERIFY]`'d against the installed plugin:
- (a) A dedicated `livekit-plugins-nvidia` (or similarly named) NeMo streaming STT plugin pointed at `NEMO_STT_BASE_URL`.
- (b) If the NeMo HTTP server is OpenAI-`/v1/audio`-compatible with streaming, keep `openai.STT` and just repoint `base_url` — lowest-friction, reuses the verified plugin and the metrics subscription unchanged.

Whichever shape, the STT instance is built in `build_session()` and `metrics.attach()` binds `_on_stt_metrics` to it unchanged (`agent/metrics.py:258`). The STT metrics handler has a documented limitation (no `speech_id`, attaches to the most-recently-touched buffer, `agent/metrics.py:66`) — this is unchanged by the swap.

**3. Data flow — streaming partials + finalize.**
```
User speaks → WebRTC user audio track → livekit-server → agent
  → silero VAD + MultilingualModel turn detection (UNCHANGED, agent/main.py:242)
  → NeMo STT plugin streams audio frames to nemo-stt HTTP server
      → growing partial transcripts (native streaming) → useTranscriptions() shows growth
      → ~100ms after end-of-speech: FINAL transcript (native punctuation + caps)
  → final transcript → LLM (selected Ollama tag) → first-sentence Kokoro TTS (UNCHANGED)
```
The turn-detection layer (Silero VAD activation 0.65 + MultilingualModel semantic endpointing) is **upstream of STT and unchanged** — Nemotron's ~100ms finalize tightens the STT leg of the latency budget (`metrics.BUDGET_MS["stt"]=150`, `agent/metrics.py:34`) but the EOU decision still comes from the existing turn detector. Barge-in is unchanged (it's VAD-driven in the AgentSession, not STT-driven). Native punctuation/caps means the agent no longer needs whisper's `vad_filter`/`language=en` param block (`agent/main.py:68–73`) — those become NeMo-server config.

**4. Removed service.** `whisper` (`docker-compose.yml:87`) is removed once `nemo-stt` is wired and verified. `WHISPER_*` env and `WHISPER_PARAMS` in `agent/main.py` are deleted. `ollama/warmup.py` `warm_whisper` (`:118`) becomes `warm_nemo` (or is dropped if the NeMo server self-warms). The `vram-validate.sh` "3 GPU processes (ollama, whisper, kokoro)" assertion (`scripts/vram-validate.sh:147`) updates to the new process set per the chosen placement.

## Part C — VRAM-Aware STT Placement (server pipeline)

### Where the decision executes

**Decision point: session start, in `agent/main.py entrypoint`, BEFORE `build_session()`.** It is resolved exactly ONCE per session and never re-evaluated mid-session (no thrashing — explicit Out-of-Scope, PROJECT.md:91). The cleanest seam: a new pure module `agent/placement.py` (mirrors `history.py`/`interview.py`: pure decision, livekit-free, `_self_check()`-able in the sandbox) that returns which STT runtime to use; `entrypoint` applies the effect by choosing the STT base_url/plugin for `build_session()`.

```python
# agent/placement.py  (NEW, pure)
STT_GPU  = "gpu_nemo"
STT_CPU  = "cpu_onnx"

def resolve_stt_placement(selected_model: str, *, force_cpu: bool) -> str:
    """Pick the STT runtime ONCE at session start.
    force_cpu = the simplest-robust global fallback flag (env-driven).
    """
    if force_cpu:
        return STT_CPU
    # Fast/E2B leaves GPU headroom → full NeMo on GPU.
    # Better/E4B makes headroom tight → CPU-ONNX off-GPU.
    return STT_GPU if selected_model == "fast" else STT_CPU
```

```python
# agent/main.py entrypoint (MODIFIED), before build_session:
force_cpu = os.environ.get("STT_FORCE_CPU", "false").lower() == "true"
placement = placement_mod.resolve_stt_placement(current_model[0], force_cpu=force_cpu)
session = build_session(ctx.proc.userdata["vad"], stt_placement=placement)
```

`build_session()` gains a `stt_placement` arg and selects the STT endpoint:
- `STT_GPU` → NeMo plugin pointed at `nemo-stt:8010` (the GPU service).
- `STT_CPU` → NeMo plugin pointed at `nemo-stt-cpu:8011` (the CPU-ONNX service).

**The coupling to the LLM selection** is the input `current_model[0]`. Because placement is resolved at session start and the model can be switched *mid-session*, there is a subtlety: a session that starts on Fast (GPU-STT) and switches to Better mid-session would, in principle, want to move STT to CPU — but mid-session STT thrash is explicitly forbidden. **Resolution (the robust path): the global-CPU-ONNX fallback removes the conflict entirely** (below). Without the global fallback, the safe rule is: placement is fixed at start from the start-of-session model; a mid-session upgrade to Better is allowed only if the start-of-session GPU-STT placement still co-fits Better+GPU-STT+Kokoro (which is exactly the case the measurement may show it does NOT — hence the fallback is the recommended default).

### The simplest-robust global-CPU-ONNX fallback (recommended default path)

PROJECT.md:107 and Decision 146 state the preferred fallback: **if measurement shows E4B + GPU-STT + Kokoro can't co-fit on the target GPU, default STT to CPU-ONNX globally for BOTH LLM choices.** This is the simplest-robust path because:

1. **It eliminates the per-session decision branch.** `STT_FORCE_CPU=true` in `.env` → `resolve_stt_placement` returns `STT_CPU` regardless of model → STT is ALWAYS the off-GPU CPU-ONNX service.
2. **It makes the model picker VRAM-safe with zero runtime switching.** Both Fast and Better get the full GPU for LLM+KV+TTS; STT's ~0.67GB lives in CPU RAM (>6× realtime, negligible WER loss). A mid-session Fast↔Better switch never needs an STT move because STT isn't on the GPU at all.
3. **It is a single env flag**, set once after the operator runs the co-fit measurement (`scripts/vram-validate.sh`, extended to test the E4B+GPU-STT+Kokoro peak). No code branch is exercised at runtime beyond the `force_cpu` short-circuit.

**Compose for the fallback:** the `nemo-stt-cpu` service has NO `deploy.resources` GPU block (CPU/RAM only). When `STT_FORCE_CPU=true`, the GPU `nemo-stt` service can even be omitted from the active profile (Compose `profiles:`) to save the image pull and any idle reservation. Recommended: gate the two STT services behind Compose profiles (`stt-gpu` / `stt-cpu`) so only the chosen one boots.

**Build-order implication:** Part C's decision *cannot be finalized in code until the operator runs the co-fit measurement on the target consumer GPU.* So Part C ships the mechanism (both services + `placement.py` + the `STT_FORCE_CPU` flag) with the global-CPU-ONNX fallback as the SAFE DEFAULT, and the operator flips to the per-model GPU/CPU split only if the measurement proves E4B+GPU-STT+Kokoro co-fits. This is the same "ship the safe fallback, operator-gate the optimization" posture as the v1.0 endpointing profile (`agent/main.py:99–117`) and VRAM proof (`scripts/vram-validate.sh`).

## Part D — Avatar (FRONTEND-ONLY — the isolation boundary)

### The unambiguous no-server-change boundary

**Part D touches ONLY `web/`. It adds ZERO files under `agent/`, ZERO Compose services, ZERO env consumed by the server, and ZERO new server data paths.** Everything it needs already flows: the inbound Kokoro audio track (already rendered by `RoomAudioRenderer`, `VoiceRoom.tsx:81`) and the existing user-speech-start interrupt signal (already emitted by the AgentSession for barge-in). The server pipeline (Parts A/B/C) is byte-for-byte unaware the avatar exists.

```
                  ┌─────────────── SERVER (untouched by Part D) ───────────────┐
User speaks ─────▶│ VAD/turn-detect → NeMo STT → Ollama LLM → Kokoro TTS       │
                  └───────────────────────────┬───────────────────────────────┘
                                              │ inbound WebRTC audio track (Kokoro)
                                              │ + user-speech-start signal (existing)
┌─────────────────────────────────────────────▼──────────────────────────────┐
│   BROWSER  <LiveKitRoom>                                                     │
│   ── Voice only (default) ──────────────────────────────────────────────┐   │
│   │ RoomAudioRenderer plays inbound audio. NO avatar code mounted.       │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│   ── Avatar mode (opt-in) ──────────────────────────────────────────────┐   │
│   │ <AvatarStage>:                                                       │   │
│   │   • TalkingHead renders persona→GLB (Three.js/WebGL, client-only)    │   │
│   │   • HeadAudio worklet taps the SAME inbound track → viseme detection │   │
│   │     (Path A: audio-driven, no timestamps, no transcription)          │   │
│   │   • on user-speech-start (existing interrupt) → streamInterrupt()    │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### How it bolts on (web only)

**1. Toggle + mount boundary (`web/app/VoiceRoom.tsx`, MODIFIED — the only modified existing file).** Add a `viewMode: "voice" | "avatar"` state (default `"voice"`, persisted in `sessionStorage`). Conditionally render `<AvatarStage>` ONLY when `viewMode === "avatar"`. When `"voice"`, the avatar subtree is unmounted — React unmounts the TalkingHead canvas, the HeadAudio AudioWorklet is disconnected/closed, no RAF loop runs, no GLB is fetched. **Voice-only is byte-for-byte the pre-avatar build with zero residual overhead** because the code path is gated at the component-mount boundary, not merely hidden with CSS. (Dynamic-import the avatar bundle with `next/dynamic ssr:false` so the TalkingHead/Three.js code isn't even in the initial JS for voice-only users.)

**2. Audio tap — Path A (`web/app/avatar/HeadAudio*`, NEW).** Get the inbound agent audio track from the room (the same track `RoomAudioRenderer` plays — `useVoiceAssistant().audioTrack` or the agent participant's audio publication). Route its `MediaStreamTrack` through the HeadAudio AudioWorklet, which does audio-driven viseme detection and drives the GLB's ARKit(52)/Oculus(15) viseme blendshapes. No server timestamps, no transcription, TTS stays server-side Kokoro. The tap is read-only — it does NOT intercept or replace `RoomAudioRenderer` playout (audio still plays normally); it observes a fork of the same stream.

**3. Barge-in reuse (`web/app/avatar/*`, NEW).** Subscribe to the EXISTING user-speech-start signal that already drives server-side barge-in. In LiveKit components this surfaces via the room/agent state (e.g. local mic activity / the same VAD-driven event the AgentSession uses). On that signal, call TalkingHead's `streamInterrupt()` to stop the avatar's mouth animation immediately — mirroring how the server already cancels TTS. **No second VAD, no new turn-taking source** (Decision 149). The avatar's interrupt is purely cosmetic; the server's barge-in is the source of truth and is unchanged.

**4. Persona → GLB mapping.** Persona config extends so each persona maps to an avatar GLB + mood. **Critical isolation rule:** this mapping lives **client-side** (a `web/app/avatar/personaAvatars.ts` lookup keyed by the persona the client already knows). It must NOT add fields the *server* prompt renderer consumes — `agent/persona.py`'s `render_prompt` and the frozen prefix MUST stay byte-identical (the KB-cache invariant, `agent/persona.py:116`). The persona panel already holds the full persona snapshot client-side (`PersonaPanel.tsx:24`); the avatar reads `display_name`/an avatar key from that same client state to pick the GLB and mood. If a per-persona avatar key is desired, add it as a CLIENT-ONLY field that is NOT sent in the `persona.update` payload (or is ignored by the server — `Persona(**snapshot)` would reject an extra key with TypeError at `agent/main.py:416`, so it must NOT be added to the RPC payload). Keep the avatar key out of the RPC entirely; derive it client-side from `display_name`/a local persona id.

**5. Performance constraints (client WebGL).** ~30fps target, Meshopt/Draco GLB compression, graceful degradation. ZERO server VRAM cost (rendering is client GPU/WebGL). This adds NO latency to the voice loop because it's a passive observer of an already-flowing track.

### Isolation checklist (for the roadmapper / quality gate)
- [ ] No file under `agent/` changed for Part D.
- [ ] No Compose service added/changed for Part D.
- [ ] No new `register_rpc_method` / byte-stream / participant-attribute on the server for Part D.
- [ ] `persona.update` payload schema unchanged (`Persona(**snapshot)` still accepts it).
- [ ] Voice-only mode dynamic-imports nothing avatar-related; AudioWorklet + canvas fully unmounted.
- [ ] Avatar interrupt subscribes to the EXISTING barge-in signal, adds no VAD.

## Part E — Deployment: Consumer-GPU Passthrough (Compose)

**Drop the Proxmox VM; `docker compose up` on the user's machine.** The existing GPU reservation blocks (`docker-compose.yml:78–84` ollama, `:96–102` whisper→nemo-stt, `:116–122` kokoro) already use the modern Compose `deploy.resources.reservations.devices` form, which the NVIDIA Container Toolkit honors directly on a consumer host with `--gpus`/the toolkit installed. The change is primarily environmental, not structural:

| Concern | v1.0 (Proxmox VM) | v1.1 (consumer machine) |
|---------|-------------------|--------------------------|
| GPU exposure | VM PCIe passthrough | NVIDIA Container Toolkit (`nvidia-ctk runtime configure`) + existing `deploy.devices` |
| `LIVEKIT_NODE_IP` / `LAN_BIND_IP` | VM LAN IP | host LAN IP (or `127.0.0.1` for local-only) |
| GPU detection | assumed present | add a preflight (`nvidia-smi` / toolkit check) and a clear failure message |
| STT placement default | n/a | `STT_FORCE_CPU` default set per Part C measurement on the consumer GPU |

**Compose deltas:**
- Remove `whisper`; add `nemo-stt` (GPU) and `nemo-stt-cpu` (CPU), gated behind `profiles: [stt-gpu]` / `[stt-cpu]` so only the chosen runtime boots.
- `agent` `depends_on` updates: drop `whisper`, add the active STT service.
- `.env` gains `OLLAMA_MODEL_FAST`, `OLLAMA_MODEL_BETTER`, `OLLAMA_MODEL_DEFAULT`, `STT_FORCE_CPU`, `NEMO_STT_BASE_URL` (+ CPU variant), `NEMO_ATT_CONTEXT_SIZE`.
- README/runbook: consumer-GPU toolkit setup replaces the Proxmox passthrough section.

## New vs Modified — explicit inventory

**NEW files/services:**
- `web/app/ModelPanel.tsx` (Part A client)
- `agent/placement.py` (Part C pure decision module)
- `nemo-stt/` build context + Compose service `nemo-stt` (Part B GPU)
- Compose service `nemo-stt-cpu` (Part C CPU-ONNX)
- `web/app/avatar/*` — `AvatarStage.tsx`, `HeadAudio` worklet glue, `personaAvatars.ts` (Part D, client-only)
- GLB assets under `web/public/avatars/` (Part D, licensing-gated, no redistribution)

**MODIFIED files:**
- `agent/main.py` — add `model.update` handler + `current_model` holder; replace `openai.STT` whisper wiring with NeMo placement-resolved STT; call `resolve_stt_placement` in `entrypoint`; `build_session(stt_placement=...)` signature.
- `agent/metrics.py` — possibly add `reattach_llm()` IF the `session.llm.update_options(model=)` setter doesn't exist (fallback path only).
- `ollama/pull-and-pin.sh` + `ollama/warmup.py` — two-tag pull/verify with per-build template + thinking-off checks; warm default tag.
- `web/app/VoiceRoom.tsx` — mount `ModelPanel`; add `viewMode` toggle + gated `<AvatarStage>` (the ONLY existing web file Part D touches).
- `docker-compose.yml` — remove `whisper`; add `nemo-stt`/`nemo-stt-cpu` with profiles; update `agent.depends_on`.
- `.env` / `.env.example` — new model/STT/placement vars.
- `scripts/vram-validate.sh` — co-fit measurement for E4B+GPU-STT+Kokoro; GPU-process-count assertion updated per placement.

**UNCHANGED (must stay so):**
- `agent/persona.py` (frozen-prefix renderer — byte-stable; Part D avatar key stays client-side).
- `agent/history.py`, `agent/interview.py`, `agent/kb/*` (history window, interview prompt, KB pipeline).
- `agent/main.py` `handle_persona_update` / `handle_mode_update` / KB ingest (the avatar adds nothing here).
- `web/app/PersonaPanel.tsx`, `InterviewPanel.tsx`, `KbPanel.tsx`, `Transcript.tsx`, `AgentStatePill.tsx`, `api/token/route.ts`.
- The frozen prompt prefix, KB inline-cache, `HistoryWindowAgent` truncation, speech_id metrics buffer.

## Data-Flow Changes (summary)

1. **Voice turn (modified STT leg only):** `audio → VAD/turn-detect (unchanged) → NeMo STT (was whisper) → Ollama LLM (selected tag) → first-sentence Kokoro TTS (unchanged) → audio`. STT finalize tightens from whisper's ~120–250ms toward ~100ms.
2. **Model switch (new):** `ModelPanel → performRpc("model.update") → agent validates key → session.llm.update_options(model=tag) → applies next turn`. One-turn cold-prefill cost on the new tag (expected, bounded by keep_alive).
3. **STT placement (new, session-start only):** `entrypoint → resolve_stt_placement(model, force_cpu) → build_session picks nemo-stt | nemo-stt-cpu endpoint`. Never re-runs mid-session.
4. **Avatar (new, client-only, passive):** `inbound Kokoro track → HeadAudio worklet → visemes`; `existing user-speech-start → streamInterrupt()`. No server data path.

## Suggested Build Order

Ordered to respect the flat-TTFT invariant (each server change re-proves the latency/VRAM gates before the next stacks on) and to keep the avatar's no-server-change boundary last and isolated:

1. **Part A — LLM selector** (lowest risk; clones a verified RPC pattern). Two-tag env + pull/pin with per-build template/thinking-off verification + stock fallback → `model.update` RPC + `current_model` holder → `ModelPanel.tsx`. **Gate:** persona-swap-equivalent one-turn TTFT bump only; flat-TTFT holds across switches; thinking-off verified for both GGUFs (the content-guardrail-is-persona-only invariant rides on this).
2. **Part B — Nemotron STT service + rewire** (replaces a pipeline stage; must re-prove the STT latency budget). Build `nemo-stt` (GPU) → rewire `build_session` STT plugin → drop `whisper` → update warmup/metrics. **Gate:** streaming partials visible in transcript, ~100ms finalize, native punctuation/caps, voice-to-voice P50 still < 1.0s.
3. **Part C — VRAM-aware placement + CPU-ONNX fallback** (depends on B existing; needs the consumer-GPU co-fit measurement). Add `nemo-stt-cpu` + `placement.py` + `STT_FORCE_CPU` + Compose profiles → run `vram-validate.sh` co-fit measurement → set the safe default (global CPU-ONNX unless E4B+GPU-STT+Kokoro proves to co-fit). **Gate:** both LLM choices VRAM-safe at session start with no mid-session thrash; fallback flag proven.
4. **Part E — Consumer-GPU deployment** (folds in alongside/after C since C's default depends on the target-GPU measurement). Toolkit preflight + GPU-detection failure message + `.env`/README shift off Proxmox. **Gate:** `docker compose up` on a consumer GPU brings the full stack up with the resolved STT placement.
5. **Part D — Avatar** (LAST and ISOLATED; server is frozen by this point). Dynamic-imported `<AvatarStage>` + HeadAudio Path-A tap + existing-interrupt barge-in + client-side persona→GLB map + default-off toggle. **Gate:** voice-only is byte-for-byte the pre-avatar build (no avatar JS loaded, worklet/canvas unmounted); avatar adds no latency; isolation checklist all-green; **no `agent/`, Compose, or RPC change introduced.**
6. **v1.0 polish (deferred Phase 7, rolled in):** session controls (new/reset/end + ephemeral teardown incl. KB), transcript export, mic-denial prompt, garbled-STT reprompt, final P50<1.0s/P95<1.5s tuning. Slots after the pipeline is stable; the garbled-STT reprompt couples to Part B's NeMo finalize behavior.

**Ordering rationale:** A before B because A is a contained RPC clone that doesn't perturb the latency path's structure; B before C because placement can't be measured without the NeMo service existing; C before/with E because the consumer-GPU measurement sets C's default; D strictly last because the server pipeline must be frozen and proven before a frontend-only layer observes it — this makes the "Part D changed nothing server-side" claim trivially auditable (the server diff is empty after step 4).

## Integration Points

### External services (all local)
| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| ollama (two tags) | `openai.LLM.with_ollama(model=tag)`; mutate via `session.llm.update_options(model=)` | `[VERIFY]` setter; keep_alive=-1; cold-prefill on first switch |
| nemo-stt (GPU) | LiveKit Nemotron STT plugin OR `openai.STT` repoint `[VERIFY]` | streaming partials + ~100ms finalize; `att_context_size [56,3]` |
| nemo-stt-cpu | same plugin, CPU-ONNX endpoint | ~0.67GB RAM, off-GPU; the global fallback target |
| kokoro | unchanged (`openai.TTS`) | inbound track is also the avatar's Path-A audio source |
| livekit-server | unchanged | carries the new `model.update` RPC like persona/mode |

### Internal boundaries
| Boundary | Communication | Notes |
|----------|---------------|-------|
| ModelPanel ↔ agent | `model.update` RPC (validate key) | clone of `persona.update`; ack string is the UI status |
| placement.py ↔ entrypoint | in-process pure call at session start | resolved once; no mid-session re-eval |
| Avatar ↔ inbound audio | client-side MediaStreamTrack tap (read-only) | passive observer; does not replace RoomAudioRenderer |
| Avatar ↔ barge-in | existing user-speech-start signal → streamInterrupt() | no second VAD; server barge-in unchanged |
| Avatar ↔ persona | client-side GLB lookup | MUST NOT enter the `persona.update` payload / frozen prefix |

## Anti-Patterns (v1.1-specific)

### Anti-Pattern 1: Reassigning `session.llm` on model switch
**What people do:** `session.llm = openai.LLM.with_ollama(new_tag)`.
**Why it's wrong:** orphans the `metrics_collected` subscription bound in `metrics.attach()` — the speech_id turn buffer stops getting LLM TTFT, silently breaking the flat-TTFT instrument the whole design depends on.
**Do instead:** mutate the existing instance (`update_options(model=)`), mirroring the verified `session.tts.update_options(voice=)` persona swap. Only reassign if no setter exists, and then re-run the LLM metrics subscription.

### Anti-Pattern 2: Mid-session STT GPU↔CPU thrashing
**What people do:** move STT to CPU when the user upgrades to E4B mid-session.
**Why it's wrong:** explicitly out of scope; reloading STT mid-conversation drops audio frames and spikes latency.
**Do instead:** resolve placement once at session start; use the global-CPU-ONNX fallback to make the picker VRAM-safe with no runtime switching.

### Anti-Pattern 3: Sending the avatar GLB key through `persona.update`
**What people do:** add `avatar_glb` to the persona snapshot RPC.
**Why it's wrong:** `Persona(**snapshot)` rejects extra keys (TypeError, `agent/main.py:416`) AND any server-side persona field risks perturbing the byte-stable frozen prefix / KB cache. It also violates the Part D no-server-change boundary.
**Do instead:** keep the persona→GLB map entirely client-side, keyed off the persona state the client already holds.

### Anti-Pattern 4: Leaving avatar code resident in voice-only mode
**What people do:** hide the avatar with CSS / keep the AudioWorklet running but muted.
**Why it's wrong:** residual RAF/worklet/WebGL work violates "voice-only is byte-for-byte pre-avatar with zero overhead."
**Do instead:** gate at the mount boundary with `next/dynamic ssr:false`; unmount the canvas and close the AudioWorklet when toggled to voice.

### Anti-Pattern 5: Warming both LLM tags resident under a tight GPU
**What people do:** keep Fast+Better both resident for instant switching.
**Why it's wrong:** two resident models + GPU-STT + Kokoro can blow the 16GB floor — the exact co-fit Part C must measure.
**Do instead:** keep the default (Fast) resident; load Better on first selection (keep_alive holds it after). Couple this decision to the Part C measurement.

## Sources

- Real repository code (verified): `agent/main.py`, `agent/persona.py`, `agent/metrics.py`, `agent/history.py`, `agent/interview.py`, `docker-compose.yml`, `web/app/*` (VoiceRoom, PersonaPanel, InterviewPanel, KbPanel, Transcript, AgentStatePill, api/token/route.ts), `ollama/*`, `scripts/vram-validate.sh`, `.env.example`.
- `.planning/PROJECT.md` — v1.1 milestone, Context, Constraints, Key Decisions (Parts A–D, placement coupling, avatar isolation).
- `.planning/ROADMAP.md` — flat-TTFT keystone invariant, phase structure.
- Prior v1.0 `ARCHITECTURE.md` (this file's predecessor) — streaming pipeline, persona-as-config, inline-cache-KB patterns carried forward.
- LiveKit Agents 1.x `AgentSession` / plugin `update_options` / `register_rpc_method` (`[VERIFY]` the `session.llm` model setter and Nemotron STT plugin shape against the installed packages, per the codebase's `[VM-INTROSPECT]` discipline).

---
*Architecture research for: v1.1 local-first pipeline swap (LLM selector + Nemotron STT + VRAM-aware placement) + frontend-only avatar integration*
*Researched: 2026-06-26*
