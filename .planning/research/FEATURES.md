# Feature Research

**Domain:** Voice-first AI persona trainer — spoken domain fluency + interview practice (Adept)
**Researched:** 2026-06-24
**Confidence:** HIGH

Grounded in named comparables: **Yoodli** (AI speech coach + mock interviews), **Google Interview Warmup** (one-question-at-a-time + ML insights), **Pramp/peer-mock tools**, **Speak / Talkpal / Langua** (voice AI language tutors), and **LiveKit / Inworld / Telnyx** voice-agent platform guidance on latency, barge-in, and turn detection.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Missing any of these and it doesn't feel like a real spoken-practice tool — it feels like a text chatbot with a speaker bolted on.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Full streamed voice loop (mic→STT→LLM→TTS) | The entire product premise — practicing *speaking* out loud | HIGH | Already core. faster-whisper + Gemma E4B + Kokoro behind LiveKit. Stream every stage; start TTS on first completed sentence. |
| Low voice-to-voice latency | Below ~1s feels live; above ~1.5s feels like "speak-and-wait" and kills practice flow (Telnyx/Inworld both cite latency as the make-or-break) | HIGH | Project's headline metric (P50 <1.0s). Drives architecture, not a feature you add later. |
| Barge-in / interruptibility | Humans interrupt; Yoodli/Speak/Langua all let you talk over the agent. Without it conversation feels robotic | MEDIUM | LiveKit handles transport; agent must stop TTS + flush pending audio instantly on user speech onset. |
| Turn detection / endpointing (not fixed timer) | Must not cut in on a thinking pause, must not lag after you finish. LiveKit explicitly frames this as the trigger for the whole pipeline | MEDIUM-HIGH | Semantic/model-based endpointing > VAD-silence-timer. Already chosen. |
| Open-mic VAD input | Natural hands-free turn-taking; PTT breaks immersion for fluency drills | MEDIUM | Decided. VAD gates STT; pairs with turn detection. |
| Visible agent-state indicator (listening/thinking/speaking) | Users need to know whose turn it is, especially open-mic. Universal in voice UIs | LOW | Drive off pipeline events (VAD active, LLM in-flight, TTS playing). |
| Live two-sided transcript | Interview Warmup, Yoodli, Speak all show transcribed text alongside audio so users can review what they said | LOW-MEDIUM | Stream partial + final STT for user; stream LLM tokens for agent. Read-only display. |
| Voice selection | Even table-stakes language tutors offer a voice/character; a credible "expert" needs an appropriate voice | LOW | Kokoro preset voices, per-persona. |
| Session controls (new / reset / end) | Basic lifecycle — start fresh, abandon a bad run | LOW | Tied to ephemeral session + KB clearing. |
| Graceful failure (mic-denied, garbled STT, upload fail) | Voice apps fail in predictable ways; silent failure feels broken | MEDIUM | Mic-permission prompt, "didn't catch that" reprompt, upload-size guard. |

### Differentiators (Competitive Advantage)

Where Adept beats a generic text chatbot or a single-purpose tool. Should map to the Core Value: *sound like a practitioner*.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Editable expert persona (live, in-session) | Most tools are fixed (Yoodli = interviewer, Speak = language tutor). Adept becomes *any* domain expert and you can retune mid-conversation | MEDIUM | System-prompt assembly from role/instructions/name. Apply without dropping the session. The signature flexibility. |
| Behavior knobs (difficulty / verbosity / correction-aggressiveness) | Lets one persona span "gentle coach" → "hostile panel interviewer." Yoodli/Pramp can't dial this | MEDIUM | Prompt parameters injected into system prompt. Cheap to build, high perceived value. |
| Per-session ephemeral knowledge base (upload your docs) | Grounds answers in the user's *own* study notes / employer prep. Yoodli & Interview Warmup can't ingest your material. Privacy-preserving (local + cleared at end) | MEDIUM-HIGH | Inline-and-cache (distill at upload → load once → KV cache), not per-turn RAG — deliberately avoids TTFT inflation. |
| KB distillation to compact domain brief | Setup-time work where latency is invisible; keeps per-turn context lean so latency target holds | MEDIUM | One LLM pass at upload. Trades upload-time cost for runtime speed. |
| Interview Mode (one-question-at-a-time + critique + model answer) | Interview Warmup does one-at-a-time but only surfaces ML "insights" (top words, terms) — **no model answer**. Yoodli gives follow-ups + delivery scoring. Adept's *model answer after critique* is the teaching moment neither nails fully | MEDIUM | Mode = different prompt/state machine: ask → listen → critique → ideal answer → next. Role picked at entry. |
| Learn/Converse mode (open dialogue) | Free-form spoken practice — the Speak/Talkpal "just talk" loop, but domain-expert-flavored | LOW | Default mode; mostly persona prompt + voice loop. |
| Local-first / fully private | Sensitive prep material never leaves the network; no per-token cost enables the *long repetitive practice that builds fluency*. A genuine wedge vs every cloud competitor | HIGH (infra) | Already the architecture. Enables behavior (unlimited practice) competitors can't price-match. |
| Gentle in-conversation terminology correction | The "sound like a practitioner" payoff — agent nudges sloppy terms toward precise ones, in flow | LOW-MEDIUM | Persona-prompt behavior, not a separate subsystem. Tunable via correction-aggressiveness knob. |
| Export/download transcript | Review and self-study after the session (Interview Warmup lets you edit/save answers) | LOW | Serialize the in-memory transcript to file. |

### Delivery Coaching — Differentiator, deferred to v2 (correctly)

This is Yoodli's *entire* core competency (filler words, pacing, clarity, eye contact) — a real differentiator if added, but a separate analysis subsystem.

| Feature | Value | Complexity | Notes |
|---------|-------|------------|-------|
| Filler-word detection (um/uh/like) | Yoodli's headline feature; concrete, motivating signal | MEDIUM | Post-turn or post-session pass over transcript + timing. Needs word-level timestamps from STT. |
| Pacing / words-per-minute | "Too fast / too slow" feedback | LOW-MEDIUM | Compute from STT timestamps. |
| Vagueness / hedging flags | Pushes toward concrete, confident phrasing | MEDIUM-HIGH | LLM analysis pass over transcript. |
| Terminology-usage insights (job-relevant terms used) | Mirrors Interview Warmup's "talking points / job terms detected" insight | MEDIUM | LLM tagging against domain/KB vocabulary. |

Keep out of v1: each needs word-level timestamps and/or an extra analysis pass that competes with the latency budget. Run as **post-session** (not in-loop) when built, so it never touches the live latency path.

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Animated avatar / video face | "Feels more human / engaging" | Huge complexity, lip-sync latency, distracts from voice fluency; competitors (Praktika) add it but it's not what builds *verbal* skill | Voice-first + a clean agent-state indicator. Already out of scope. |
| Multi-user accounts / auth / SaaS | "Share with my team" | Concurrency, auth, tenancy — massive surface for a single-user homelab tool | Single-user, no auth. Out of scope by design. |
| Analytics dashboard / progress graphs | "Track improvement over time" | Requires persistent cross-session storage (conflicts with ephemeral/private design); heavy UI for n=1 | Per-session transcript export. Defer trend-tracking to v2 if ever. |
| True vector RAG (chunk→embed→retrieve) | "Handle big document sets" | Per-turn retrieval inflates TTFT — directly attacks the latency metric the whole design depends on; adds embedder + vector store to VRAM budget | Inline-and-cache distilled brief; reserve RAG only for oversized KBs in v2+. |
| Persistent cross-session memory / profiles | "Remember me, build on past sessions" | Privacy risk (sensitive material persisted) + state complexity | Ephemeral per-session. Out of scope. |
| Saved persona library | "Switch between my saved experts" | Storage + management UI before the core loop is proven | Single default + live editing in v1; named library is v2. |
| Numeric interview scoring / rubric | "Give me a score like the real competitors" | Encourages gaming a number; precise/fair scoring is hard and can mislead; pulls focus from *fluency* | Qualitative critique + model answer (more instructive). Add rubric later if validated. |
| Push-to-talk | "Cleaner audio / more control" | Breaks the natural, hands-free feel that's the core value | Open-mic VAD. Decided against. |
| Real-time in-loop delivery coaching | "Yoodli does it live" | Extra inference on the hot path blows the latency budget | Post-session analysis pass in v2. |

---

## Feature Dependencies

```
Streamed voice loop (STT→LLM→TTS)
    ├──requires──> Low-latency streaming (first-sentence TTS, resident models)
    ├──requires──> Turn detection / endpointing
    │                   └──requires──> VAD (open-mic input)
    ├──enables───> Barge-in (stop TTS on user speech onset)
    ├──enables───> Agent-state indicator (listening/thinking/speaking)
    └──enables───> Live transcript ──enables──> Export transcript
                                    └──enables──> Delivery coaching (v2, post-session)

Persona system (default Cybersecurity Trainer)
    ├──enables───> Persona editor (role/name/instructions)
    ├──enables───> Behavior knobs (difficulty/verbosity/correction)
    ├──enables───> Voice selection (per persona)
    ├──enables───> Terminology correction (prompt behavior)
    └──enables───> Interview Mode (persona + state machine)

Knowledge base upload
    ├──requires──> KB distillation (compact brief at upload)
    ├──requires──> Inline-and-cache loading (KV/prefix cache, no per-turn RAG)
    ├──requires──> Ephemeral session lifecycle (clear at end)
    └──needs─────> Upload guard + KB-active indicator

Delivery coaching (v2)
    └──requires──> Word-level STT timestamps + live transcript + post-session pass

History management (sliding window / summarize)
    └──protects──> Low-latency target (stops growing context inflating TTFT)
```

### Dependency Notes

- **Turn detection requires VAD:** VAD gates when audio is speech; endpointing decides when the *turn* is over. Open-mic mode makes both mandatory and tightly coupled.
- **Barge-in depends on the streamed loop + state tracking:** the agent must know it's currently speaking and be able to interrupt its own TTS the instant user speech is detected.
- **Interview Mode depends on persona + a state machine:** it's not a new pipeline, it's a constrained dialogue flow (ask→listen→critique→model-answer→next) layered on the same voice loop.
- **KB inline-and-cache conflicts with per-turn RAG:** they're mutually exclusive strategies; RAG would reintroduce the per-turn latency the cache strategy exists to avoid.
- **Delivery coaching depends on word-level timestamps:** filler-word and pacing analysis need them from STT; confirm faster-whisper config exposes them before committing to v2 scope.
- **History management protects the latency target:** not a user-facing feature, but a dependency of sustaining P50 <1.0s across a long session.
- **Export depends on the live transcript** already being captured in memory.

---

## MVP Definition

### Launch With (v1)

Hard MVP gate (per PROJECT.md): ship the bare voice loop with the default persona before anything else.

- [ ] Streamed voice loop (STT→LLM→TTS) — the product
- [ ] Low voice-to-voice latency (P50 <1.0s) — the core value, instrument from day one
- [ ] Barge-in — without it conversation feels robotic
- [ ] Turn detection / endpointing + open-mic VAD — natural turn-taking
- [ ] Agent-state indicator — users must know whose turn it is
- [ ] Live two-sided transcript — review what you said
- [ ] Default Cybersecurity Trainer persona — credible expert out of the box
- [ ] Persona editor + behavior knobs — the signature flexibility
- [ ] Voice selection — credible expert voice
- [ ] Ephemeral KB upload + distillation + inline-cache + active indicator/guard — grounded answers
- [ ] Learn/Converse mode — default open practice
- [ ] Interview Mode (one-at-a-time + critique + model answer) — the interview-confidence payoff
- [ ] Session controls + transcript export — lifecycle + review
- [ ] Graceful failure handling — mic, STT, upload
- [ ] History management — protects latency over a long session

### Add After Validation (v1.x)

- [ ] Post-session delivery coaching: filler words + pacing — trigger: core loop solid and STT timestamps confirmed
- [ ] Terminology-usage insights (Interview Warmup-style) — trigger: users want "did I sound like a practitioner" signal
- [ ] Swappable/cloned trainer voice (VoxCPM) — trigger: Kokoro voices feel generic; interface already supports it
- [ ] Larger model option (Gemma 26B-A4B / Qwen3 8B) on 24GB — trigger: quality gap on hard domains

### Future Consideration (v2+)

- [ ] Vagueness/hedging flags — defer: needs an analysis pass; validate demand first
- [ ] Saved persona library — defer: storage + UI; live editing covers v1
- [ ] Persistent/named KB collections — defer: conflicts with privacy/ephemeral stance
- [ ] True vector RAG for oversized KBs — defer: only when KBs exceed what inline-cache handles
- [ ] Interview scoring rubric — defer: only if qualitative critique proves insufficient

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Streamed voice loop | HIGH | HIGH | P1 |
| Low latency (<1s) | HIGH | HIGH | P1 |
| Barge-in | HIGH | MEDIUM | P1 |
| Turn detection + VAD | HIGH | MEDIUM-HIGH | P1 |
| Agent-state indicator | MEDIUM | LOW | P1 |
| Live transcript | MEDIUM | LOW-MEDIUM | P1 |
| Default persona | HIGH | LOW | P1 |
| Persona editor + knobs | HIGH | MEDIUM | P1 |
| Voice selection | MEDIUM | LOW | P1 |
| Ephemeral KB (distill+cache) | HIGH | MEDIUM-HIGH | P1 |
| Learn/Converse mode | HIGH | LOW | P1 |
| Interview Mode | HIGH | MEDIUM | P1 |
| Session controls + export | MEDIUM | LOW | P1 |
| Graceful failure handling | MEDIUM | MEDIUM | P1 |
| History management | HIGH (latency) | MEDIUM | P1 |
| Delivery coaching (post-session) | HIGH | MEDIUM | P2 |
| Terminology insights | MEDIUM | MEDIUM | P2 |
| Cloned trainer voice | MEDIUM | LOW-MEDIUM | P2 |
| Vagueness flags | MEDIUM | MEDIUM-HIGH | P3 |
| Saved persona library | MEDIUM | MEDIUM | P3 |
| Vector RAG | LOW (v1) | HIGH | P3 |
| Scoring rubric | LOW | MEDIUM | P3 |

---

## Competitor Feature Analysis

| Feature | Yoodli | Google Interview Warmup | Speak / Talkpal / Langua | Our Approach (Adept) |
|---------|--------|------------------------|--------------------------|----------------------|
| Real-time spoken dialogue | Yes (AI interviewer w/ follow-ups) | No — record answer, then analyze | Yes (voice chat / call mode) | Yes — streamed, sub-1s, barge-in |
| Barge-in / interrupt | Limited | N/A (not conversational) | Yes | Yes — instant TTS stop |
| One-question-at-a-time interview | Yes | Yes | Roleplay modes | Interview Mode |
| Model / ideal answer | No (delivery focus) | No (insights only) | Corrections, not full model answers | **Yes — critique + model answer** (gap others miss) |
| Delivery coaching (fillers/pacing) | **Yes — core strength** | Partial (top words, terms) | Pronunciation/fluency feedback | v2 post-session (deliberately deferred) |
| Editable expert persona | No (fixed roles) | No (fixed paths) | Tutor characters, not editable domain experts | **Yes — live-editable any-domain persona** |
| Upload your own docs as grounding | No | No | No | **Yes — ephemeral per-session KB** |
| Configurable difficulty/style knobs | Limited | No | Level-based | **Yes — explicit behavior knobs** |
| Transcript + export | Yes | Yes (edit/save answers) | Yes | Yes |
| Local / private / unlimited | No (cloud, paid tiers) | No (cloud) | No (cloud, paid) | **Yes — fully local, no per-token cost** |

**Net differentiation:** Adept fuses *Speak's* live spoken-dialogue feel + *Interview Warmup's* one-at-a-time structure + a **model answer** (which neither gives) + **editable persona** and **your-own-docs grounding** and **local privacy/unlimited practice** (which none give). Yoodli's delivery coaching is the one area where a named competitor is clearly ahead — correctly scoped as v2.

---

## Sources

- Yoodli — AI speech coach + mock interview (real-time follow-up Qs, filler/pacing/clarity feedback): yoodli.ai, GeekWire launch coverage, third-party reviews (Articuler, Mockly, Leadr)
- Google Interview Warmup — one-question-at-a-time, ML transcription, insights (top words / talking points / job-related terms; no model answer): blog.google, grow.google, InterviewChamp comparison
- Pramp-style peer mocks — referenced via Interview Warmup alternatives comparison (free peer practice, follow-ups, scoring gaps)
- Voice AI language tutors — Speak (speak-out-loud philosophy, instant feedback), Talkpal (voice chat / call / roleplay / debate modes), Langua (human-like, cloned voices)
- Voice-agent platform guidance — LiveKit (turn detection: VAD vs endpointing vs model-based), Telnyx & Inworld (latency budgets, barge-in as make-or-break)
- Project context — .planning/PROJECT.md (Adept stack, latency target, KB inline-cache decision, scope boundaries)

---
*Feature research for: voice-first AI persona trainer (spoken fluency + interview practice)*
*Researched: 2026-06-24*
