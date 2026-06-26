"""Adept LiveKit agent worker — AgentSession wiring + walking-skeleton gate.

Phase 1 scope (Plan 01-03): construct an AgentSession against the three LOCAL
model endpoints (Nemotron streaming STT, Ollama LLM, Kokoro TTS) with the LOCAL
MultilingualModel turn detector, run a startup warmup that emits exactly ONE
real LLM-TTFT metric line through the scaffold, and register as a worker against
the self-hosted livekit-server. NO live voice turn happens yet — no participant
audio flows in Phase 1.

Local-first invariant (PERF-03 / DEPLOY-02): every model base_url is an in-stack
service on the `adept` Docker network; the turn detector is the local
MultilingualModel, never the cloud-default turn detector plugin. Nothing reaches
a non-LAN endpoint at startup.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field

import httpx
from livekit.agents import Agent, AgentSession, JobContext, JobProcess, WorkerOptions, cli
from livekit.plugins import openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

import history
import interview
import metrics
from nemo_stt import NemoSTT
from kb import KB_AGGREGATE_MAX_TOKENS, DistillError, KbParseError, ParsedDoc
from kb import distill as kb_distill
from kb import parse as kb_parse
from persona import (
    CORRECTION,
    DEFAULT_PERSONA,
    DIFFICULTY,
    KB_CITE_NUDGE,
    Persona,
    VERBOSITY,
    VOICE_IDS,
    render_prompt,
)

logger = logging.getLogger("adept.agent")

# In-stack model endpoints (Docker `adept` network — all LAN-local, no egress).
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434/v1")
OLLAMA_GENERATE_URL = os.environ.get("OLLAMA_GENERATE_URL", "http://ollama:11434/api/generate")
# NemoSTT websocket endpoint — a `ws://` URL (NOT `http://.../v1`), matching the
# Wave-1 (09-01) server route on the `nemo-stt` service. The STT model itself is
# single-sourced server-side via STT_MODEL (no model tag in agent code).
NEMO_STT_URL = os.environ.get("NEMO_STT_URL", "ws://nemo-stt:8000/v1/audio/stream")
KOKORO_BASE_URL = os.environ.get("KOKORO_BASE_URL", "http://kokoro:8880/v1")

# Use "tts-1" (not "kokoro"): the livekit openai TTS plugin only routes tts-1 /
# tts-1-hd through the plain audio-stream path. Any other model name takes the
# SSE path (stream_format="sse"), which kokoro-fastapi ignores — it returns raw
# audio/mpeg instead of SSE deltas, so zero frames are pushed ("no audio frames
# were pushed"). kokoro selects the voice via the `voice` param, not the model.
KOKORO_MODEL = "tts-1"

WARMUP_PROMPT = "Reply with the single word: ready."
WARMUP_TIMEOUT_SECONDS = 120.0
WARMUP_NUM_PREDICT = 16
THINKING_ENABLED = False  # protect TTFT (see ollama/Modelfile)
_MS_PER_SECOND = 1000.0

# --- Endpointing profiles (Plan 06-02, MODE-05) -------------------------------
# Two named endpointing profiles, no magic values (AGENTS.md). The CONVERSATIONAL
# profile (min_delay 0.3 / max_delay 3.0) is today's Learn/Converse floor — see the
# turn_handling dict in build_session. The INTERVIEW profile raises the floor so a
# deliberate, pause-heavy answer ("let me think… the answer is…") is NOT read as
# turn-end and cut mid-thought; MultilingualModel() stays the semantic decider, this
# only widens the silence tolerance around it (RESEARCH §5).
CONVERSATIONAL_ENDPOINTING_MIN_DELAY: float = 0.3
CONVERSATIONAL_ENDPOINTING_MAX_DELAY: float = 3.0
# Interview floor: min ∈ [0.6, 0.8] (wait longer before committing a turn),
# max ∈ [5.0, 6.0] (allow a longer final pause before forcing turn-end).
INTERVIEW_ENDPOINTING_MIN_DELAY: float = 0.7
INTERVIEW_ENDPOINTING_MAX_DELAY: float = 5.0
# METRICS INTERPRETATION (RESEARCH §2.4 / §7.7): the raised interview min_delay (0.7s)
# INTENTIONALLY exceeds metrics.BUDGET_MS["eou"]=300 (agent/metrics.py:31), so interview
# turns flag over_budget:["eou"]. This is EXPECTED and correct for deliberate-answer
# speech, NOT a regression — do not "fix" it. agent/metrics.py is READ-ONLY here.
#
# [VM-INTROSPECT] HOW TO SWITCH PROFILES — UNRESOLVED, three ordered candidates; NO
# runtime `turn_handling` setter is assumed (this codebase has never proven one):
#   (1) Per-Agent override (cleanest): if the installed livekit-agents Agent.__init__
#       accepts min_endpointing_delay / max_endpointing_delay / turn_detection, an
#       interview-profiled Agent carries the slow floor by construction. Because
#       Option B (06-01) keeps ONE agent (no separate InterviewAgent), this has no
#       clean carrier unless the VM probe says otherwise.
#   (2) Runtime mutation via session.update_options(...) on mode-enter — memory note
#       suggests NO such runtime setter exists; UNCONFIRMED.
#   (3) MVP-SAFE FALLBACK (the realistic landing): carry both profiles as named
#       constants and select the interview floor as the session endpointing profile
#       at build_session when interview-leaning, OR document mode-before-start. We
#       apply the interview floor as the SINGLE session profile below (mechanism 3):
#       a deliberate-answer floor that also serves Learn turns acceptably (slightly
#       slower conversational commit), avoiding an unproven runtime setter.
# The chosen mechanism is FINALIZED against the inspect.signature probe in
# 06-INTERVIEW-VERIFY.md (06-02-3). Until that probe confirms mechanism 1 or 2, the
# single-profile fallback ships.
ENDPOINTING_MIN_DELAY: float = INTERVIEW_ENDPOINTING_MIN_DELAY
ENDPOINTING_MAX_DELAY: float = INTERVIEW_ENDPOINTING_MAX_DELAY

# Default persona (PERS-01) now lives in agent/persona.py as a structured config:
# DEFAULT_PERSONA renders (via render_persona) to a byte-stable system prompt with
# the frozen prefix layout ([persona] + [KB] + [history] + [turn]) so Phase 4 can
# slot a KB beneath it without a rewrite. Voice-friendly: concise and conversational
# because TTS speaks it aloud.


def resolved_llm_tag() -> str:
    """Read the pinned LLM tag from OLLAMA_MODEL (no hardcoded gemma tag)."""
    tag = os.environ.get("OLLAMA_MODEL", "").strip()
    if not tag:
        raise SystemExit("OLLAMA_MODEL is not set — run ollama/pull-and-pin.sh first")
    return tag


# --- LLM Speed Selector (Phase 8, LLM-01..LLM-04) -----------------------------
# Two user-selectable response models exposed via plain-language OUTCOME labels in
# the UI ("Fast (snappier)" / "Better (more thoughtful)"). The agent only ever sees
# the validated plain choice key here — NEVER a raw Ollama tag from the client
# (LLM-01). Fast is the configurable default (LLM-02). No hardcoded gemma tag: each
# choice resolves to its own env var (the v1.0 no-hardcoded-tag invariant,
# generalized from resolved_llm_tag above).
MODEL_CHOICES = ("fast", "better")
DEFAULT_MODEL_CHOICE = "fast"
_MODEL_ENV = {"fast": "OLLAMA_MODEL_FAST", "better": "OLLAMA_MODEL_BETTER"}

# Live hot-path generation cap (LLM-04 "capped num_predict"). Sized to the
# SPOKEN_STYLE_FOOTER "a sentence or two at a time" budget (persona.py:71) — it
# bounds runaway generation uniformly on BOTH models.
#
# WIRE FORMAT (Phase-8 Gate C finding, Ollama 0.30.10): Ollama's OpenAI-compat
# /v1/chat endpoint honors the top-level `max_tokens` field and IGNORES
# `max_completion_tokens`. The earlier code set `_opts.max_completion_tokens`,
# which the plugin faithfully forwards — but Ollama drops it, so the cap was a
# silent NO-OP (a verbose model ran to 1892 tokens on a "count to 500" probe).
# The fix sets `_opts.extra_body = {"max_tokens": CAP}`; the plugin forwards
# extra_body verbatim into the request body, landing the cap where Ollama reads it.
LIVE_NUM_PREDICT_CAP: int = 256


def resolved_model_tag(choice: str) -> str:
    """Resolve a Fast/Better picker choice to its pinned Ollama tag from env.

    Mirrors resolved_llm_tag's SystemExit-if-unset posture — no hardcoded tag.
    """
    env_var = _MODEL_ENV[choice]
    tag = os.environ.get(env_var, "").strip()
    if not tag:
        raise SystemExit(f"{env_var} is not set — run ollama/pull-and-pin.sh first")
    return tag


def _warmup_llm_ttft_ms(tag: str) -> float:
    """Stream one tiny completion from Ollama; return measured TTFT in ms.

    Mirrors ollama/warmup.py's LLM path: forces the model resident and measures
    first-token latency — the real number routed through the metrics scaffold as
    the walking-skeleton "one real metric" gate.
    """
    payload = {
        "model": tag,
        "prompt": WARMUP_PROMPT,
        "stream": True,
        "think": THINKING_ENABLED,
        "options": {"num_predict": WARMUP_NUM_PREDICT},
    }
    started = time.perf_counter()
    ttft_seconds: float | None = None
    with httpx.Client(timeout=WARMUP_TIMEOUT_SECONDS) as client:
        with client.stream("POST", OLLAMA_GENERATE_URL, json=payload) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if chunk.get("response") and ttft_seconds is None:
                    ttft_seconds = time.perf_counter() - started
                if chunk.get("done"):
                    break
    if ttft_seconds is None:
        raise RuntimeError("LLM produced no tokens — warmup failed")
    return round(ttft_seconds * _MS_PER_SECOND, 1)


def build_session(vad: silero.vad.VAD) -> AgentSession:
    """Construct the AgentSession against the three local endpoints + local turn
    detector. Used by the entrypoint; metrics are attached per-plugin after.
    """
    return AgentSession(
        vad=vad,
        stt=NemoSTT(ws_url=NEMO_STT_URL, language="en"),
        # Thinking-OFF on the hot path (a <think> preamble destroys TTFT and
        # breaks first-sentence TTS). with_ollama connects over Ollama's
        # OpenAI-compat /v1 endpoint, which IGNORES the native `think` field but
        # DOES honor `reasoning_effort` — Ollama maps "none" to its internal
        # Think=false (see Ollama OpenAI-compatibility docs). with_ollama exposes
        # `reasoning_effort` directly (livekit-plugins-openai reference), so this
        # forwards think-off over /v1 WITHOUT a Modelfile change or repointing the
        # model. The tag now resolves to the Fast default (LLM-02) via
        # resolved_model_tag(DEFAULT_MODEL_CHOICE); handle_model_update swaps it in
        # place per session. The num_predict cap is NOT set here (build_session
        # returns the AgentSession inline — there is no handle to session.llm
        # before the return); it is pinned to the single entrypoint site after
        # metrics.attach (LLM-04).
        llm=openai.LLM.with_ollama(
            model=resolved_model_tag(DEFAULT_MODEL_CHOICE),
            base_url=OLLAMA_BASE_URL,
            reasoning_effort="none",
        ),
        tts=openai.TTS(
            base_url=KOKORO_BASE_URL,
            model=KOKORO_MODEL,
            voice=DEFAULT_PERSONA.voice_id,
            api_key="none",
        ),
        # Endpointing surface (Plan 02-03 BLOCKER — resolved by reading the real
        # AgentSession source across the whole ~=1.5 pin, NOT by guessing).
        # Verified against livekit-agents@1.5.0, @1.5.17 and @1.6.4
        # (voice/agent_session.py + voice/turn.py): the TWO surfaces are NOT
        # mutually exclusive and the direct kwargs do NOT throw TypeError —
        #   * direct kwargs (min_endpointing_delay=..., min_interruption_duration=...)
        #     are present but DEPRECATED; __init__ migrates them via
        #     _migrate_turn_handling() into the dict below.
        #   * turn_handling=TurnHandlingOptions(...) (a TypedDict, passable as a
        #     plain dict) is the NON-deprecated consolidated surface and is the
        #     ONLY one that exposes `mode: "dynamic"` endpointing.
        # We use the dict surface (future-proof under ~=1.5 resolving to 1.6.x;
        # dynamic mode preferred per Pattern D1). The MultilingualModel turn
        # detector is the semantic decider and MUST live INSIDE the dict —
        # when turn_handling is given, the deprecated top-level turn_detection
        # kwarg is dropped (else-branch in __init__), so nesting it is required.
        # endpointing min_delay/max_delay are the named profile constants above. As of
        # Plan 06-02 (MODE-05) the SINGLE session profile is the INTERVIEW floor
        # (ENDPOINTING_MIN_DELAY/MAX_DELAY = the deliberate-answer profile) — the
        # mechanism-3 fallback, because Option B keeps one agent and no runtime
        # turn_handling setter is assumed ([VM-INTROSPECT] block above). The raised
        # min_delay intentionally exceeds metrics.BUDGET_MS["eou"]=300 so interview
        # turns flag over_budget:["eou"] — EXPECTED, not a regression.
        # VM-introspection-pending: confirm the installed signature with
        #   python -c "import inspect, livekit.agents as a; print(inspect.signature(a.AgentSession.__init__))"
        # (sandbox cannot import livekit — grounded on tagged source instead).
        # Barge-in / interruption gate (Plan 02-03-2). Barge-in is built in:
        # AgentSession cancels TTS + rolls back the turn on user speech and
        # `interruption.enabled` defaults True (verified in voice/turn.py
        # _INTERRUPTION_DEFAULTS) — we DO NOT disable it (allow_interruptions
        # stays on). On the dict surface the deprecated direct kwargs map as:
        #   min_interruption_duration   -> interruption["min_duration"]
        #   false_interruption_timeout  -> interruption["false_interruption_timeout"]
        #   resume_false_interruption   -> interruption["resume_false_interruption"]
        # All three keys are verified present on InterruptionOptions across
        # livekit-agents@1.5.0..@1.6.4 (voice/turn.py). min_duration 0.3s
        # requires ~300ms of real speech before cancel — defends against the
        # agent's own echo tail and "mm-hmm" backchannels. resume_false_int +
        # a 2.0s timeout make a no-transcript noise-blip barge-in resume the
        # agent instead of dropping the turn (open-mic win).
        # VM-introspection-pending: confirm the installed InterruptionOptions
        # accepts these keys (sandbox cannot import livekit — grounded on tagged
        # source). If a future version renames a key, the dict degrades by
        # ignoring unknown keys at _resolve_interruption (TypedDict, total=False).
        turn_handling={
            "turn_detection": MultilingualModel(),
            "endpointing": {
                "mode": "dynamic",
                "min_delay": ENDPOINTING_MIN_DELAY,
                "max_delay": ENDPOINTING_MAX_DELAY,
            },
            "interruption": {
                "min_duration": 0.3,
                "resume_false_interruption": True,
                "false_interruption_timeout": 2.0,
            },
        },
    )


def prewarm(proc: JobProcess) -> None:
    """Worker-startup hook: load VAD and emit the one real warmup metric line.

    Runs once when the worker process boots — before any job/voice turn — so the
    walking-skeleton gate (exactly one real llm_ttft_ms line) is satisfied at
    startup without a participant. The VAD is cached for reuse in the entrypoint.
    """
    # Raise Silero VAD activation_threshold 0.5 -> 0.65 (Plan 02-03-2, Pitfall 4):
    # a higher bar to register speech reduces open-mic false triggers from the
    # agent's own playout + room noise. `activation_threshold` is verified
    # present on silero.VAD.load (livekit-plugins-silero vad.py: default 0.5,
    # alongside min_speech_duration/min_silence_duration/deactivation_threshold).
    # VM-introspection-pending: confirm the installed silero.VAD.load signature
    #   python -c "import inspect; from livekit.plugins import silero; print(inspect.signature(silero.VAD.load))"
    # (sandbox cannot import livekit — grounded on tagged source).
    proc.userdata["vad"] = silero.VAD.load(activation_threshold=0.65)
    ttft_ms = _warmup_llm_ttft_ms(resolved_llm_tag())
    metrics.emit_warmup_metric(ttft_ms)


GREETING_INSTRUCTIONS = (
    "Greet the user as the Cybersecurity Trainer and invite them to begin."
)

# Browser → agent transport contract (Plan 04-01): the file picker uploads each
# file as its own byte stream on this topic; the agent publishes ingest status
# back on the `kb.state` participant attribute (the read pattern AgentStatePill
# uses for `lk.agent.state`).
KB_UPLOAD_TOPIC = "kb.upload"
KB_STATE_ATTRIBUTE = "kb.state"


@dataclass
class _SessionKb:
    """In-memory, per-session KB state (KB-06 ephemeral — no disk/db).

    Holds ONLY the parsed docs + the distilled brief for the life of the job; it
    drops when the job ends. `brief` is the distilled, injected-once string that
    lands in the frozen KB_SLOT (04-02) — set once, never re-distilled per turn.
    """

    docs: list[ParsedDoc] = field(default_factory=list)
    brief: str = ""


def _concat_docs(docs: list[ParsedDoc]) -> str:
    """Deterministic join of the parsed docs' text for the distill pass.

    A fixed `"\n\n"` separator and no volatile data, so the distill INPUT is stable
    for a given set of uploads (the distill OUTPUT lands in the frozen prefix).
    """
    return "\n\n".join(d.text for d in docs)


class HistoryWindowAgent(Agent):
    """Cap the conversation history ITEM list each turn so per-turn prefill stays
    bounded (flat TTFT over a long session, Pitfall 10) WITHOUT touching the frozen
    persona+KB prefix carried in ``instructions``.

    ``on_user_turn_completed`` runs just before the LLM reply: a cheap SYNCHRONOUS
    window-trim that keeps the last ``window_target()`` message items and drops the
    OLDEST (cut from the FRONT — the cache-safe edge; never rewrite the middle). It
    NEVER calls ``update_instructions`` — ``truncate`` preserves system instructions
    by design, so the cached persona+KB prefix is untouched (Criterion 3, the §2
    rule). The trim is persisted via ``update_chat_ctx`` so the window holds ACROSS
    turns (a temporary ``turn_ctx`` edit would not persist).
    """

    async def on_user_turn_completed(self, turn_ctx, new_message):
        if history.should_trim(len(self.chat_ctx.items)):
            trimmed = self.chat_ctx.copy().truncate(max_items=history.window_target())
            await self.update_chat_ctx(trimmed)


async def entrypoint(ctx: JobContext) -> None:
    """Per-job entrypoint: connect, build the session, drive the agent's first turn.

    After session.start(...) the agent speaks first (the greeting call below) so
    the learner immediately has a partner (PERS-01 "talking within seconds"). The
    greeting instruction drives the full LLM->TTS path — no second hardcoded
    greeting string. Per-turn replies after this need no manual glue: with VAD +
    turn detector + STT + LLM + TTS all wired, AgentSession runs a turn
    automatically when the user finishes speaking.
    """
    await ctx.connect()
    session = build_session(ctx.proc.userdata["vad"])
    metrics.attach(session)
    # Live generation cap (LLM-04) — the SINGLE site it is set, applied exactly
    # once at startup. with_ollama does NOT accept the cap, so the live hot-path LLM
    # otherwise caps NOTHING (only warmup/distill cap num_predict off the hot path).
    # Set it here, where session.llm is reachable, to close that pre-existing gap.
    # MUST go through extra_body's `max_tokens`, NOT `max_completion_tokens`: Ollama
    # 0.30's /v1 ignores the latter (Phase-8 Gate C finding) — the plugin forwards
    # extra_body verbatim, so this lands the cap where Ollama actually reads it.
    # Applies equally to BOTH models and survives the in-place _opts.model swap
    # (extra_body lives in the same _opts the swap mutates only .model on).
    session.llm._opts.extra_body = {"max_tokens": LIVE_NUM_PREDICT_CAP}
    # Named local ref (was inline): 03-02's RPC handler will close over `agent` to
    # hot-swap the persona via agent.update_instructions(...) without a restart.
    # render_prompt(DEFAULT_PERSONA, "") is byte-identical to the old
    # render_persona(DEFAULT_PERSONA) golden (the empty-KB seam).
    agent = HistoryWindowAgent(instructions=render_prompt(DEFAULT_PERSONA, ""))
    await session.start(agent=agent, room=ctx.room)

    # Track the CURRENT persona so the KB inject and persona edits COMPOSE (Pattern
    # D3 / the "(persona × KB) epoch" model): a KB load re-emits under this persona;
    # a persona edit re-emits the current brief. Mutable holder so both closures
    # (handle_persona_update, ingest_kb) read/write the same reference.
    current_persona: list[Persona] = [DEFAULT_PERSONA]

    # Mode/role as a THIRD mutable axis alongside current_persona (06-01). MODE-01:
    # default = Learn, exactly as DEFAULT_PERSONA is the default-on-load persona.
    # All three closures (handle_persona_update, ingest_kb, handle_mode_update) write
    # these holders so their renders COMPOSE (the "(persona × KB × mode) epoch" model)
    # rather than clobber each other.
    current_mode: list[str] = [interview.MODE_LEARN]
    current_role: list[str] = [interview.DEFAULT_ROLE]

    # Fourth mutable holder for the picked response model (LLM-02 per-session
    # persistence). UNLIKE current_persona/current_mode/current_role, it does NOT
    # feed compose_instructions() — a model swap does not re-render the
    # persona/KB/mode prefix. It ONLY drives session.llm._opts.model via
    # handle_model_update (the simpler axis). Defaults to Fast (LLM-02).
    current_model: list[str] = [DEFAULT_MODEL_CHOICE]

    def compose_instructions() -> str:
        """Instruction string for the CURRENT (persona × KB × mode) epoch.

        In Interview mode, render the Interview block for the picked role composed
        with the current KB brief; otherwise render today's Learn (persona) block
        composed with the brief. The brief composition mirrors how ingest_kb /
        handle_persona_update already pass session_kb.brief. The mode toggle is the
        SINGLE sanctioned re-prefill — this is never called per turn (Pitfall 7).
        """
        if current_mode[0] == interview.MODE_INTERVIEW:
            interview_block = interview.render_interview_prompt(current_role[0])
            # Compose the KB brief through the SAME KB_CITE_NUDGE the Learn path uses
            # (persona.render_prompt) so a KB-grounded interview keeps the 04-04 GAP-2b
            # cite nudge instead of silently dropping it. Empty brief stays bare
            # (byte-stable, no nudge leak into the no-KB prefix).
            if session_kb.brief:
                return f"{interview_block} {KB_CITE_NUDGE} {session_kb.brief}"
            return interview_block
        return render_prompt(current_persona[0], session_kb.brief)

    # Live persona hot-swap (PERS-06): the browser side panel sends a full persona
    # snapshot over the `persona.update` RPC. The handler closes over the named
    # `agent`/`session` and applies the change IN PLACE — no AgentSession/Agent
    # teardown, no TTS-plugin recreation:
    #   * agent.update_instructions(...) is async; effective on the NEXT turn.
    #   * session.tts.update_options(voice=...) is sync and mutates the EXISTING
    #     TTS instance, so the metrics_collected subscription bound in
    #     metrics.attach() survives (Pattern E). The one re-prefill turn after an
    #     edit shows elevated llm_ttft_ms / over_budget:["llm_ttft"] — expected.
    # Full-snapshot apply is idempotent (last-edit-wins), so it is spam-safe with
    # no extra debounce; an edit arriving mid-turn applies to the next turn only.
    # The native RPC return value ("applied") IS the "applying…→applied" ack.
    # Compose with the KB (Pattern D3): a persona edit re-emits the CURRENT brief via
    # render_prompt(p, session_kb.brief), so editing the persona after a KB load never
    # clobbers the grounding. current_persona is updated so a later KB inject re-emits
    # under this persona — both are one-time, user-initiated re-prefills that compose.
    async def handle_persona_update(data):
        # persona.update is the UNTRUSTED RPC boundary (any room participant can send
        # an arbitrary payload). Persona(**snapshot) is a plain @dataclass: it rejects
        # missing/extra KEYS (TypeError) but performs NO VALUE validation — an unknown
        # knob value with valid keys (e.g. difficulty="Expert") constructs fine, and if
        # we committed current_persona[0] before rendering it would poison the shared
        # persona/KB/mode holder, then compose_instructions() (also used by
        # handle_mode_update / ingest_kb) would raise KeyError on DIFFICULTY[...] for the
        # REST of the session, wedging every later persona edit / KB load / mode toggle.
        # This is the persona-handler twin of the Phase-06 mode.update fix. VALIDATE the
        # knob values + voice_id and render BEFORE mutating the holder; commit only on
        # success so a malformed RPC cannot wedge the shared epoch state.
        try:
            snapshot = json.loads(data.payload)
            p = Persona(**snapshot)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("persona.update rejected: malformed payload (%s)", exc)
            return "error"
        if (p.difficulty not in DIFFICULTY or p.verbosity not in VERBOSITY
                or p.correction not in CORRECTION):
            logger.warning("persona.update rejected: unknown knob value %r", snapshot)
            return "error"
        if p.voice_id not in VOICE_IDS:
            logger.warning("persona.update rejected: unknown voice_id %r", p.voice_id)
            return "error"
        # Route through compose_instructions so a persona edit while in Interview mode
        # re-emits the INTERVIEW block (not the Learn block) — the renders compose.
        current_persona[0] = p
        await agent.update_instructions(compose_instructions())
        session.tts.update_options(voice=p.voice_id)
        return "applied"

    # Register AFTER connect/start so the method exists before the client calls it.
    ctx.room.local_participant.register_rpc_method(
        "persona.update", handle_persona_update
    )

    # Live mode/role hot-swap (MODE-02/03/04): the browser side panel sends a
    # {mode, role_key} snapshot over the `mode.update` RPC. Clones the persona
    # hot-swap machinery EXACTLY — write the mutable holders, re-prefill IN PLACE via
    # update_instructions(compose_instructions()), no AgentSession/Agent teardown. The
    # toggle is the single sanctioned re-prefill (same cost model as a persona edit),
    # NEVER a per-turn render (Pitfall 7). The native RPC return ("applied") IS the
    # applying->applied ack. ONLY on entering Interview mode do we fire one ask-Q1
    # generate_reply (MODE-04 ask boundary — mirrors the greeting/KB-priming calls);
    # toggling back to Learn just re-prefills and lets the normal loop resume.
    async def handle_mode_update(data):
        snapshot = json.loads(data.payload)
        # mode.update is the UNTRUSTED RPC boundary. VALIDATE before committing the
        # shared holders: compose_instructions() (also used by handle_persona_update /
        # ingest_kb) would raise KeyError on an unknown role_key AFTER the holders were
        # already poisoned, breaking persona edits + KB loads for the rest of the
        # session. Reject malformed payloads up front so a bad client cannot wedge the
        # shared epoch state.
        new_mode = snapshot.get("mode")
        new_role = snapshot.get("role_key", current_role[0])
        if new_mode not in (interview.MODE_LEARN, interview.MODE_INTERVIEW):
            logger.warning("mode.update rejected: unknown mode %r", new_mode)
            return "error"
        if new_mode == interview.MODE_INTERVIEW and new_role not in interview.ROLES:
            logger.warning("mode.update rejected: unknown role_key %r", new_role)
            return "error"
        current_mode[0] = new_mode
        current_role[0] = new_role
        await agent.update_instructions(compose_instructions())
        if current_mode[0] == interview.MODE_INTERVIEW:
            await session.generate_reply(
                instructions=(
                    "(internal) ask the first interview question for the current role, "
                    "then wait for the candidate's answer"
                )
            )
        return "applied"

    ctx.room.local_participant.register_rpc_method(
        "mode.update", handle_mode_update
    )

    # Live response-model hot-swap (LLM-01..LLM-03): the browser ModelPanel sends a
    # {choice: "fast"|"better"} snapshot over the `model.update` RPC. Clones
    # handle_mode_update's validate-before-mutate discipline (the Phase-6 fix) but
    # SIMPLER — NO update_instructions (a model swap does not re-render the
    # persona/KB/mode prefix) and NO generate_reply (a model switch must NOT inject
    # an agent turn — it lands on the user's NEXT real turn, LLM-02). The swap is
    # IN PLACE on the SAME openai.LLM instance (session.llm._opts.model = tag),
    # re-read fresh by the next chat() (RESEARCH §1.3) — so the metrics_collected
    # subscription from metrics.attach() survives, no AgentSession/Agent teardown,
    # current TTS uninterrupted. reasoning_effort="none" lives in the same _opts and
    # carries across the swap automatically (thinking stays OFF). The native RPC
    # return ("applied") IS the applying→applied ack.
    async def handle_model_update(data):
        # model.update is the UNTRUSTED RPC boundary. VALIDATE the choice BEFORE
        # mutating: only the plain keys in MODEL_CHOICES are accepted — NEVER a raw
        # tag from the client (LLM-01). Reject up front so a bad payload never
        # reaches _opts.model (validate-before-mutate, the Phase-6 discipline).
        snapshot = json.loads(data.payload)
        choice = snapshot.get("choice")
        if choice not in MODEL_CHOICES:
            logger.warning("model.update rejected: unknown choice %r", choice)
            return "error"
        current_model[0] = choice
        # In-place swap on the existing LLM instance (mirrors the TTS voice swap at
        # session.tts.update_options above): the next chat() re-reads _opts.model.
        session.llm._opts.model = resolved_model_tag(choice)
        return "applied"

    ctx.room.local_participant.register_rpc_method(
        "model.update", handle_model_update
    )

    # --- KB ingest (Plan 04-01/04-02): upload → parse → distill → inject once -----
    # The indicator moves idle→uploading→parsing→distilling→ready(n)/error. On a
    # successful parse the docs are distilled (one off-hot-path Ollama call) into a
    # compact brief that is injected ONCE into the frozen KB_SLOT via
    # update_instructions(render_prompt(...)) — then frozen for the session (no
    # per-turn re-distill / re-inject; the keystone constraint, Pitfall 7). KB is
    # in-memory only (KB-06): no disk/db write anywhere in this path; teardown is
    # implicit at job end.
    session_kb = _SessionKb()
    # GC guard: the byte-stream read runs in a background task. Keep a strong ref
    # in this list (docs-mandated) so the task is not garbage-collected mid-read.
    active_tasks: list[asyncio.Task] = []
    # Serialize ingest (M3): on_kb_stream spawns one ingest_kb task per incoming
    # stream, so a multi-file pick yields overlapping tasks that each append to
    # session_kb.docs, set session_kb.brief, and call update_instructions. Across
    # their await points those interleave → nondeterministic final brief/docs and
    # stacked priming replies. Hold this lock for the whole parse→distill→inject
    # critical section so each upload is applied atomically, in arrival order.
    ingest_lock = asyncio.Lock()

    async def set_kb_state(*, status: str, docs: int = 0, error: str = "") -> None:
        """Publish the kb.state participant attribute as JSON {status, docs, error}.

        Mirrors how `lk.agent.state` is read by AgentStatePill — the panel learns
        ingest status from this attribute (byte streams are one-way).
        """
        await ctx.room.local_participant.set_attributes(
            {KB_STATE_ATTRIBUTE: json.dumps({"status": status, "docs": docs, "error": error})}
        )

    async def ingest_kb(reader) -> None:
        """Read one uploaded byte stream, parse it, distill it, inject ONCE.

        On a typed KbParseError the agent surfaces a clear error and RETURNS — the
        voice loop keeps running with the unchanged (empty KB_SLOT) prefix (REL-03).
        On a distill failure the agent surfaces a clear error and RETURNS too, with
        the prefix left unchanged (the session continues without the KB).
        """
        info = reader.info
        raw = bytes()
        async for chunk in reader:
            raw += chunk
        # Serialize the whole parse→distill→inject critical section (M3) so overlapping
        # uploads from a multi-file pick apply atomically in arrival order instead of
        # interleaving at their await points.
        async with ingest_lock:
            await set_kb_state(status="parsing", docs=len(session_kb.docs))
            # Offload the synchronous, CPU-heavy PyMuPDF / python-docx parse to a worker
            # thread (H3): running it inline on the agent's single event-loop thread would
            # block audio, turn detection, and RPCs for the full parse duration — defeating
            # the "off hot path, voice loop keeps running" guarantee (REL-03).
            result = await asyncio.to_thread(kb_parse, info.name, info.mimeType, raw)
            if isinstance(result, KbParseError):
                await set_kb_state(status="error", docs=len(session_kb.docs), error=result.message)
                return

            # Aggregate token-budget guard (M2): the distiller re-distills the FULL
            # concatenation of every accepted doc, so reject a new doc when the running
            # session total would exceed KB_AGGREGATE_MAX_TOKENS — otherwise Ollama
            # silently truncates the distill prompt past its context (the GAP-1 class
            # of bug, multi-doc edition). Reject BEFORE appending so the prior KB stays
            # intact and the session continues unchanged.
            current_total = sum(d.token_estimate for d in session_kb.docs)
            if current_total + result.token_estimate > KB_AGGREGATE_MAX_TOKENS:
                await set_kb_state(
                    status="error",
                    docs=len(session_kb.docs),
                    error="KB is full — remove material or upload less to add more",
                )
                return
            session_kb.docs.append(result)

            # Distill all docs into a compact brief (one off-hot-path Ollama call — the
            # latency is invisible to the voice loop). A typed DistillError is surfaced
            # as a clear kb.state error; the session continues with the prefix unchanged.
            await set_kb_state(status="distilling", docs=len(session_kb.docs))
            try:
                # Offload the blocking httpx-stream distill to a worker thread (H3): the
                # synchronous httpx.Client streaming loop would otherwise block the event
                # loop for the whole generation. The client now also carries a bounded
                # DISTILL_TIMEOUT_SECONDS, so a stalled Ollama maps to DistillError instead
                # of hanging the ingest forever.
                brief = await asyncio.to_thread(kb_distill, _concat_docs(session_kb.docs))
            except DistillError:
                # Roll back the just-appended doc so a failed distill leaves session_kb
                # exactly as it was (the prior brief stays valid; M3 atomicity).
                session_kb.docs.pop()
                await set_kb_state(
                    status="error",
                    docs=len(session_kb.docs),
                    error="Couldn't build the brief — continuing without KB",
                )
                return

            # Inject the brief into the frozen KB_SLOT EXACTLY ONCE (the single sanctioned
            # re-prefill, mirroring the persona hot-swap). render_prompt composes under the
            # CURRENT persona so a prior persona edit is preserved. Then freeze: no
            # per-turn re-distill / re-inject. The elevated llm_ttft_ms / over_budget on
            # THIS one turn is expected (same as the persona-swap turn) — NOT "fixed".
            session_kb.brief = brief
            # Route through compose_instructions so a KB load while in Interview mode
            # re-emits the INTERVIEW block + the new brief (compose, not clobber).
            await agent.update_instructions(compose_instructions())
            await set_kb_state(status="ready", docs=len(session_kb.docs))

        # Priming turn (Pattern E, Pitfall 3): fire one internal reply so the KB
        # prefill warms while the panel shows "ready" — the user's first REAL turn is
        # cache-warm. The goal is the prefill, not a visible utterance (silent-vs-
        # spoken is a [VM-INTROSPECT] operator gate). Outside the lock so the next
        # queued upload isn't blocked on this reply.
        await session.generate_reply(
            instructions="(internal) acknowledge the loaded material briefly"
        )

    def on_kb_stream(reader, participant_identity) -> None:
        task = asyncio.create_task(ingest_kb(reader))
        active_tasks.append(task)
        task.add_done_callback(active_tasks.remove)

    ctx.room.register_byte_stream_handler(KB_UPLOAD_TOPIC, on_kb_stream)

    await session.generate_reply(instructions=GREETING_INSTRUCTIONS)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
