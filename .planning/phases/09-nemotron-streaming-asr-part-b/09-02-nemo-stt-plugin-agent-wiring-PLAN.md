---
plan: 09-02
title: NemoSTT streaming plugin (agent/nemo_stt.py) + main.py STT swap + whisper code removal (warmup.py, vram-validate.sh, README) + STTMetrics emission + 09-STT-VERIFY runbook
phase: 9
wave: 2
depends_on: [09-01]
autonomous: false
requirements: [STT-01, STT-02, STT-03, STT-04]
files_modified:
  - agent/nemo_stt.py
  - agent/main.py
  - agent/requirements.txt
  - ollama/warmup.py
  - scripts/vram-validate.sh
  - README.md
  - .planning/phases/09-nemotron-streaming-asr-part-b/09-STT-VERIFY.md
---

# Plan 09-02: The agent leg — a real streaming NemoSTT plugin that talks the Wave-1 WS contract, swaps into build_session, emits its own STTMetrics so stt_ms isn't NULL, and finishes removing faster-whisper

## User Story

**As** a learner speaking to the agent, **I want** the agent's STT plugin to stream my audio to the
`nemo-stt` service and surface a growing interim transcript that finalizes within ~100 ms of
end-of-speech (interim distinct from final in the existing panel), with native punctuation/
capitalization, **so that** I see live, clean, cased text and the agent responds at conversational
latency — with faster-whisper fully gone from the agent code and stack.

## Context

This is the **agent half** of the swap. It writes `agent/nemo_stt.py` (`NemoSTT` +
`NemoSpeechStream`, a true `livekit.agents.stt.STT` streaming subclass over the Wave-1 websocket),
swaps it into `build_session()` replacing `openai.STT(...)`, retires the `WHISPER_*` config block,
removes the remaining faster-whisper references (warmup, vram-validate, README), and authors the
`09-STT-VERIFY.md` operator GPU-gate runbook. Depends on **09-01** (Wave 1) because the plugin's WS
client speaks the contract frozen there (`config`/binary-PCM/`flush` → `ready`/`delta`/`final`).

**The plugin contract is VERIFIED against `livekit-agents@1.6.4` `stt/stt.py` (RESEARCH §3).**
`NemoSTT(stt.STT)` constructs with `STTCapabilities(streaming=True, interim_results=True)`,
implements `stream(...) -> NemoSpeechStream` (a `stt.RecognizeStream` subclass), and stubs
`_recognize_impl` to raise `NotImplementedError` (streaming-only). `NemoSpeechStream.__init__` calls
`super().__init__(stt=..., conn_options=..., sample_rate=16000)` — passing `sample_rate=16000` makes
`push_frame` AUTO-RESAMPLE LiveKit's 48 kHz frames to 16 kHz mono for us (RESEARCH §3, ln ~473-480
build an `rtc.AudioResampler`). `_run` reads `self._input_ch` (AudioFrame or `_FlushSentinel`),
forwards int16 PCM bytes over the WS, and on a flush sentinel sends `{"type":"flush"}`. A `_recv_loop`
maps server `delta` → `INTERIM_TRANSCRIPT` (growing) and `final` → `FINAL_TRANSCRIPT`
(`stt.SpeechEvent` with `stt.SpeechData(language="en", text=...)`).

**Endpoint authority is UNCHANGED (RESEARCH §4, CONTEXT lock).** Silero VAD + local
`MultilingualModel` turn detector REMAIN the sole endpoint authority — satisfied by the existing
AgentSession contract with NO new code. The session streams frames into `push_frame` continuously
(growing interim) and, when the TURN DETECTOR decides end-of-utterance, calls `end_input()`/`flush()`
on the STT stream → `_run` forwards `{"type":"flush"}` → server drains and replies `{"type":"final"}`
→ we emit `FINAL_TRANSCRIPT` (~100 ms finalize, STT-02). The `turn_handling` dict in `build_session`
stays exactly as-is — NeMo does NOT own turn-taking.

**THE non-obvious gotcha — STTMetrics or `stt_ms` is NULL forever (RESEARCH §5, PATTERNS §1 Analog
C — MUST get right).** `agent/metrics.py` is **READ-ONLY** this phase; `_on_stt_metrics` (:258-265)
reads `STTMetrics.duration`. The STREAMING path does NOT auto-emit a timed `STTMetrics` (only the
non-streaming `recognize()` does; the base monitor hardcodes `duration=0.0` for `streamed=True`).
`openai.STT` worked because it is non-streaming. So `NemoSpeechStream` MUST EXPLICITLY emit a
`STTMetrics` with a REAL measured `duration` on each FINAL via `self._stt.emit("metrics_collected",
STTMetrics(...))`. `STTMetrics` required fields (verified `metrics/base.py`): `label`, `request_id`,
`timestamp`, `duration`, `audio_duration`, `streamed`. `session.stt` IS the `NemoSTT` instance, so
the existing `plugin.on("metrics_collected", _on_stt_metrics)` binds unchanged — no metrics.py edit.

**`duration` semantics — PICK ONE and pin it in the runbook (RESEARCH §5, Risk §3).** This plan
defines `stt_ms` = **finalize latency** (flush→final wall-clock seconds), matching the ~100 ms
target and the per-stage `stt` budget (`BUDGET_MS["stt"]=150`, metrics.py:34). Measure from the
flush-sentinel send to the `final` receipt. Document this definition explicitly in `09-STT-VERIFY.md`
so the P50 gate is unambiguous.

**Whisper removal (RESEARCH §7, PATTERNS §1/§7/§9).** Delete the `WHISPER_*` block in main.py
(:51-73), update the module docstring (:4), swap the `stt=openai.STT(...)` construction (:210-215) →
`stt=NemoSTT(ws_url=NEMO_STT_URL, language="en")` with `NEMO_STT_URL` env (default
`ws://nemo-stt:8000/v1/audio/stream`) + `from nemo_stt import NemoSTT`. Add `aiohttp` to
agent/requirements.txt (WS client). Remove `warm_whisper` + `WHISPER_*` from `ollama/warmup.py`
(STT warmup is now "model resident at container start"). Rename whisper→nemo-stt in
`scripts/vram-validate.sh` (still 3 GPU procs — `EXPECTED_GPU_PROCS` UNCHANGED). Update the README STT
section. `livekit-plugins-openai` STAYS (LLM+TTS still use it).

**Transcript UI is NO functional change (CONTEXT, PATTERNS §10).** `web/app/Transcript.tsx` consumes
LiveKit native transcription via `useTranscriptions()` — interim+final arrive automatically once
`NemoSTT` emits proper `INTERIM_TRANSCRIPT`/`FINAL_TRANSCRIPT`. The CONTEXT dimmed/italic interim
styling is OPTIONAL and explicitly out of this plan's required scope (zero functional change) — do
NOT touch web/ unless the operator later requests styling.

**Sandbox vs operator split (RESEARCH §8).** Sandbox-verifiable: `py_compile agent/nemo_stt.py` +
`agent/main.py`; instantiate `NemoSTT` and assert `capabilities.streaming`/`interim_results`; a
fake-WS-server unit test of the `delta`→INTERIM / `final`→FINAL+STTMetrics framing (pip
`livekit-agents` installs in the sandbox, no GPU needed); `metrics.py` `stt_ms` populates from a
synthetic `STTMetrics`. Operator GPU gates: the real voice-to-voice P50<1.0s with the new STT leg +
~100 ms finalize, the `conformer_stream_step` confirmation, Blackwell torch — all authored in
`09-STT-VERIFY.md`. Marked `autonomous: false`.

**Scope discipline (YAGNI).** Do NOT edit `agent/metrics.py` (READ-ONLY — feed it, don't change it).
Do NOT change the VAD/turn-detector/`turn_handling` config. Do NOT implement cyber-vocab fine-tune
(hook only). Do NOT add interim styling to web/. Do NOT add a CPU-ONNX path (Phase 10). Keep each
method ≤40 lines / ≤3 nesting via the `_run`/`_recv_loop`/`_emit_final` split (AGENTS.md).

## Tasks

<task id="09-02-1">
  <title>Create agent/nemo_stt.py — NemoSTT + NemoSpeechStream streaming plugin over the Wave-1 WS contract; emit INTERIM/FINAL + an explicit STTMetrics with measured finalize duration</title>
  <read_first>
    - .planning/phases/09-nemotron-streaming-asr-part-b/09-RESEARCH.md (§3 verified STT/RecognizeStream/SpeechEvent/SpeechData contract + the skeleton; §5 the STTMetrics gotcha + required fields + _emit_final; §4 endpoint-authority-unchanged)
    - .planning/phases/09-nemotron-streaming-asr-part-b/09-PATTERNS.md (§1 Analog A wiring site, Analog C metrics contract metrics.py:258-265 + attach :327-335, Analog D keep-methods-small)
    - .planning/phases/09-nemotron-streaming-asr-part-b/09-01-nemo-stt-server-compose-PLAN.md (the FROZEN WS contract: config/flush/reset → ready/delta/final/error; binary int16 PCM)
    - agent/metrics.py (_on_stt_metrics :258-265 reads STTMetrics.duration; attach :318-337 binds session.stt — what the plugin MUST feed; READ-ONLY)
    - agent/main.py (build_session stt=openai.STT :208-215 — the construction this plugin replaces; _warmup_llm_ttft_ms :172-201 — the small-method house style)
  </read_first>
  <action>
    Create `agent/nemo_stt.py` with two classes, structure adapted from RESEARCH §3/§5 (keep heavy
    work in the small `_run`/`_recv_loop`/`_emit_final` split):
    - **`class NemoSTT(stt.STT)`:** `__init__(self, *, ws_url: str, language: str = "en")` calling
      `super().__init__(capabilities=stt.STTCapabilities(streaming=True, interim_results=True))`;
      store `ws_url`/`language`. `model`/`provider` read-only properties (e.g.
      `"nemotron-speech-streaming-en-0.6b"` / `"nemo"`) for the metrics `label`. `async
      _recognize_impl(self, *a, **k)` → `raise NotImplementedError("NemoSTT is streaming-only")`.
      `stream(self, *, language=None, conn_options=...) -> NemoSpeechStream` returns a new
      `NemoSpeechStream(stt=self, ws_url=self._ws_url, language=self._language,
      conn_options=conn_options)`.
    - **`class NemoSpeechStream(stt.RecognizeStream)`:** `__init__` calls `super().__init__(stt=stt,
      conn_options=conn_options, sample_rate=16000)` — the 16000 makes push_frame auto-resample the
      48 kHz mono input (RESEARCH §3). Store `ws_url`/`language` and the parent `stt` ref for the
      metrics emit.
    - **`async _run(self)`:** open an `aiohttp.ClientSession().ws_connect(self._ws_url)`; send
      `{"type":"config","language":self._language}`; spawn `recv = asyncio.create_task(
      self._recv_loop(ws))`; then `async for data in self._input_ch:` — if `isinstance(data,
      self._FlushSentinel)`: record `self._flush_started = time.perf_counter()` (the finalize-latency
      start) and `await ws.send_json({"type":"flush"})` then `continue`; else
      `await ws.send_bytes(data.data.tobytes())` (int16 PCM, already 16k mono). `await recv` at end.
      Early-continue on the sentinel keeps nesting ≤3.
    - **`async _recv_loop(self, ws)`:** `async for msg in ws:` parse JSON; on `delta` push
      `stt.SpeechEvent(type=stt.SpeechEventType.INTERIM_TRANSCRIPT, alternatives=[stt.SpeechData(
      language=self._language, text=evt["text"])])` to `self._event_ch.send_nowait(...)` (growing,
      native PnC as-is); on `final` call `self._emit_final(evt["text"])`; on `error` log it.
    - **`_emit_final(self, text)`:** compute `dur = time.perf_counter() - self._flush_started`
      (finalize latency seconds; guard if no flush recorded → 0.0). Emit the FINAL SpeechEvent
      (`FINAL_TRANSCRIPT`, SpeechData with the cased text) to `self._event_ch`, THEN emit the metrics:
      `self._stt.emit("metrics_collected", STTMetrics(request_id="", timestamp=time.time(),
      duration=dur, label=self._stt.label, audio_duration=0.0, streamed=True))`. Use the EXACT
      `STTMetrics` field set verified in RESEARCH §5 (label, request_id, timestamp, duration,
      audio_duration, streamed). Add a comment that WITHOUT this explicit emit, `stt_ms` stays NULL
      forever (the streaming path emits no timed STTMetrics) — this is the load-bearing line for the
      latency gate (metrics.py:258-265 reads `.duration`).
    Imports: `from livekit.agents import stt, APIConnectOptions` (+ utils as needed), `from
    livekit.agents.metrics import STTMetrics`, `from livekit import rtc`, `aiohttp, asyncio, json,
    time`. NO language/prompt steering (English-only). Do NOT emit FINAL on any client-side heuristic
    — only on the server `final` (which only comes from the flush the turn detector triggers).
  </action>
  <acceptance_criteria>
    - `python3 -m py_compile agent/nemo_stt.py` exits 0
    - `NemoSTT` subclasses `stt.STT` with `STTCapabilities(streaming=True, interim_results=True)` (`grep -n "class NemoSTT(stt.STT)\|streaming=True\|interim_results=True" agent/nemo_stt.py`)
    - `_recognize_impl` raises NotImplementedError and `stream()` returns a NemoSpeechStream (`grep -n "NotImplementedError\|def stream\|NemoSpeechStream" agent/nemo_stt.py`)
    - `NemoSpeechStream` passes `sample_rate=16000` to super().__init__ (auto-resample) (`grep -n "sample_rate=16000" agent/nemo_stt.py`)
    - `_run` forwards int16 PCM bytes + sends `{"type":"flush"}` on the FlushSentinel; `_recv_loop` maps delta→INTERIM and final→FINAL (`grep -nE "send_bytes|\"flush\"|FlushSentinel|INTERIM_TRANSCRIPT|FINAL_TRANSCRIPT" agent/nemo_stt.py`)
    - `_emit_final` emits an explicit STTMetrics with a measured `duration` and the verified field set (`grep -n "metrics_collected\|STTMetrics\|duration=\|audio_duration=\|streamed=True" agent/nemo_stt.py`)
    - INTERIM/FINAL text is passed through with native PnC (no lowercase/strip) (`grep -ni "\.lower()\|\.strip()\|capitalize\|punctuation" agent/nemo_stt.py` returns nothing meaningful)
    - SANDBOX-TEST: instantiating `NemoSTT(ws_url="ws://x", language="en")` exposes `capabilities.streaming` and `capabilities.interim_results` True (a fake-WS unit test of delta→INTERIM / final→FINAL+STTMetrics framing passes — pip livekit-agents, no GPU)
    - OPERATOR-VERIFICATION (GPU, deferred — 09-STT-VERIFY): live audio streams growing interims, the turn-detector flush yields a FINAL within ~100 ms, and `stt_ms` is NON-NULL in the agent metrics line
  </acceptance_criteria>
</task>

<task id="09-02-2">
  <title>Swap agent/main.py: replace WHISPER_* config + openai.STT with NemoSTT(ws_url=NEMO_STT_URL); add aiohttp to agent/requirements.txt</title>
  <read_first>
    - .planning/phases/09-nemotron-streaming-asr-part-b/09-RESEARCH.md (§7 MODIFY agent/main.py exact line targets; §3 the NemoSTT wiring lines)
    - .planning/phases/09-nemotron-streaming-asr-part-b/09-PATTERNS.md (§1 Analog A :210-215 swap, Analog B import + NEMO_STT_URL env :26,49-52; §6 add aiohttp to requirements)
    - agent/main.py (module docstring :1-14; OLLAMA/WHISPER/KOKORO base-url consts :49-52; WHISPER_MODEL :54-58; WHISPER_PARAMS :66-73; build_session stt=openai.STT :208-215; the `from livekit.plugins import openai, silero` import :26)
    - agent/requirements.txt (the httpx host-client dep note :16-17 — mirror for aiohttp)
  </read_first>
  <action>
    Wire NemoSTT into the agent and retire the whisper config:
    - **Import:** add `from nemo_stt import NemoSTT` to the local-module import block (beside
      `import history` / `import metrics`).
    - **Env const:** add `NEMO_STT_URL = os.environ.get("NEMO_STT_URL",
      "ws://nemo-stt:8000/v1/audio/stream")` beside the other `*_BASE_URL` consts (:49-52). Note in a
      comment it is a `ws://` URL (not `http://.../v1`) and matches the Wave-1 server route.
    - **DELETE** `WHISPER_BASE_URL` (:51), `WHISPER_MODEL` + its single-source comment (:54-58), and
      `WHISPER_PARAMS` (:66-73). Leave `OLLAMA_*` and `KOKORO_*` untouched.
    - **build_session:** replace the `stt=openai.STT(base_url=WHISPER_BASE_URL, model=WHISPER_MODEL,
      api_key="none", language=WHISPER_PARAMS["language"])` block (:210-215) with
      `stt=NemoSTT(ws_url=NEMO_STT_URL, language="en")`. The `vad=`, `llm=`, `tts=`, and `turn_handling`
      args stay EXACTLY as-is (endpoint authority unchanged — RESEARCH §4).
    - **Docstring:** update the module docstring (:4) "faster-whisper STT" → "Nemotron streaming STT"
      (and any other whisper mention in :1-14).
    - **Keep** `from livekit.plugins import openai, silero` — `openai` is still used by `llm=`/`tts=`.
    - **agent/requirements.txt:** add `aiohttp` (the WS client for `NemoSpeechStream._run`) with a
      one-line rationale comment mirroring the httpx note (:16-17). Keep
      `livekit-plugins-openai==1.6.4` (LLM+TTS). Use the explicit-pin posture.
    Do NOT touch the persona/KB/mode/model RPC handlers, HistoryWindowAgent, metrics.attach, or the
    VAD/turn_handling config. `py_compile` is the sandbox gate (cannot import livekit).
  </action>
  <acceptance_criteria>
    - `python3 -m py_compile agent/main.py` exits 0
    - `from nemo_stt import NemoSTT` is imported and `NEMO_STT_URL` defaults to the ws:// nemo-stt route (`grep -n "from nemo_stt import NemoSTT\|NEMO_STT_URL = os.environ.get" agent/main.py`)
    - build_session constructs `stt=NemoSTT(ws_url=NEMO_STT_URL, language=\"en\")` and no longer constructs openai.STT (`grep -n "stt=NemoSTT(ws_url=NEMO_STT_URL" agent/main.py`; `grep -n "openai.STT" agent/main.py` returns nothing)
    - All WHISPER_* consts are gone (`grep -n "WHISPER_BASE_URL\|WHISPER_MODEL\|WHISPER_PARAMS" agent/main.py` returns nothing)
    - The module docstring no longer says faster-whisper (`grep -ni "faster-whisper\|whisper" agent/main.py` returns nothing)
    - `openai` import retained for llm/tts (`grep -n "from livekit.plugins import openai, silero" agent/main.py`)
    - `agent/requirements.txt` adds aiohttp and keeps livekit-plugins-openai==1.6.4 (`grep -n "aiohttp\|livekit-plugins-openai==1.6.4" agent/requirements.txt`)
    - The VAD/turn_handling block is unchanged (`grep -n "turn_handling\|MultilingualModel" agent/main.py` still present; no edits inside it)
    - OPERATOR-VERIFICATION (GPU, deferred — 09-STT-VERIFY): after `docker compose build agent && up -d`, a live turn transcribes via nemo-stt and the agent responds; `stt_ms` is non-null
  </acceptance_criteria>
</task>

<task id="09-02-3">
  <title>Finish whisper removal: drop warm_whisper + WHISPER_* from ollama/warmup.py; rename whisper→nemo-stt in scripts/vram-validate.sh (EXPECTED_GPU_PROCS unchanged); update README STT section</title>
  <read_first>
    - .planning/phases/09-nemotron-streaming-asr-part-b/09-RESEARCH.md (§7 MODIFY warmup.py / vram-validate.sh / README exact targets)
    - .planning/phases/09-nemotron-streaming-asr-part-b/09-PATTERNS.md (§7 warm_whisper :118-127 + main() warm-loop :142-145 + consts :45,47; §9 vram-validate WHISPER_BASE_URL :43 + assert :158-164, EXPECTED_GPU_PROCS=3 unchanged)
    - ollama/warmup.py (WHISPER_BASE_URL/WHISPER_MODEL :45,47; _sine_wav_bytes :64-76; warm_whisper :118-127; main() warm-loop :140-146; module docstring :7-9)
    - scripts/vram-validate.sh (header comments :8,13; WHISPER_BASE_URL :43; assert_three_gpu_procs message :158-164; EXPECTED_GPU_PROCS :45)
    - README.md (STT section ~:35 — "ollama, whisper, kokoro need the GPU")
  </read_first>
  <action>
    Remove the remaining faster-whisper references across the host scripts + docs:
    - **ollama/warmup.py:** DELETE `warm_whisper` (:118-127) and remove it from the `main()` warm-loop
      tuple (:142-145, leave `warm_llm` + `warm_kokoro`). DELETE the `WHISPER_BASE_URL` (:45) +
      `WHISPER_MODEL` (:47) consts. Update the module docstring (:7-9) to drop the `{"model":
      "whisper", ...}` line. Decide on `_sine_wav_bytes` (:64-76): it is only used by warm_whisper, so
      either DELETE it too (cleanest — STT warmup is now "model resident at container start", RESEARCH
      §7) OR keep it ONLY if you also add a tiny WS warmup ping (NOT required — prefer deletion to
      avoid dead code, YAGNI). Pick deletion unless adding the optional WS ping. `warm_llm`/
      `warm_kokoro`/`resolved_llm_tag` stay intact.
    - **scripts/vram-validate.sh:** rename whisper→nemo-stt in the header comments (:8,13) and the
      `assert_three_gpu_procs` messages (:162-163); replace the `WHISPER_BASE_URL` const (:43) with a
      `NEMO_STT` equivalent (it points at port 8000 — keep the port, rename the var + the service name
      in the assert text to "ollama, nemo-stt, kokoro"). Leave `EXPECTED_GPU_PROCS=3` (:45) UNCHANGED
      — still 3 GPU procs (ollama, nemo-stt, kokoro). `bash -n` must pass.
    - **README.md:** update the STT section (~:35) — faster-whisper → Nemotron streaming
      (`nvidia/nemotron-speech-streaming-en-0.6b`), the service name (`nemo-stt`) + port (8000), and a
      one-line build-time model-bake note (offline-capable). Keep "ollama, nemo-stt, kokoro need the
      GPU".
    Do NOT change warm_llm/warm_kokoro behavior. Do NOT change EXPECTED_GPU_PROCS.
  </action>
  <acceptance_criteria>
    - `python3 -m py_compile ollama/warmup.py` exits 0 and no whisper refs remain (`grep -ni "whisper" ollama/warmup.py` returns nothing)
    - `warm_whisper` is gone and the main() warm-loop runs only warm_llm + warm_kokoro (`grep -n "warm_whisper" ollama/warmup.py` returns nothing)
    - `bash -n scripts/vram-validate.sh` exits 0; no whisper refs remain and EXPECTED_GPU_PROCS is still 3 (`grep -ni "whisper" scripts/vram-validate.sh` returns nothing; `grep -n "EXPECTED_GPU_PROCS=3" scripts/vram-validate.sh`)
    - The vram-validate assert names the 3 procs as ollama, nemo-stt, kokoro (`grep -n "nemo-stt" scripts/vram-validate.sh`)
    - README STT section names Nemotron streaming + nemo-stt + port 8000, no faster-whisper (`grep -ni "nemotron\|nemo-stt" README.md`; `grep -ni "faster-whisper\|whisper" README.md` returns nothing)
  </acceptance_criteria>
</task>

<task id="09-02-4">
  <title>Author 09-STT-VERIFY.md — operator GPU-gate runbook: voice-to-voice P50<1.0s with new STT leg + ~100ms finalize, stt_ms=finalize-latency semantics pinned, conformer_stream_step + Blackwell torch gates, cyber-vocab HOOK note</title>
  <read_first>
    - .planning/phases/09-nemotron-streaming-asr-part-b/09-RESEARCH.md (§8 sandbox-vs-operator table; §9 risks 1-6; §5 duration-semantics decision; §10 cyber-vocab hook)
    - .planning/phases/09-nemotron-streaming-asr-part-b/09-CONTEXT.md (§decisions Latency operator gate; §specifics ~100ms finalize, no audio leaves LAN)
    - .planning/phases/08-llm-speed-selector-part-a/08-LLM-VERIFY.md (the operator-runbook format: frontmatter status pending-operator, harness_note, frozen-contract notes, per-gate result tables, NONE marked passed)
    - agent/metrics.py (BUDGET_MS stt=150 / e2e=1200 :32-39 — the budgets the runbook references)
  </read_first>
  <action>
    Create `.planning/phases/09-nemotron-streaming-asr-part-b/09-STT-VERIFY.md` mirroring
    08-LLM-VERIFY's format (frontmatter `status: pending-operator`, `phase`, `plan: 09-02`,
    `requirement_ids: [STT-01, STT-02, STT-03, STT-04]`, a `harness_note` that the sandbox has no
    GPU/Docker/NeMo so every gate is deferred and NONE are marked passed by the executor). Include:
    - **Frozen-contract notes:** endpoint authority unchanged (Silero VAD + MultilingualModel own
      finalize); the server never auto-finalizes (stall watchdog recycles, no premature FINAL);
      native PnC surfaced as-is; metrics.py READ-ONLY; the `STT_MODEL`/`STT_ATT_CONTEXT_SIZE`
      single-source (no hardcoded tag).
    - **PIN the `stt_ms` semantics (RESEARCH §5):** `stt_ms` = FINALIZE LATENCY (flush→final
      seconds), measured in `NemoSpeechStream._emit_final`, compared against `BUDGET_MS["stt"]=150`.
      State this explicitly so the P50 gate is unambiguous.
    - **BUILD-FIRST step:** `docker compose build nemo-stt agent && docker compose up -d && docker
      compose ps` (nemo-stt healthy, agent started after) before any live gate.
    - **Gates (each with a result table, unsigned):**
      - **Gate 1 — conformer_stream_step signature (RESEARCH §1 ⚠️, Risk 1):** in-container, confirm
        the `conformer_stream_step` call matches `nemo.collections.asr` source for the pinned NeMo
        version; the server decodes a real clip.
      - **Gate 2 — Blackwell sm_120 torch (RESEARCH Risk 2):** the image runs sm_120 kernels on the
        RTX 5090 (no "no kernel image is available" crash) — the Kokoro-class gate.
      - **Gate 3 — interim+final stream (STT-02/03):** speaking yields a GROWING interim transcript
        in the panel, native PnC/casing surfaced as-is, the turn-detector flush finalizes within
        ~100 ms, final replaces interim in place; `stt_ms` is NON-NULL (the §5 gotcha is closed).
      - **Gate 4 — voice-to-voice P50<1.0s (PERF-04, the headline):** measure rolling e2e P50 with the
        new STT leg; the STT finalize leg tightens toward sub-100 ms; `e2e` under `BUDGET_MS["e2e"]`.
      - **Gate 5 — RNNT stall watchdog (STT-02 run-on):** an interview-mode pause-heavy run-on answer
        is NOT stranded — the server recycles decoder state and continues, no premature FINAL (check
        agent + server logs).
      - **Gate 6 — VRAM co-residency re-check (RESEARCH Risk 4):** `scripts/vram-validate.sh` — 3 GPU
        procs (ollama, nemo-stt, kokoro), peak under the 16 GB floor with the +2.4 GB model.
    - **Cyber-vocab fine-tune HOOK note (STT-04 / RESEARCH §10):** document the seam — point
      `STT_MODEL` at a future fine-tuned `.nemo` and rebuild, ZERO code change; NOT implemented now.
    Leave every gate result table UNSIGNED/PENDING. Do NOT mark anything passed.
  </action>
  <acceptance_criteria>
    - `09-STT-VERIFY.md` exists with `status: pending-operator` frontmatter and `requirement_ids: [STT-01, STT-02, STT-03, STT-04]` (`grep -n "status: pending-operator\|STT-01, STT-02, STT-03, STT-04" 09-STT-VERIFY.md`)
    - It PINS `stt_ms` = finalize latency (flush→final) explicitly (`grep -ni "finalize latency\|flush.*final" .../09-STT-VERIFY.md`)
    - Gates cover conformer_stream_step signature, Blackwell sm_120, interim+final+~100ms finalize, voice-to-voice P50<1.0s, RNNT stall watchdog, and VRAM co-residency (`grep -niE "conformer_stream_step|sm_120|blackwell|interim|finalize|P50|stall|vram" .../09-STT-VERIFY.md`)
    - A cyber-vocab fine-tune HOOK note is present and marked NOT implemented (`grep -ni "fine-tune\|hook\|STT_MODEL" .../09-STT-VERIFY.md`)
    - No gate is marked passed/signed (`grep -ni "PASS\b" .../09-STT-VERIFY.md` shows only unfilled result-table placeholders, none asserted by the executor)
  </acceptance_criteria>
</task>

## Verification

- `python3 -m py_compile agent/nemo_stt.py agent/main.py ollama/warmup.py` exits 0; `bash -n
  scripts/vram-validate.sh` exits 0.
- `agent/nemo_stt.py`: `NemoSTT(stt.STT)` with `STTCapabilities(streaming=True,
  interim_results=True)`, `_recognize_impl` raises, `stream()` returns `NemoSpeechStream` (passing
  `sample_rate=16000`); `_run` forwards int16 PCM + flush, `_recv_loop` maps delta→INTERIM /
  final→FINAL, and `_emit_final` emits an explicit `STTMetrics` with a MEASURED finalize `duration`
  (the load-bearing line so `stt_ms` is not NULL). Native PnC passed through (no lowercase/strip).
- `agent/main.py`: imports `NemoSTT`, defines `NEMO_STT_URL`, constructs `stt=NemoSTT(...)`, all
  `WHISPER_*` removed, docstring updated, `turn_handling`/VAD/turn-detector UNCHANGED; openai import
  retained for llm/tts. `agent/requirements.txt` adds aiohttp, keeps livekit-plugins-openai==1.6.4.
- Whisper fully gone: no `whisper` refs in `ollama/warmup.py`, `scripts/vram-validate.sh`, or
  `README.md`; `EXPECTED_GPU_PROCS=3` unchanged (now ollama/nemo-stt/kokoro).
- SANDBOX-TEST (pip livekit-agents, no GPU): instantiate `NemoSTT`; assert `capabilities.streaming` /
  `capabilities.interim_results`; a fake-WS unit test drives `delta`→INTERIM and `final`→FINAL +
  asserts a `metrics_collected` STTMetrics with non-null `duration`; feeding that synthetic STTMetrics
  through `metrics._on_stt_metrics` populates `stt_ms`.
- `metrics.py` is UNCHANGED (READ-ONLY) — verify `git diff agent/metrics.py` is empty.
- BUILD-FIRST (operator, baked-image invariant): `docker compose build nemo-stt agent && docker
  compose up -d && docker compose ps` (nemo-stt healthy, agent up).
- OPERATOR GATE (GPU — deferred; authored in `09-STT-VERIFY.md`): conformer_stream_step signature
  confirmation; Blackwell sm_120 execution; live growing-interim + ~100 ms finalize with native PnC;
  `stt_ms` non-null; voice-to-voice P50<1.0s; RNNT stall watchdog no-premature-FINAL; VRAM
  co-residency (3 procs, under 16 GB).
- DEFER (do NOT mark passed in this plan): all GPU/Docker operator items; the sandbox has no
  GPU/Docker daemon and cannot import NeMo/torch.

## must_haves

truths:
- STT-01: the agent's STT plugin is a custom streaming `NemoSTT` (`livekit.agents.stt.STT` subclass,
  NOT an openai.STT shim) that streams audio to the `nemo-stt` service over the Wave-1 websocket;
  faster-whisper is fully removed from the agent code + host scripts + README.
- STT-02: a GROWING interim transcript streams while the user speaks (`INTERIM_TRANSCRIPT` re-emitted
  with the cumulative text), and FINAL fires within ~100 ms of end-of-speech — triggered by the
  turn-detector flush, the server drains and replies `final`, the plugin emits `FINAL_TRANSCRIPT`;
  the Silero VAD + MultilingualModel turn detector remain the SOLE endpoint authority (turn_handling
  unchanged).
- STT-03: native punctuation + capitalization are surfaced AS-IS to both the transcript (native
  LiveKit transcription, zero client post-processing) and the LLM (the FINAL text feeds the turn).
- STT-04: `att_context_size` remains the config knob (consumed server-side from `STT_ATT_CONTEXT_SIZE`
  default `[56,3]`); the cyber-vocab fine-tune is a documented HOOK only.
- `stt_ms` is NON-NULL: `NemoSpeechStream._emit_final` EXPLICITLY emits a `STTMetrics` with a measured
  finalize `duration` (flush→final), so `metrics._on_stt_metrics` (READ-ONLY) populates `stt_ms` —
  without it the streaming path leaves `stt_ms` NULL forever (the RESEARCH §5 gotcha).
- The transcript UI needs NO functional change — `useTranscriptions()` consumes the native
  interim+final stream automatically; dimmed-interim styling is optional and out of this plan's scope.

must_haves.prohibitions:
- NO edit to `agent/metrics.py` (READ-ONLY — the plugin FEEDS it via the metrics_collected emit; the
  per-turn JSON shape is frozen).
- NO change to the VAD / `MultilingualModel` turn detector / `turn_handling` endpointing config — the
  turn detector stays the sole endpoint authority (NeMo does NOT own turn-taking).
- NO client-side STT FINAL heuristic — FINAL only on the server `final` (which only comes from the
  turn-detector flush); NO mid-utterance finalize in the plugin.
- NO client-side PnC post-processing (no lowercase/strip/recapitalize) — native cased text passed
  through.
- NO hardcoded STT model tag in agent code; NO removal of `livekit-plugins-openai` (LLM+TTS need it).
- NO functional change / interim styling in `web/` (out of scope — native transcription already works).
- NO cyber-vocab fine-tune implementation (hook/note only); NO CPU-ONNX path (Phase 10).
- NO marking any GPU/Docker OPERATOR-VERIFICATION step passed in this plan.

## Artifacts this plan produces

- `agent/nemo_stt.py` (new): `class NemoSTT(stt.STT)` (capabilities streaming+interim, `model`/
  `provider` properties, `_recognize_impl` stub, `stream()`), `class NemoSpeechStream(
  stt.RecognizeStream)` (`_run`, `_recv_loop`, `_emit_final` — the explicit STTMetrics emit with
  measured finalize `duration`).
- `agent/main.py` (modified): `from nemo_stt import NemoSTT`; `NEMO_STT_URL` env const (default
  `ws://nemo-stt:8000/v1/audio/stream`); `stt=NemoSTT(ws_url=NEMO_STT_URL, language="en")` in
  build_session; all `WHISPER_*` consts + the openai.STT construction removed; docstring updated.
- `agent/requirements.txt` (modified): `aiohttp` added (WS client); `livekit-plugins-openai==1.6.4`
  retained.
- `ollama/warmup.py` (modified): `warm_whisper` + `WHISPER_*` consts (+ `_sine_wav_bytes` if unused)
  removed; warm-loop is warm_llm + warm_kokoro.
- `scripts/vram-validate.sh` (modified): whisper→nemo-stt renames; `EXPECTED_GPU_PROCS=3` unchanged.
- `README.md` (modified): STT section → Nemotron streaming / `nemo-stt` / port 8000 / build-time bake.
- `.planning/phases/09-nemotron-streaming-asr-part-b/09-STT-VERIFY.md` (new): operator GPU-gate
  runbook (status pending-operator) — `stt_ms`=finalize-latency pinned; gates for
  conformer_stream_step signature, Blackwell sm_120, interim+final+~100ms finalize, voice-to-voice
  P50<1.0s, RNNT stall watchdog, VRAM co-residency; cyber-vocab fine-tune HOOK note. Unsigned.
- Env var introduced: `NEMO_STT_URL` (agent-side, code default). Classes introduced: `NemoSTT`,
  `NemoSpeechStream`.
</content>
