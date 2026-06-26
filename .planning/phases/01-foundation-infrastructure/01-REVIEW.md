# Phase 01 — Foundation & Infrastructure: Backfill Code Review

**Scope:** Phase-01 foundational logic only — session wiring (`agent/main.py`),
metrics scaffold (`agent/metrics.py`), warmup (`ollama/warmup.py`), token mint
(`web/app/api/token/route.ts`), web shell, and Docker/compose/LiveKit config.
`agent/main.py` and `agent/metrics.py` were reviewed in their **current** on-disk
state; findings are attributed to Phase-01 logic vs. later-phase additions where
relevant. Static review only — stack was not run (no livekit/Docker/GPU in sandbox).

**Resolution (backfill fixes):** N1 (blocking) FIXED — `agent/Dockerfile` now COPYs `history.py` + `interview.py` (both imported by `main.py`; the image would have `ImportError`ed at container start without them). H1 (unauthenticated `GET /api/token`) and M1–M4 left as documented findings (LAN-trust / hardening; tracked for a future pass).

**Diff context:** `git diff 41fc8e1^ 8e63ad7`
**Overall:** Solid walking-skeleton. Secret handling is correct (no hardcoded
secrets, `.env` gitignored, secret stays server-side). No critical issues. The
main standing item is that the token-mint endpoint is unauthenticated by design —
acceptable LAN-only, but a gate is required before any non-LAN exposure.

---

## Findings by Severity

### Critical
None.

### High

**H1 — Token-mint endpoint is unauthenticated and issues publish-capable JWTs**
`web/app/api/token/route.ts:16-40`
`GET /api/token` requires no auth and returns a signed LiveKit JWT with
`roomJoin: true, canPublish: true, canSubscribe: true` for room `adept` to any
caller that can reach the web service. For the Phase-1 LAN-only posture (all ports
bound to `LAN_BIND_IP`, default `127.0.0.1`) this is acceptable and matches plan
intent. However, it is a standing security gate: the moment the web service is
reachable from a wider network, anyone can mint a valid media-publishing token.
- *Recommendation:* Before Phase 2 / any non-localhost bind, add at minimum a
  shared-secret/session check and accept identity/room server-side only. Track
  explicitly so it is not forgotten when `LAN_BIND_IP` is widened. The secret
  handling itself is correct (`force-dynamic`, server-side env, never
  `NEXT_PUBLIC_*`).

### Medium

**M1 — Unbounded `_turns` buffer growth (memory leak on turns that never reach TTS)**
`agent/metrics.py:76,86-95,98-116,225-235`
Turn buffers are created in `_buffer_for()` (on EOU/LLM/TTS) and only removed in
`_flush_turn()`, which is invoked **only** from the TTS handler
(`_on_tts_metrics`). Any turn that never produces a TTS metric — an errored/
interrupted reply, a user turn with no agent speech, or a stage that fires EOU/STT
but no TTS — leaves its buffer in `_turns` forever. Over a long session this grows
without bound.
- *Note:* The turn-keyed buffer is a later-phase (02-03) addition on top of the
  Phase-01 scaffold; the original Phase-01 `metrics.py` had no `_turns` dict. Flag
  for the metrics owner.
- *Recommendation:* Cap/evict `_turns` (e.g. drop oldest beyond an LRU bound, or
  flush stale buffers on a timeout / on session end).

**M2 — Token identity collisions via `Date.now()`**
`web/app/api/token/route.ts:27`
`identity = user-${Date.now()}` is not unique under concurrency: two requests in
the same millisecond get the same identity, and LiveKit evicts the older
participant when a duplicate identity joins. Low probability single-user, real for
multi-tab / load.
- *Recommendation:* Use `crypto.randomUUID()` (or append it) for the identity.

**M3 — `.env` (incl. `LIVEKIT_API_SECRET`) broadcast to every container**
`docker-compose.yml:16,36,48,88,107,127,139`
All services use `env_file: .env`, so `LIVEKIT_API_SECRET` (and other secrets) are
injected into `ollama`, `whisper`, `kokoro`, and `agent`, none of which need it —
only `livekit-server` (via `LIVEKIT_KEYS`) and `web` (token route) do. Widens the
secret blast radius unnecessarily.
- *Recommendation:* Scope `env_file`/`environment` per service to only the vars
  each needs.

**M4 — Whisper model drift between agent and warmup (later-phase)**
`agent/main.py:45` (`Systran/faster-whisper-large-v3`) vs.
`ollama/warmup.py:47` (default `Systran/faster-whisper-large-v3-turbo`)
The agent STT loads `large-v3` while the host warmer defaults to `large-v3-turbo`.
The warmup then forces a *different* model resident than the one the agent uses,
defeating the warm and risking two STT models co-resident in VRAM. In the original
Phase-01 `main.py` both were `large-v3-turbo` (consistent); the divergence is a
later-phase edit to `main.py`.
- *Recommendation:* Single-source the whisper model name (env) across agent and
  warmup.

### Low

**L1 — `npm install` instead of `npm ci`** `web/Dockerfile:5`
A `package-lock.json` is present but `npm install` may mutate it / drift versions.
Use `npm ci` for reproducible image builds.

**L2 — `depends_on` has no readiness condition** `docker-compose.yml:39-43`
The agent depends on `ollama`/`whisper`/`kokoro` by start order only, not
readiness. On boot the prewarm warmup will hit a not-yet-ready Ollama and crash;
`restart: unless-stopped` recovers via crash-loop. Functional but noisy.
- *Recommendation:* Add healthchecks + `condition: service_healthy`, or keep the
  crash-loop intentionally and document it.

**L3 — Module-global metrics state is not concurrency-safe**
`agent/metrics.py:76-77,88-94,220`
`_turns`, `_last_turn_key`, `_turns_emitted` are module globals shared across all
jobs/sessions in a worker process. Fine for the single-session MVP; concurrent
sessions would interleave into one buffer and `_last_turn_key` (the STT-attach
fallback) is racy. Document the single-session assumption.

**L4 — No security headers on the web shell** `web/next.config.mjs`
No CSP / HSTS / frame headers. Acceptable for the LAN walking skeleton; revisit if
exposed more broadly.

**L5 — Agent log handler never detaches** `agent/metrics.py:250-266`
`attach()` subscribes per-plugin `metrics_collected` with no unsubscribe. Because
each job builds fresh plugin instances, old subscriptions GC with the old session,
so no leak in practice — noted only for completeness.

---

## Out-of-Scope Notes (later-phase regressions in scoped files)

These are NOT Phase-01 defects but surfaced in files within the review scope; flag
to the later-phase owners.

**N1 — Agent Dockerfile `COPY` omits `history.py` and `interview.py`**
`agent/Dockerfile:28` copies `metrics.py persona.py main.py` + `kb/`, but the
current `agent/main.py:29-30` imports `history` and `interview`. The built image
would fail at runtime with `ImportError` on `python main.py start`. These modules
were added by later phases (06 interview / history-window) without updating the
COPY list. **Recommend fixing before next image build.**

**N2 — Kokoro TTS model name `kokoro` → `tts-1` (resolved later)**
The original Phase-01 `main.py` set `KOKORO_MODEL = "kokoro"`, which (per the
detailed comment now at `agent/main.py:46-51`) routes the LiveKit OpenAI TTS plugin
down the SSE path that kokoro-fastapi ignores → zero audio frames. This was a
latent Phase-01 bug that did not surface because Phase 1 starts no voice turn; it
was corrected to `tts-1` in a later phase. Current state is correct. Note for the
record. (The host-side `ollama/warmup.py` keeps `kokoro`, which is correct there —
it calls `/v1/audio/speech` directly, not via the plugin.)

---

## Verified Good

- **No hardcoded secrets** anywhere in source; `.env` is gitignored
  (`.gitignore`: `.env`, `certs/*.pem`). `livekit.yaml` carries no key; keys come
  from `LIVEKIT_KEYS` built from `.env`. `api_key="none"` placeholders in
  `main.py` are for the keyless local STT/TTS endpoints — not secrets.
- **Token secret never reaches the browser** — server-side `process.env`,
  `force-dynamic`, missing-config returns 500 instead of leaking. Identity is
  server-generated (no client identity injection).
- **Local-first / no-egress design is sound** — `livekit.yaml` uses
  `node_ip` + `use_external_ip: false` (no STUN/WAN), udp mux 7882, ports bound to
  `LAN_BIND_IP`. Turn detector is the local `MultilingualModel`; no
  `inference.TurnDetector`. Metrics emit to stdout only (no Prometheus/Opik/OTel).
- **Metrics scaffold uses the non-deprecated per-plugin `metrics_collected`**
  subscription (`metrics.py:263-266`), not the session-level event. Budget
  constants present. Seconds→ms conversion correct.
- **Warmup correctness** — streaming first-token TTFT measured correctly;
  `warm_llm` asserts no `<think>` preamble (think-off guard); sync client in the
  sync `prewarm` hook is appropriate.
- **Web shell** (`SecureContextProbe.tsx`, `layout.tsx`, `page.tsx`) and
  `next.config.mjs` (`output: "standalone"`) are clean and minimal.

---

## Report

- **Severity counts:** Critical 0 · High 1 · Medium 4 · Low 5 · Notes 2
- **Top action items:** H1 (gate token endpoint before non-LAN exposure),
  M1 (`_turns` leak), N1 (Dockerfile COPY — runtime breakage).
- **Report path:** `.planning/phases/01-foundation-infrastructure/01-REVIEW.md`
