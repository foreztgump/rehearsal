# Changelog

All notable changes to Rehearsal are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); commits use
[Conventional Commits](https://www.conventionalcommits.org/).

## [Unreleased]

### Added
- `web`: **selectable avatar faces.** When Avatar mode is on, the setup screen shows
  an **Avatar face** picker — **Auto (match persona)** plus four vendored faces
  (Cyber Trainer, Brunette, Avaturn, Avatar SDK male) in the new
  `AVATAR_CATALOG` (`web/app/avatarConfig.ts`). An explicit pick overrides the
  persona's model but keeps the persona's resting mood, so expression continuity is
  preserved; "Auto" keeps today's persona-matched behaviour. Purely client-side —
  no agent/server/compose change (the agent never touches GLB files). Wired through
  `SessionConfig.selectedAvatarId` (`VoiceRoom.tsx`) into `AvatarStage`, which now
  resolves its GLB via `resolveAvatar(persona, avatarId)`. The four new faces are the
  verified TalkingHead example set (all free / non-commercial — see
  `web/public/avatars/ATTRIBUTION.md`); Ready Player Me's public avatar API shut down
  on 2026-01-31, so faces are pre-vendored rather than fetched on demand. New
  `scripts/verify-avatars.mjs` checks every catalog GLB carries the 15 Oculus visemes
  + ARKit blendshapes AND is not meshopt-compressed (AvatarStage wires only the Draco
  decoder), so an incompatible model can't ship unnoticed.
- `web`/`compose`/`install`: **expressive voice is now a real, install-aware option.**
  The setup screen shows a named **Voice** picker — **Kokoro · fast** vs
  **Chatterbox · expressive** — instead of a generic toggle, so the active engine is
  explicit rather than reading as "stuck on Kokoro". The picker is baked in only when
  the expressive engine was actually installed (`NEXT_PUBLIC_REHEARSAL_EXPRESSIVE_AVAILABLE`,
  set by the installer); otherwise it is hidden entirely and `expressiveVoice` is clamped
  off so a held value can never route a Chatterbox `tts.update` to a stack that has no
  chatterbox service. New `web/app/voiceEngine.ts`; wired through `SetupScreen.tsx` and
  `VoiceRoom.tsx`, with a matching web build-arg in `web/Dockerfile`.
- `install`: **opt-in expressive-voice install** via `./install.sh --expressive` /
  `.\install.ps1 -Expressive` (or `INSTALL_EXPRESSIVE=1`). NVIDIA-gated and off by
  default (large ~19 GB build, +4.3 GB VRAM, exceeds the P50<1.0s budget). When enabled
  the installer builds the `chatterbox` service, writes
  `NEXT_PUBLIC_REHEARSAL_EXPRESSIVE_AVAILABLE=1` + `COMPOSE_PROFILES=expressive` to
  `.env`, and rebuilds web so the picker appears; re-running without the flag turns it
  back off. Documented in `INSTALLATION.md` (new "Expressive Voice (Opt-In)" section).
- `web`: the avatar's **brows now lift subtly while it speaks** so the face reads as
  engaged rather than a still mask under a moving mouth. A heavily smoothed
  engagement envelope drives the outer-brow morphs off the same speech-energy signal
  the mouth uses (`web/app/AvatarStage.tsx`: `BROW_MORPHS` + `BROW_LIFT_*` constants),
  with a very slow attack/release so the brows drift with phrase energy instead of
  twitching per syllable. It drives `browOuterUp*` specifically (never `browInnerUp`)
  because the realtime morph tier *overrides* the mood baseline, so touching the inner
  brows would stomp the emotional brows (sad's furrow, love's raise); the outer brows
  are ~0 across moods, so the lift never fights a mood's expression. Released back to
  the mood baseline on mute/turn-end alongside the mouth morphs.
- `web`/`agent`: the 3D avatar now **laughs on its face when the voice laughs**. In
  expressive mode the agent tags a sentence's laugh cue (`laugh`/`chuckle`, from the
  `[laugh]`/`[chuckle]` tag it already emits) onto the per-sentence `lk.avatar.mood`
  packet (`agent/paralinguistics.py` `laugh_kind`, published in `agent/expressive_tts.py`),
  and `web/app/AvatarStage.tsx` plays a transient TalkingHead emoji gesture (😂 full
  laugh / 🙂 chuckle) at the audio anchor so the expression lands in sync with the
  vocalized laugh, then settles back. Avatar-gated (no data when Avatar is OFF); the
  Kokoro path is unaffected (it strips laugh tags, so there is no laugh to mirror).
- `web`: while speaking the avatar now **holds eye contact and faces the user**
  (looks straight), like an attentive coach, instead of drifting off-center or turning
  away mid-sentence. Two dials in `web/app/avatarConfig.ts`: the gaussian head-TURN
  probability is off (`avatarSpeakingHeadMove` 0, `avatarSpeakingEyeContact` 1), and the
  speaking gaze lock now pins the head-rotate axes (`headRotateX/Y/Z`) as well as the
  eyes so mood/gesture animations can't rotate the head off the camera. It doesn't read
  as a frozen statue despite the steady head because the face is kept alive by the mouth
  visemes, the engagement brows, and the laugh gesture, and the volume-synced neck bob
  is applied independently of these head morphs, so a subtle breathing nod survives the
  pin. The lock is released on turn-end so ambient scanning resumes between turns.
- `web`: the **laugh reaction is now brief** so it no longer keeps a laughing face
  (eyes closed, jaw open, big smile) while the trainer talks through the words that
  follow a `[laugh]`/`[chuckle]`. `LAUGH_GESTURE_SECONDS` dropped to 1.0s (laugh) / 0.7s
  (chuckle) from 2.5s/1.5s (`web/app/avatarConfig.ts`) — the emoji gesture pins mouth
  and eye morphs, so a long hold fought the viseme lipsync; a short reaction lands the
  laugh and settles back before the next words.
- `agent`/`web`/`compose`: opt-in **expressive voice** mode. A new toggle swaps the
  default Kokoro TTS for **Chatterbox-Turbo** (`agent/expressive_tts.py`). Turbo has no
  numeric emotion knob (it ignores `exaggeration`), so expressiveness rides its two
  honored levers, both driven by the *same* per-sentence lexicon mood that moves the
  avatar face: `temperature` scales with mood (animated for praise, subdued for
  sympathy, with a lifted neutral baseline so every line is livelier than Kokoro), and
  **real laughter**. The persona is permitted to be warm and to insert Turbo's native
  paralinguistic tags — the exact tokens `[laugh]` / `[chuckle]` (lowercase, square
  brackets; parentheses or angle brackets are spoken as noise) — which the model
  vocalizes as genuine laughter. `agent/paralinguistics.py` passes those tags through to
  the expressive engine and strips them for Kokoro (which would otherwise speak the
  word). A direct user request to laugh also forces `[laugh]` onto that reply so it works
  on demand. Synthesis uses the server's `/tts` route (the OpenAI `/v1/audio/speech` route
  silently drops `temperature`). GPU-only, ~4.3 GB VRAM, served by a new pinned
  `chatterbox` compose service (`rehearsal-chatterbox:turbo-cu128`, built from
  devnen/Chatterbox-TTS-Server `Dockerfile.cu128` for Blackwell/sm_120) with a
  persistent model-cache volume. The engine is switched **live** per session via a
  `tts.update {expressive}` RPC through a session-lifetime wrapper
  (`agent/expressive_mode_tts.py`) that preserves the metrics subscription across
  swaps. Persona `voice_id`s map to gender-matched Chatterbox voices
  (`agent/voice_map.py`); mood→temperature is a pure table (`agent/emotion_voice.py`).
  Because Chatterbox returns no word timestamps, expressive mode uses Path-A energy
  lip-sync and publishes the per-sentence mood on its own avatar-gated `lk.avatar.mood`
  topic (Kokoro mode still piggybacks the lipsync schedule). **OFF by default** —
  expressive synthesis runs ~0.8–1.2 s/sentence and deliberately exceeds the
  voice-to-voice P50<1.0 s budget; Kokoro remains the default low-latency path.
- `agent`/`web`: per-sentence avatar **emotion**. The 3D avatar's baseline facial
  mood now tracks what the trainer is saying, changing per sentence as it speaks
  (praise → `happy`, warmth → `love`, sympathy → `sad`, otherwise `neutral`) instead
  of a single fixed speaking expression. The agent maps each synthesized sentence to
  a mood with a pure, GPU-free keyword lexicon (`agent/emotion.py`) and piggybacks
  the label onto the existing `lk.avatar.lipsync` schedule payload — no new data
  channel, no model, off the audio hot path. The browser applies the mood at the
  moment that sentence's audio anchors (in the lip-sync rAF tick), so expression
  never races ahead of speech. Gated by avatar-ON exactly like lip-sync: with Avatar
  OFF no mood ships and voice-only stays byte-identical (AVTR-12 preserved). Unknown/
  missing moods fall back to `neutral` (guards TalkingHead `setMood`, which throws on
  an unknown label).

### Changed
- `web`: the persona **Voice picker now shows human-readable, engine-honest names**
  instead of raw ids like `af_bella`. In standard mode it reads "Bella — US, female"
  (decoded from the id's accent/gender prefix by a new `formatVoiceLabel` helper in
  `web/app/savedPersonas.ts`). In **expressive** mode it shows the *actual* Chatterbox
  voice the agent maps to — e.g. "Olivia — female" — so the label matches what is heard
  rather than promising a Kokoro voice Chatterbox doesn't have (the expressive map
  preserves gender only, not accent). A new `web/app/voiceMap.ts` mirrors the agent's
  canonical `agent/voice_map.py` for display; the option VALUE is unchanged (still the
  `voice_id` contract). Applies to the picker in both the setup screen and the drawer.
- `compose`: the `chatterbox` (expressive voice) service is now **behind the
  `expressive` profile and buildable via `docker compose build`**. Previously it was in
  the agent's hard `depends_on` yet had no build context, so a default `docker compose
  up` would fail on the missing image; now it is only built/started when the profile is
  enabled, and its image is produced from a pinned remote-git build context
  (devnen/Chatterbox-TTS-Server `Dockerfile.cu128`) instead of a manual out-of-band
  build. The agent no longer hard-depends on it (it reaches Chatterbox lazily via
  `tts.update`), so the default Kokoro stack is unaffected.
- `web`: **sharper, more fluid mouth articulation** during speech. The energy-driven
  lip-sync now opens wider on loud syllables and forms lip shapes on softer ones
  (`web/app/AvatarStage.tsx`: `MOUTH_OPEN_MAX` 0.6→0.75, `VISEME_INTENSITY` 0.7→0.85,
  Path-A viseme gate 0.06→0.045), while the open/close *timing* is eased (not sped up)
  so the motion flows instead of snapping mechanically. Magnitude and timing are tuned
  separately: visible articulation without the rigid, hinge-like look.
- `agent`: expressive voice now adds a **mood-scaled breath between sentences** so
  multi-sentence replies stop running together. Each Chatterbox sentence clip gets a
  short trailing pad of pure silence (`agent/wav_pad.py`, sized by
  `emotion_voice.pad_ms_for_mood` — sympathy longest at 280 ms, praise shortest at
  120 ms, neutral 180 ms). Silence leaves the model audio byte-for-byte untouched, so
  unlike the rejected `speed_factor` time-stretch it adds pacing with zero quality cost;
  it applies only to the expressive path (Kokoro is unaffected).
- `agent`: rewrote the spoken-delivery instructions so the coach **stops faking laughter
  and carries emotion in its words** (`agent/persona.py` footer + the forced-laugh nudge
  in `agent/main.py`). The model was writing spelled-out laughter ("hahaha!") alongside
  the real `[laugh]` token, and Chatterbox reads those letters syllable-by-syllable as an
  ugly, robotic fake laugh. The new footer teaches the model that everything it writes is
  spoken (so emotion must live in word choice, not punctuation or stage directions),
  forbids spelled-out laughter at length, and reserves the two native tags `[laugh]` /
  `[chuckle]` as the only real laugh — used rarely and only when genuinely funny. Verified
  live against the failing transcript: zero spelled-out laughter across the laugh-request
  turns, warm words when a laugh isn't earned.
- `agent`: the expressive coach now **varies its sentence rhythm** for a more natural
  cadence — short punchy lines mixed with longer flowing ones, clipped when the learner
  is upset or thinking and stretched when encouraging (`agent/persona.py`). This replaces
  the earlier reliance on punctuation for pauses (Chatterbox-Turbo barely voices commas/
  em-dashes as silence — verified live). Note: Turbo's `speed_factor` knob is
  deliberately left unused — the server implements it as a post-hoc librosa time-stretch
  that sounds robotic, so pace is shaped by wording, not by warping the waveform.
- `agent`: the Voice Fluency Coach persona now **sounds like a warm human**, not a
  clinical assistant. Prompt-only change (`agent/persona.py`) grounded in voice-agent
  prompting research (LiveKit + Vapi): personality is written as *audible behaviors*
  (contractions, And/But/So openers, a light filler once or twice a reply, warm
  specific reactions like "Yeah — that's exactly it" over "That is correct"), rhythm is
  varied on purpose (short punchy lines mixed with longer flowing ones, clipped when the
  learner is upset or thinking and stretched when encouraging), and emotion is a
  *constraint* — a calm warm baseline with laughter reserved to roughly one turn in five,
  never two in a row.
  It still marks genuine laughs with Turbo's native `[laugh]`/`[chuckle]` tags (and no
  longer refuses when asked to laugh). The `sad` avatar-mood lexicon
  (`agent/emotion.py`) gained a few empathy phrases ("that's rough", "I hear you",
  "that's frustrating") so genuine sympathy still moves the face. A new
  `tests/test_persona_golden.py` runs the persona byte-stability self-check in the
  normal test sweep so a prompt edit can no longer silently drift the golden string.

### Docs
- `README`: added a **Features** section and a **Voice & avatar** subsection so the
  front page actually surfaces the two headline optional features — the 3D avatar
  (lip-sync, per-sentence emotion, head motion, laughter, brows) and the opt-in
  expressive voice (Kokoro-default vs Chatterbox tradeoff, `--expressive` install) —
  with a deep link to the INSTALLATION.md expressive-voice section.
- `docs`/`README`: added an animated UI-preview GIF and centered hero block to the
  top of the README (`docs/assets/rehearsal-demo.gif`), rendered from the
  `design-mockups/v4` aurora-veil concept, so the project page shows the session
  UI at a glance. Labeled "UI preview" — it is the interface, not a captured
  live-latency benchmark.
- `docs`/`install`: the macOS Ollama bind-widen step now documents the Ollama Mac
  app's **Settings → "Expose Ollama to the network"** GUI toggle (v0.10+) as an
  equivalent to `launchctl setenv OLLAMA_HOST "0.0.0.0:11434"` — either binds
  `0.0.0.0`. Explains why some Macs reach `host.docker.internal:11434` without ever
  setting `OLLAMA_HOST` (the GUI toggle was already on). The macOS validation
  checklist step 1 no longer treats an empty `launchctl getenv OLLAMA_HOST` as a
  failure (a false negative when the GUI toggle was used) — the container-side curl
  (step 3) is the source of truth. Updated in INSTALLATION.md, `install.sh`,
  `docker-compose.macos.yml`, and `scripts/gpu-doctor.sh`.

### Fixed
- `agent`: the "laugh on command" path no longer fires on **incidental mentions** of
  laughter. `wants_laugh` now word-boundary matches (`\b(?:laugh|lol|(?:ha){2,})\b`), so
  "I was laughing about that", "that's laughable", "we shared a lot of laughter", and
  "lollipop" no longer force a `[laugh]` onto the reply — only a direct command
  ("laugh", "lol", "haha…") does. Regression tests added in `tests/test_paralinguistics.py`.
- `web`/`install`: review-pass fixes on the avatar/voice branch — (1) updated two stale
  avatar gaze-lock tests that still asserted the pre-"come alive" behaviour
  (`avatarSpeakingHeadMove` 0 and head-axis locks) after Avatar A freed head motion;
  (2) added the missing `.ts` extension on `savedPersonas.ts`'s `voiceMap` import so the
  Node `.mjs` tests load it; (3) made the installer's `COMPOSE_PROFILES` edit
  token-accurate in both `install.sh` and `install.ps1` so disabling expressive removes
  only the `expressive` token and preserves any other profile (e.g. `stt-gpu`); and
  (4) made the compose-topology default render hermetic against a persisted
  `COMPOSE_PROFILES` in `.env`. Added `formatVoiceLabel` unit tests incl. a
  web↔agent voice-map drift guard.
- `agent`: the avatar no longer turns **sad on plain acknowledgment**. `"i hear you"`
  was removed from the sympathy lexicon (`agent/emotion.py`) because the coach uses it
  as an agreement opener (`"i hear you have some concerns…"`) far more often than as
  standalone empathy, so its substring match was flipping the face sad on ordinary
  agreement. The unambiguous empathy phrases (`"sorry to hear"`, `"that must be hard"`,
  …) still map to sad. Regression test added in `tests/test_emotion.py`.

## [0.3.0] - 2026-07-04

macOS (Apple Silicon) gets a real GPU voice path: TTS now runs in native-host
Kokoro-FastAPI on Metal (default, ~256 ms P50 vs ~799 ms for the old CPU container),
joining the already-native Ollama LLM so both GPU services run on the host. Includes
the bring-up helper, the compose override, installer/doc/provenance updates, and two
fixes surfaced by M5 live testing (model-weights download, CPU-STT pinning) — the
topology is validated end-to-end with a working voice-to-voice turn.

### Added
- `compose`: `docker-compose.macos.yml` — macOS (Apple Silicon) override for the
  native-host topology. Docker Desktop on Mac has no GPU passthrough, so both GPU
  services run natively — the LLM in the Ollama Mac app (Metal/MLX) and TTS in native
  Kokoro-FastAPI (Metal/MPS) — with the Docker services reaching them via
  `host.docker.internal:11434` and `:8880`; the in-stack ollama and kokoro are
  `alpine` no-op stubs. No `cpu-tts` override on macOS anymore.
- `install`: `scripts/kokoro-native-macos.sh` — bring-up helper for native-host Kokoro
  TTS. Clones Kokoro-FastAPI pinned to `v0.5.0`, creates the venv, and launches on
  Metal/MPS by default (`--cpu` selects the CPU fallback; `stop` halts it). Encodes the
  macOS-specific fixes (brew `espeak-ng` data path, upstream install-before-venv
  ordering). Measured on an M5: native Metal ~256 ms P50 vs ~799 ms for the CPU
  container (see `docs/adr/0002` + `docs/macos-tts-benchmark-results.md`).
- `install.sh` detects macOS (`uname -s = Darwin`) and prints the exact manual
  steps — install the Ollama Mac app, `launchctl setenv OLLAMA_HOST "0.0.0.0:11434"`
  (+ restart), `ollama pull`, scaffold `.env`, start native Kokoro TTS, then bring
  the stack up with the `macos` override (TTS is native now, no `cpu-tts`) — then
  stops, instead of running the wrong all-in-container CPU topology.
- `gpu-doctor.sh` gains a macOS branch: it recognizes `Darwin` as the native-Ollama
  + Metal path (not a misleading "no GPU" degrade) and advises the `OLLAMA_HOST`
  bind widen, the macOS compose invocation, and CPU-STT `.env` settings.
- `docs`: INSTALLATION.md gains a "macOS (Apple Silicon)" section — native host
  Ollama AND Kokoro on Metal, the `OLLAMA_HOST=0.0.0.0` bind step, the native-Kokoro
  bring-up + health check, the abliterated-GGUF default vs the stock/content-filtered
  MLX-tag opt-in (`gemma4:e2b-nvfp4` / `gemma4:e4b-mlx-bf16`) tradeoff, an ordered M5
  validation checklist, and the measured TTS latency (native Metal Kokoro ~256 ms P50,
  vs ~799 ms for the CPU container). README Platform Support and SECURITY_PROVENANCE
  updated to match.
- `test`: `scripts/test_compose_topology.sh` asserts the macOS override render
  (agent → `host.docker.internal` for both Ollama and Kokoro; ollama + kokoro no-op
  stubs).
- `ci`: automated code review on every pull request. Review-only
  (describe/improve off). Requires the review API key repo secret.

### Changed
- `compose`/`install`: macOS (Apple Silicon) default TTS is now **native-host Kokoro on
  Metal**, not the `cpu-tts` container. The macOS `docker compose … up` command drops
  `-f docker-compose.cpu-tts.yml` (the `macos` override now stubs the `kokoro` container
  and points `KOKORO_BASE_URL` at `host.docker.internal:8880`). native-CPU Kokoro remains
  a documented one-flag fallback (`scripts/kokoro-native-macos.sh --cpu`).

### Fixed
- `install`: `scripts/kokoro-native-macos.sh` now downloads the Kokoro v1.0 model
  weights (`docker/scripts/download_model.py`) before launching uvicorn. Because the
  script launches uvicorn directly (rather than via upstream's `start-*.sh`, which
  fetch the weights), the server previously crashed on startup with
  `FileNotFoundError: v1_0/kokoro-v1_0.pth` and never became healthy. Idempotent —
  skips the ~327 MB download when the weights already exist. Found in M5 live testing.
- `docs`: the macOS `.env` guidance (INSTALLATION.md step 4 and `install.sh`) now
  calls out keeping `STT_FORCE_CPU=1` — the `.env.example` default — and the "stuck on
  Listening to you…" troubleshooting row gains a macOS/Windows-AMD remedy. Docker on
  Mac has no container GPU, so setting it to `0` sends STT placement to a `nemo-stt`
  service that never starts and the agent hangs with `Cannot connect to host
  nemo-stt:8000`. Found in M5 live testing (voice-to-voice then works end-to-end:
  STT ~113 ms, LLM TTFT ~392 ms P50, native-Metal TTS TTFB ~907 ms P50).

### Security
- `docs`: the macOS `OLLAMA_HOST=0.0.0.0:11434` bind step (INSTALLATION.md and
  `install.sh` guidance) now warns that it exposes Ollama's **unauthenticated** API
  to the LAN — required only because the Docker VM's `host.docker.internal` cannot
  reach a `127.0.0.1`-only bind. Advises keeping the macOS firewall on and never
  port-forwarding `11434` to the WAN (same posture as the `127.0.0.1` default-port
  rule for the rest of the stack).

## [0.2.2] - 2026-07-03

Field-report follow-through: the Windows AMD install path, VRAM-aware model
defaults, a health-gated finish line, an STT-profile preflight warning, and the
docs to match — plus the F34 non-root turn-detector fix from the 0.2.1 live test.

### Added
- `install.ps1` detects Windows AMD (including Vulkan-only RDNA cards with no
  ROCm marker, via the video-adapter name) and prints the exact native-Ollama +
  Vulkan manual steps, then stops — instead of silently running the wrong NVIDIA
  topology (the AMD stack needs the `windows-amd` + `cpu-tts` overrides the
  one-liner never loaded).
- `gpu-doctor.ps1` gains an AMD branch: it advises the native-Ollama + Vulkan
  path and skips the NVIDIA-only CUDA/VRAM floors on AMD hosts.
- Installers health-gate the finish line: after `up -d` they poll the agent logs
  for `registered worker` (bounded by `READY_TIMEOUT_S`, default 180s) and print
  a real "ready to talk", or advise that a sub-16GB/CPU first turn is slow.
- `up.sh` / `up.ps1` warn when `.env` selects GPU STT (`STT_FORCE_CPU=0` +
  `STT_HEADROOM_MEASURED=1`) but the opt-in `stt-gpu` profile is not enabled —
  the case that otherwise fails with a cryptic `Connection error.`
- `INSTALLATION.md` gains a full Windows AMD walkthrough (native Ollama, the
  permanent-Vulkan-env dance, single-model `.env` narrowing, `ollama ps`
  verification) and an "Upgrading from a pre-rename install" section covering the
  `voice-trainer` -> `rehearsal` compose-project split and orphaned model volume.

### Changed
- Installers default the LLM tier by detected VRAM: NVIDIA cards at/below
  `VRAM_SMALL_MB` (8192) default to the smaller `floor` model instead of `fast`;
  the detected VRAM and chosen default are surfaced so an interactive user can
  override.
- `gpu-doctor.ps1` and `install.ps1` read VRAM from `nvidia-smi`, never
  `Win32_VideoController.AdapterRAM` (a uint32 that wraps at 4GB and under-reports
  8GB cards).
- Docs and override headers use explicit `-f` flags on Windows instead of
  `COMPOSE_FILE=...:...` (the `:` separator collides with Windows drive letters);
  the `docker-compose.amd.yml` / `windows-amd.yml` / `cpu-tts.yml` headers note
  the caveat.
- `INSTALLATION.md` troubleshooting replaces the stale "PR #1 fixes this" rows
  with the shipped state and adds STT-profile, low-VRAM-first-turn, and
  pre-rename-`down` rows; `README.md` points LAN guidance at
  `docs/lan-exposure.md` and bumps the release line to 0.2.2.
- `web` SettingsDrawer scrim/panel/close/End controls now use the shared theme
  classes (`.drawer-scrim`, `.surface`, `.btn-ghost[.danger]`, `.btn-apply.danger`)
  instead of hardcoded inline styles.

### Fixed
- Agent worker no longer crash-loops on every job with `Could not find file
  "languages.json"`. The F34 non-root-user hardening baked the turn-detector
  weights into `/root/.cache/huggingface` (root-owned, since `download-files`
  ran before `USER app`), but the runtime `app` user had no writable HOME
  (`--no-create-home`) and couldn't read the root cache, so the local
  `MultilingualModel` turn detector failed to initialize on every room dispatch
  and the publisher data channel closed. The Dockerfile now pins
  `HF_HOME=/app/.hf-cache` so the cache bakes under `/app` and is chowned to
  `app` by the existing `chown -R app:app /app`, making it readable at runtime.

## [0.2.1] - 2026-07-03

Review Batches A–H (PR #2 and #3): KB/STT/web fixes, the LAN TLS proxy
override, hardening and supply-chain pinning, CI, and latency/perf
optimizations. Also ships the Windows one-line install and installer
robustness work.

### Added
- LAN TLS proxy override (`docker-compose.proxy.yml`) with `PROXY_BIND_IP`
  split-binding and caddy 2.11.4, so the stack can be exposed on the LAN with
  a single pinned-image override; a compose test asserts the topology.
- STT concurrent-connection cap plus a LAN hardening runbook, bounding how many
  simultaneous ASR sessions the sidecar accepts.
- Minimal GitHub Actions CI workflow (typecheck, ruff, basedpyright, stub
  tests).
- `ollama/pull-and-pin.sh` now records pulled model manifest digests and wires
  `verify-build` into the pull flow.
- Agent and web containers run as a non-root `USER` with a `HEALTHCHECK`, and
  the agent base image is digest-pinned.
- Windows one-line install (`irm …/install.ps1 | iex`) that clones the repo and
  runs the native installer, mirroring the Linux curl bootstrap.
- `INSTALLATION.md` with platform prerequisites, first-run download size
  expectations, troubleshooting, and an AI-agent install prompt.

### Changed
- Web `tsconfig` strict mode enabled and enforced in CI.
- Ollama pinned image bumped 0.30.10 -> 0.30.11.
- KB ingest now short-circuits before parse when the session is full, and
  multi-file uploads coalesce into one batched distill call.
- STT raw-silence EOU logic extended to the buffered path.
- CPU legacy-ONNX export gated behind a build ARG so GPU images stay lean.
- Agent deps install with `uv --no-cache`.
- Web `Visualizer` hoists the per-frame `Uint8Array` allocation out of the
  render loop; per-line transcript rendering is memoized.
- `curl … install.sh | bash` detects Windows (Git Bash / MSYS / Cygwin) and
  hands off to the PowerShell installer; `install.ps1` runs `pull-and-pin.sh`
  via Git Bash (not the WSL `bash.exe` shim) with a clear error when absent.
- `gpu-doctor.ps1` checks the driver's CUDA version against the 12.8 floor
  (parity with `gpu-doctor.sh`).
- README is shorter and points detailed install guidance to `INSTALLATION.md`.

### Security
- KB DOCX parser rejects XML DTD/entity declarations before parsing.
- KB distill delimiters neutralized against spoofing and a token budget enforced
  on the distilled stream.
- Agent KB distill stream bounded by wall-clock and byte count; Ollama error
  chunks surfaced instead of swallowed.
- Agent PDF extraction capped at a max page count.
- `livekit-agents` pinned to `==1.6.4` and the `_opts` surface guarded at
  startup.
- STT `python-multipart` pinned in the GPU image deps.
- STT offline `/v1/audio/transcriptions` route hardened (lock, size cap, WAV
  validation).
- `STT_DEBUG_HYBRID` exposure now warns, and dead debug code was dropped.

### Fixed
- STT folds held text forward on stall recycle; caps hybrid `_turn_pcm` at
  `_MAX_BUFFER_BYTES`; guards the WS config handshake with try/except + timeout;
  suppresses spurious empty deltas after finals; deletes dead
  `RECYCLE_HARD_CHARS` config; trims inter-turn silence from the buffered
  finalize buffer.
- `NemoSTT` reconnects on transport errors and survives bad correction
  callbacks.
- Agent KB byte stream capped in-loop and accumulated into a bytearray;
  unexpected `ingest_kb` failures are contained so the KB panel unsticks;
  `ByteStreamInfo.mime_type` is used to unbrick KB upload.
- Web confirms the top-bar End before destroying the session; recovers from
  terminal LiveKit disconnect; handles drag/drop on both KB dropzones; gates
  setup apply on agent readiness and honors RPC acks; re-arms the
  `avatar.update` retry budget on every toggle; strips unknown persona keys on
  load so agent apply doesn't silently fail.
- Compose Windows-AMD ollama stub port publish reset (field report Bug #1).
- Install gates AMD/no-GPU hosts onto the CPU compose override and makes the
  bootstrap idempotent.
- `gpu-doctor.ps1` WSL2 toolkit remedy corrected; gpu-doctor stops backtick
  escapes garbling Windows advise messages.
- Windows `up.ps1`/`down.ps1` gained the missing `up`/`down` subcommand.
- `security-check.sh` gates shellcheck at `-S error` to drop benign false
  positives; CI installs numpy so the STT stub tests pass.
- Added `.gitattributes` forcing LF for shell scripts. With `core.autocrlf=true`
  (the Git-for-Windows default) they were checked out CRLF, and `bash` inside
  the Docker build failed on `set -o pipefail` — breaking `docker compose
  build` for every Windows one-line install.
- `install.ps1` checks `$LASTEXITCODE` after each `docker compose` step; its
  Docker-missing gate now stops correctly.
- Agent receives `LIVEKIT_URL` (compose), and its `initialize_process_timeout`
  is raised (env-tunable via `AGENT_INIT_TIMEOUT_S`, default 300s) so cold
  warmup can load the model on modest/low-VRAM GPUs.
- GPU doctor CUDA parsing accepts the newer `CUDA UMD Version` header.
- The STT debug window no longer mounts in the main talking UI.

### Docs
- Corrected stale STT 560ms "equals the live step" claims, stale model-tag
  claims in compose/Modelfile/vram-validate, and stale README TLS refs;
  documented phone-background room timeouts.
- Added `caddy:2.11.4` to the provenance Docker Images table; un-ignored the
  LAN-exposure runbook and Windows-AMD field report (the latter kept
  local-only).
- Fixed the proxy bring-up command for the override design; replaced an
  impossible `--profile` example with `COMPOSE_PROFILES`; switched Windows docs
  to `-f` flags instead of colon `COMPOSE_FILE`.
- `security-check` now excludes `docs/**` and allowlists the `savedPersonas`
  key.

## [0.2.0] - 2026-06-30

### Added
- Added browser-local saved personas so custom persona setups can be saved,
  loaded, and deleted from setup or in-session settings.

### Changed
- Reworked setup and live settings around a scenario-first mode/persona flow.
- Updated the product tagline to "Local first fully private voice practice
  with expert personas."

### Fixed
- Guarded live settings updates against stale RPC acknowledgements and
  settings-drawer reopen races.
- Preserved explicit Mock Interview targets while keeping other scenarios
  mapped to the right persona defaults.

## [0.1.0] - 2026-06-30

Rehearsal is now installable with a Linux curl bootstrap, from a local repo
checkout on Linux, and from native Windows, with install-time model selection
and best-effort Windows-AMD support.

### Added
- Added broad voice-practice persona presets across AI/ML, data, software,
  cloud/DevOps, product, sales, customer success, leadership, healthcare
  communication, finance/business, GRC/policy, climate/energy, and language
  conversation practice.
- Added Drill and Roleplay practice modes alongside Learn and Interview.
- `install.sh` / `install.ps1` — two native installers (bash + PowerShell)
  with offer-to-install prerequisites, a model-selection prompt, and
  per-model user-chosen aliases. Aliases are baked into the web build so
  the picker shows only what was installed, named as the user named it.
- `install.sh` curl-style bootstrap — when streamed outside a checkout, it
  clones `foreztgump/rehearsal` into `~/rehearsal` or `REHEARSAL_INSTALL_DIR`
  and then runs the normal local installer.
- `ollama/pull-and-pin.sh` — accepts an `INSTALL_MODELS` set and pulls only
  the selected model ladders; the chosen default is aliased to `OLLAMA_MODEL`.
  Fast/better ladder failures are skip-with-warning (like floor); empty
  `default_tag` falls back to the first installed model.
- `docker-compose.cpu-tts.yml` — CPU Kokoro override
  (`ghcr.io/remsky/kokoro-fastapi-cpu:v0.5.0`) for no-GPU / VRAM-tight hosts.
- `docker-compose.windows-amd.yml` — Windows-AMD override: native host
  Ollama via `host.docker.internal`, in-stack `ollama` reduced to an
  `alpine:3.21` no-op stub (profile-gating fails on `depends_on`), CPU Kokoro.
- `scripts/gpu-doctor.ps1`, `up.ps1`, `down.ps1` — Windows PowerShell
  siblings of the Linux wrappers.
- `agent/models.py` `effective_model_choices()` — derives the picker choice
  set from `REHEARSAL_MODEL_CHOICES`, narrowing `default_model_choice` to the
  installed set. Single installed model renders a read-only field.
- `web/app/ModelPanel.tsx` — choices + labels baked at build time via
  `NEXT_PUBLIC_REHEARSAL_MODEL_CHOICES` / `NEXT_PUBLIC_REHEARSAL_MODEL_LABELS`;
  one model renders as a read-only `<input>`, two-plus as a dropdown.
- `scripts/guarddog-check.sh` — optional GuardDog deep supply-chain scan for
  malicious package signals, with JSON reports under `security/reports/guarddog/`.
- `SECURITY.md` — public reporting policy and the local scan commands.

### Changed
- Renamed the app to Rehearsal, including package metadata, UI copy,
  runtime prefixes, Docker labels/network names, and model-picker env keys.
- Rewrote `README.md` for the public repo with setup, privacy, security checks,
  and project credits.
- Default persona changed to Voice Fluency Coach, with Cybersecurity Trainer
  moved into the preset library.
- `docker-compose.yml` — web service build args pass the baked model
  choice/label env to the Next.js build.
- `web/Dockerfile` now uses `npm ci` and declares the model-picker build args.
- `install.sh` `write_model_env` now runs after `pull-and-pin.sh` succeeds
  (was writing `.env` before tags were confirmed).
- `.gitignore` now excludes local AI/planning workspaces, editor state, caches,
  local env files, and security reports.
- Local security baseline now treats OSV resolver-internal errors with a
  valid zero-vulnerability report as a warning, while still failing on
  malformed reports and high/critical findings.
- Local security scans now use the current Gitleaks `git` command and keep
  GuardDog's package sandbox enabled for npm dependency scans.

### Fixed
- `offer_install_prereqs` sudo failure now falls back to guidance instead
  of a silent `set -e` abort.
- `install.ps1` `Set-EnvKey` hoisted to a top-level function (was scoped
  inside the param block).
- Hardened dependency floors for STT (`h11`, `idna`, `python-multipart`,
  `sentencepiece`) and forced the web lockfile to the fixed `postcss` line
  until Next ships a clean transitive dependency.
- Pinned previously unbounded agent direct dependencies so supply-chain scans do
  not resolve prerelease or dev-package artifacts.

### Notes
- R3 STT decision: `buffered` non-streaming Parakeet is the supported path.
  `streaming` and `hybrid` engines are retained in code as legacy/manual
  comparison modes only.
- Linux curl bootstrap live-tested against a real GitHub clone with Docker/Ollama
  shimmed to avoid multi-GB image and model pulls.
- Operator-deferred (need Windows / `pwsh` / real GPU hardware): PowerShell
  parse checks, Windows NVIDIA Docker GPU probe, Windows AMD native Ollama
  probe. Linux AMD ROCm and Windows AMD profiles are gated on R6 verification.
