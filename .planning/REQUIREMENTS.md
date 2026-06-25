# Requirements: Adept — Near-Real-Time Voice Persona Trainer

**Defined:** 2026-06-24
**Core Value:** The user can hold a natural spoken conversation with a credible expert persona at voice-to-voice latency that feels live (P50 < 1.0s) — practicing speaking a domain out loud.

## v1 Requirements

Requirements for the first complete release. Each maps to roadmap phases.

### Conversation Core

- [ ] **VOICE-01**: User can speak into the mic and hear a spoken response from the agent (full streamed mic → STT → LLM → TTS loop)
- [ ] **VOICE-02**: Agent begins speaking on the first completed sentence of its response (sentence-chunked TTS streaming), not after the full response is generated
- [ ] **VOICE-03**: Agent stops speaking instantly when the user starts talking (barge-in)
- [ ] **VOICE-04**: Agent waits for the user to finish a thought before responding, using semantic endpointing (not a fixed silence timer), so it does not cut in on pauses
- [ ] **VOICE-05**: User talks hands-free via open-mic VAD (no push-to-talk)
- [ ] **VOICE-06**: User sees a visible agent-state indicator showing listening / thinking / speaking
- [ ] **VOICE-07**: User sees a live two-sided transcript of both their speech and the agent's response as the conversation happens
- [ ] **VOICE-08**: Voice-to-voice latency is instrumented per-turn (via LiveKit per-turn metrics) and visible for tuning

### Persona

- [ ] **PERS-01**: A default Cybersecurity Trainer persona is available immediately on load (no setup required to start talking)
- [ ] **PERS-02**: User can edit the persona's role and system instructions in a side panel
- [ ] **PERS-03**: User can edit the persona's display name
- [ ] **PERS-04**: User can adjust behavior knobs — difficulty, verbosity, correction-aggressiveness
- [ ] **PERS-05**: User can select the persona's voice from Kokoro preset voices
- [ ] **PERS-06**: Persona changes (role, instructions, knobs, voice) apply within the current session without a restart
- [ ] **PERS-07**: The default trainer gently corrects sloppy terminology toward precise practitioner phrasing (tuned by the correction-aggressiveness knob)

### Knowledge Base

- [ ] **KB-01**: User can upload documents (PDF, TXT, MD, DOCX) at session start
- [ ] **KB-02**: Uploaded documents are parsed and distilled into a compact domain brief at upload time
- [ ] **KB-03**: The domain brief is loaded into the session context once and held in the model's prefix/KV cache (no per-turn retrieval)
- [ ] **KB-04**: With a KB loaded, the agent's answers demonstrably reference the user's material; with no KB, they do not
- [ ] **KB-05**: Per-turn time-to-first-token stays flat whether or not a KB is loaded (the flat-TTFT invariant — KB cost is paid once at session start)
- [ ] **KB-06**: KB is ephemeral — cleared at session end (privacy + simplicity)
- [ ] **KB-07**: User sees an indicator showing the KB is active and how many docs are loaded
- [ ] **KB-08**: An upload-size guard warns or distills more aggressively when an upload is large enough to bloat the cached prefix / KV-cache VRAM

### Modes

- [ ] **MODE-01**: Learn/Converse mode is the default — open conversation where the trainer explains, quizzes informally, and pushes the user to articulate
- [ ] **MODE-02**: User can toggle into Interview Mode from the side panel
- [ ] **MODE-03**: On entering Interview Mode, the user picks the target role (e.g., SOC analyst, security engineer, GRC)
- [ ] **MODE-04**: In Interview Mode the agent asks one realistic, role-relevant question at a time and waits for the user's spoken answer
- [ ] **MODE-05**: After each answer the agent gives feedback (critique) and demonstrates a strong model answer

### Session

- [ ] **SESS-01**: User can start a new session
- [ ] **SESS-02**: User can reset the current session
- [ ] **SESS-03**: User can end the session (clearing ephemeral state including the KB)
- [ ] **SESS-04**: User can export/download the session transcript
- [ ] **SESS-05**: Conversation history is managed (sliding window / summarization) so per-turn TTFT stays flat as the session grows

### Reliability

- [ ] **REL-01**: When mic permission is denied, the user sees a clear prompt explaining how to grant it (not a silent failure)
- [ ] **REL-02**: When transcription is empty or garbled, the agent reprompts ("didn't catch that") rather than responding to noise
- [ ] **REL-03**: When a KB upload fails (parse error, oversize), the user sees a clear error and the session continues without the KB

### Performance & Deployment

- [ ] **PERF-01**: Voice-to-voice latency meets P50 < 1.0s and P95 < 1.5s on the target hardware
- [ ] **PERF-02**: The full stack runs within the 16GB VRAM floor (STT + LLM + TTS co-resident, no embedder or vector store)
- [ ] **PERF-03**: All inference runs locally — no audio, transcripts, or KB content leaves the local network
- [ ] **DEPLOY-01**: The entire system (LiveKit server, agent worker, Ollama, Whisper, Kokoro, web frontend) comes up from a single Docker Compose stack with GPU passthrough
- [ ] **DEPLOY-02**: LiveKit is self-hosted (no dependency on LiveKit Cloud) including the local turn-detection model
- [ ] **DEPLOY-03**: A user can load the single-page UI and start talking to the default trainer within seconds, with configuration optional and tucked to the side

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Delivery Coaching

- **COACH-01**: Post-session filler-word detection (um/uh/like) over the transcript
- **COACH-02**: Post-session pacing / words-per-minute feedback
- **COACH-03**: Post-session terminology-usage insights (which job-relevant terms the user used)
- **COACH-04**: Vagueness / hedging flags with sharper-phrasing suggestions

### Scaling & Persistence

- **SCALE-01**: True vector RAG (chunk → embed → retrieve) auto-selected for KBs too large to fit context
- **SCALE-02**: Saved persona library — multiple named personas the user can switch between
- **SCALE-03**: Persistent / named KB collections reusable across sessions
- **SCALE-04**: Larger model option (Gemma 26B-A4B MoE / Qwen3 8B) on 24GB hardware
- **SCALE-05**: Swappable / cloned custom trainer voice (e.g., VoxCPM) via the OpenAI-compatible TTS interface

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Push-to-talk input | Decided against — open-mic VAD is core to the natural, hands-free feel |
| Per-turn vector RAG in v1 | Inflates per-turn TTFT — directly attacks the latency metric the design depends on; inline-and-cache covers small KBs |
| Persistent cross-session memory / user profiles | Privacy risk + state complexity; ephemeral per-session by design |
| Multi-user accounts / auth / SaaS multi-tenancy | Single-user homelab tool; concurrency is a future scaling problem |
| Telephony / phone calls | Web/mic only |
| Native mobile app | Web-first |
| Avatars / video | Voice-first only; lip-sync latency distracts from verbal fluency |
| Analytics dashboards / progress graphs | Requires persistent storage (conflicts with ephemeral design); heavy UI for single user |
| Model fine-tuning / training | Prompt-engineer the personas instead |
| Numeric interview scoring rubric | Encourages gaming a number; qualitative critique + model answer is more instructive |
| In-loop (live) delivery coaching | Extra inference on the hot path blows the latency budget; v2 post-session pass instead |
| Payments / billing | Not monetized |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| (populated during roadmap creation) | | |

**Coverage:**
- v1 requirements: 35 total
- Mapped to phases: 0 (pending roadmap)
- Unmapped: 35 ⚠️

---
*Requirements defined: 2026-06-24*
*Last updated: 2026-06-24 after initial definition*
