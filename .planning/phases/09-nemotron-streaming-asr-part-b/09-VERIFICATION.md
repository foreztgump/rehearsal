# Phase 09 — Nemotron Streaming ASR (Part B): VERIFICATION

**Method:** goal-backward analysis — start from the phase goal + STT-01..04, walk back to the
code that delivers each, and confirm the operator-gated runtime acceptance is correctly deferred
(not falsely marked passed).

**Verified against:** commits `7efb550..3a6d849` (16 commits). Sandbox has NO GPU, NO Docker
daemon, and CANNOT import NeMo/torch — so all runtime/behavioral acceptance is legitimately
operator-gated to `09-STT-VERIFY.md` (the established Phase-8 pattern). This document verifies the
CODE delivers the phase promise and the deferral is structurally sound.

**Phase goal:** Replace faster-whisper with `nvidia/nemotron-speech-streaming-en-0.6b` served via
NeMo behind a local server, wired into the LiveKit agent as the STT plugin — growing interim while
speaking, ~100ms finalize after end-of-speech, native PnC surfaced as-is, an `att_context_size`
knob — without regressing voice-to-voice P50 < 1.0s.

---

## Sandbox checks performed (all green)

| Check | Result |
|-------|--------|
| `py_compile` stt/server.py, agent/nemo_stt.py, agent/main.py, ollama/warmup.py | PASS |
| `bash -n scripts/vram-validate.sh` | PASS |
| `agent/metrics.py` absent from `git diff 7efb550..3a6d849` | PASS (READ-ONLY upheld) |
| No `nvidia/nemotron`/`nemotron-speech-streaming` literal in stt/server.py or agent/*.py | PASS |
| `whisper:` service removed from docker-compose.yml | PASS |
| No `whisper`/`WHISPER_*` functional refs in warmup.py / README / scripts | PASS (only analogy comments remain) |
| `EXPECTED_GPU_PROCS=3` (ollama, nemo-stt, kokoro) in vram-validate.sh | PASS |
| Dockerfile + compose healthchecks identical python-urllib probe (no curl) | PASS |
| agent `depends_on: nemo-stt: { condition: service_healthy }` | PASS |

---

## Per-requirement assessment

### STT-01 — faster-whisper replaced by Nemotron served via NeMo, wired as STT plugin
**Assessment: satisfied-in-code (runtime model-load operator-gated).**

- `stt/server.py` — FastAPI websocket server; `lifespan` loads `STT_MODEL` resident via
  `asyncio.to_thread(load_model)` and never offloads (keep-resident-forever, mirrors
  `WHISPER__TTL=-1`); `/health` returns 503-until-`_ready`, 200 after. Heavy imports (nemo/torch/
  numpy) are function-local so the module byte-compiles GPU-less. (server.py:49-52, 101-117,
  223-242)
- `docker-compose.yml` — `whisper:` service **deleted**; `nemo-stt` added (build `./stt`,
  `STT_MODEL` build-arg + env, LAN-bound `${LAN_BIND_IP:-127.0.0.1}:8000`, GPU `count: all`
  reservation, python-urllib healthcheck, `restart: unless-stopped`); no `env_file` (no LiveKit
  secret on the STT server). Agent `depends_on` gated on `nemo-stt: service_healthy`.
- `agent/nemo_stt.py` — `NemoSTT(stt.STT)` + `NemoSpeechStream(stt.RecognizeStream)`, a TRUE
  streaming plugin (not an `openai.STT` shim). `capabilities=STTCapabilities(streaming=True,
  interim_results=True)`. (nemo_stt.py:45-87)
- `agent/main.py:200` — `stt=NemoSTT(ws_url=NEMO_STT_URL, language="en")` replaces `openai.STT`;
  all `WHISPER_*` config retired; `NEMO_STT_URL` is a `ws://` endpoint.
- `ollama/warmup.py`, `scripts/vram-validate.sh`, `README.md` — faster-whisper fully removed;
  GPU-proc trio renamed to ollama/nemo-stt/kokoro, `EXPECTED_GPU_PROCS=3`.
- LAN-local only: `nemo-stt` on the `adept` Docker network, port LAN-bound — no audio leaves the
  network.

*Operator-gated:* real `.nemo` bake/load, `conformer_stream_step` signature match, Blackwell
sm_120 kernel execution → 09-STT-VERIFY Gates 1, 2.

### STT-02 — growing interim while speaking; ~100ms finalize after end-of-speech; run-ons not stranded
**Assessment: satisfied-in-code (live latency/behavior operator-gated).**

- Growing interim: `decode_chunk` returns the CUMULATIVE transcript per cache-aware step; server
  sends `{"type":"delta","text":<cumulative>}`; plugin `_recv_loop` maps `delta` →
  `INTERIM_TRANSCRIPT`. (server.py:156-182, 311-319; nemo_stt.py:142-151)
- ~100ms finalize via turn-detector flush: the server NEVER auto-finalizes — `final` is emitted
  ONLY in `_handle_control`'s `flush` branch (server.py:251-264). The plugin sends
  `{"type":"flush"}` on the `_FlushSentinel` from AgentSession's `end_input()/flush()`
  (nemo_stt.py:114-120). `stt_ms` = flush-send→final-receipt wall-clock, compared to
  `BUDGET_MS["stt"]=150`, tightening toward ~100ms.
- Run-ons not stranded: `_track_stall` recycles `prev_hyps` + carries the encoder cache forward
  after `STALL_FRAMES` of no growth, logs the recycle, and CONTINUES — it does **not** emit a
  premature FINAL. (server.py:185-200)
- **C1 fix confirmed:** `reset_turn_state` clears `prev_hyps`/stall counters (cache carried
  forward) in direct response to the `flush` frame, so each FINAL is THAT turn only — not the
  cumulative session. (server.py:210-221, 260) This was the one Critical review finding and it is
  fixed.

*Operator-gated:* live growing interim in the panel, measured ~100ms finalize, real stall-recycle
with no premature FINAL → 09-STT-VERIFY Gates 3, 5.

### STT-03 — native punctuation + capitalization surfaced as-is
**Assessment: satisfied-in-code (visual confirmation operator-gated).**

- Server: `decode_chunk` returns `hyps[0].text` verbatim — no strip/lowercase/recapitalize
  (server.py:180, comment 159-160).
- Plugin: `delta`/`final` text passed through into `SpeechData(text=...)` untouched
  (nemo_stt.py:148, 173). No client-side PnC post-processing anywhere.

*Operator-gated:* visible commas/periods/caps (e.g. "SOC") in the live transcript → 09-STT-VERIFY
Gate 3.

### STT-04 — `att_context_size` config knob; cyber-vocab fine-tune as a documented hook only
**Assessment: satisfied-in-code.**

- Knob: `STT_ATT_CONTEXT_SIZE` (default `[56,3]`), parsed + **validated** by
  `_parse_att_context_size` (fail-fast `SystemExit` on a non-2-int-list — M4 fix), applied once via
  `model.encoder.set_default_att_context_size(ATT_CONTEXT_SIZE)`. (server.py:57-75, 113) Surfaced as
  a compose env (`docker-compose.yml:116`) and `.env.example:63`.
- Fine-tune hook: documented in `.env.example:64-66` and 09-STT-VERIFY ("Cyber-vocabulary fine-tune
  HOOK — NOT IMPLEMENTED") as a zero-code-change `STT_MODEL` swap. No fine-tune code/data ships —
  exactly as the requirement scopes it.

### PERF-04 — no voice-to-voice P50 < 1.0s regression
**Assessment: operator-gated-deferred (correctly).**

- Endpoint authority unchanged (see invariants); `metrics.py` untouched so the e2e/stt budget
  scaffold is intact; `_emit_final` populates `stt_ms` (the load-bearing fix). The actual P50
  measurement requires the live GPU loop → 09-STT-VERIFY Gate 4. This is a legitimate operator gate,
  not a phase gap.

---

## Invariants

| Invariant | Status | Evidence |
|-----------|--------|----------|
| No-hardcoded-tag single-source | **HOLDS** | `STT_MODEL` is the sole functional source (compose `build.args`+`environment`, Dockerfile `ARG STT_MODEL`+`ENV`, server `os.environ["STT_MODEL"]` → `SystemExit` if unset). No `nvidia/nemotron…` literal in server.py or agent. The `NemoSTT.model` property returns the generic label `"nemotron-streaming"` (L1 de-literalized) — a metrics label only, not a behavior driver. |
| `agent/metrics.py` READ-ONLY | **HOLDS** | Absent from `git diff 7efb550..3a6d849`. `stt_ms` is fed via the explicit `STTMetrics` emit in `_emit_final` with a REAL measured `duration`. |
| Endpoint authority unchanged | **HOLDS** | `build_session` `turn_handling` dict (Silero VAD + `MultilingualModel`) is byte-identical to the prior phase; FINAL fires ONLY on the flush triggered by the turn detector. NeMo does not own turn-taking; the server never auto-finalizes. |
| Server never auto-emits FINAL | **HOLDS** | `final` sent only in the `flush` branch; stall watchdog logs + recycles, no send. |
| WS robustness (validated, no-crash) | **HOLDS** | Server: `_handle_control_frame` guards bad JSON / non-dict → `error` reply, no crash (H1); disconnect dict raises `WebSocketDisconnect` cleanly (M3). Client: `_recv_loop` filters on `msg.type`, breaks on CLOSE/ERROR, guards bad JSON (H2); `_run` closes the ws on input-exhaust so `await recv` can't hang (M1). |
| No audio to disk/db; LAN-only; no secrets | **HOLDS** | In-memory PCM only; `${LAN_BIND_IP:-127.0.0.1}` bind; no `env_file` on nemo-stt; healthcheck is argv-list `python -c` (no shell injection). |

All 1 Critical (C1), 2 High (H1/H2), and the addressed Medium/Low review findings (M1/M3/M4, L1/L4)
are present in the shipped code. The 2 skipped Lows (L2 `audio_duration=0.0`, L3 overlapping-flush
race) are non-load-bearing and correctly scoped out.

---

## Deferral structure check (09-STT-VERIFY.md)

| Criterion | Status |
|-----------|--------|
| Runbook exists with build/deploy preamble + per-gate steps | YES |
| `status: pending-operator` front-matter | YES |
| Gates enumerated (1–6) covering signature, sm_120, interim/finalize/PnC, P50, stall watchdog, VRAM) | YES (6 gates) |
| Every gate verdict marked PENDING — none falsely marked passed | YES |
| `stt_ms` semantics pinned (finalize latency, the load-bearing line) | YES |
| Sandbox-green items honestly separated from operator gates | YES |

The deferral mirrors Phase 8's unsigned-until-operator GPU gates. Nothing runtime is falsely
claimed passed.

---

## Overall verdict

**CODE-COMPLETE WITH OPERATOR GATE PENDING** (analogous to Phase 8 pre-operator-sign).

- STT-01: satisfied-in-code (model-load operator-gated)
- STT-02: satisfied-in-code (live latency/stall operator-gated)
- STT-03: satisfied-in-code (visual confirmation operator-gated)
- STT-04: satisfied-in-code (fully)
- PERF-04 (no P50 regression): operator-gated-deferred (correctly)

All four requirements are delivered in code; the three load-bearing invariants (no-hardcoded-tag,
metrics.py-untouched, endpoint-authority-unchanged) hold; faster-whisper is fully removed; the one
Critical and both High review findings are fixed. The runtime/behavioral acceptance (real NeMo
decode, Blackwell sm_120, live interim/finalize, voice-to-voice P50<1.0s, VRAM co-residency) is
legitimately operator-gated to 09-STT-VERIFY.md in a GPU-less sandbox — this is the established
project pattern and is correctly structured (runbook present, 6 gates enumerated, status
pending-operator, nothing falsely passed).

**No blocking gaps.** Phase 9 is ready to ship pending the operator GPU sign-off in 09-STT-VERIFY.md.
