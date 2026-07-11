"""Rehearsal LiveKit agent worker — AgentSession wiring + walking-skeleton gate.

Phase 1 scope (Plan 01-03): construct an AgentSession against the three LOCAL
model endpoints (Nemotron streaming STT, Ollama LLM, Kokoro TTS) with the LOCAL
MultilingualModel turn detector, run a startup warmup that emits exactly ONE
real LLM-TTFT metric line through the scaffold, and register as a worker against
the self-hosted livekit-server. NO live voice turn happens yet — no participant
audio flows in Phase 1.

Local-first invariant (PERF-03 / DEPLOY-02): every model base_url is an in-stack
service on the `rehearsal` Docker network; the turn detector is the local
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
from livekit.agents import (
    Agent,
    AgentSession,
    ChatContext,
    JobContext,
    JobProcess,
    StopResponse,
    WorkerOptions,
    cli,
)
from livekit.plugins import openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

import endpointing
import history
import interview
import metrics
import paralinguistics
import transcript_gate
from transcript_debug import transcript_debug_values
from captioned_tts import CaptionedTTS
from expressive_mode_tts import ExpressiveModeTTS
from expressive_tts import ExpressiveTTS
from nemo_stt import NemoSTT
from models import MODEL_CHOICES, default_model_choice, resolved_model_tag
from placement import resolve_stt_placement
from kb import KB_AGGREGATE_MAX_TOKENS, KB_MAX_RAW_BYTES, KbParseError, ParsedDoc
from kb import distill as kb_distill
from kb import kb_aggregate_is_full
from kb import parse as kb_parse
from kb_ingest import KbBatchDistiller
from persona import (
    CORRECTION,
    DEFAULT_PERSONA,
    DIFFICULTY,
    Persona,
    VERBOSITY,
    VOICE_IDS,
    render_prompt,
)

logger = logging.getLogger("rehearsal.agent")

# In-stack model endpoints (Docker `rehearsal` network — all LAN-local, no egress).
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434/v1")
OLLAMA_GENERATE_URL = os.environ.get("OLLAMA_GENERATE_URL", "http://ollama:11434/api/generate")
# NemoSTT websocket endpoint — a `ws://` URL (NOT `http://.../v1`), matching the
# Wave-1 (09-01) server route on the `nemo-stt` service. The STT model itself is
# single-sourced server-side via STT_MODEL (no model tag in agent code).
NEMO_STT_URL = os.environ.get("NEMO_STT_URL", "ws://nemo-stt:8000/v1/audio/stream")
# The CPU STT route on the `nemo-stt-cpu` service (STT_RUNTIME=cpu).
# Same internal port 8000 as the GPU service — reached by a different service-DNS host
# (the host-side 8001:8000 mapping is for debugging only). placement.resolve_stt_placement
# picks between this and NEMO_STT_URL ONCE at session start (build_session).
NEMO_STT_CPU_URL = os.environ.get("NEMO_STT_CPU_URL", "ws://nemo-stt-cpu:8000/v1/audio/stream")
KOKORO_BASE_URL = os.environ.get("KOKORO_BASE_URL", "http://kokoro:8880/v1")
# Chatterbox-Turbo root for the OPT-IN expressive-voice engine (expressive_tts.py).
# GPU-only, ~4.3GB VRAM; OFF by default (Kokoro is the default TTS). Flipped live per
# session via the tts.update RPC. NOT a /v1 suffix — the endpoint is POST /v1/audio/speech
# under this root (expressive_tts.py appends it).
CHATTERBOX_BASE_URL = os.environ.get("CHATTERBOX_BASE_URL", "http://chatterbox:8004")

WARMUP_PROMPT = "Reply with the single word: ready."
WARMUP_TIMEOUT_SECONDS = 120.0
WARMUP_NUM_PREDICT = 16
THINKING_ENABLED = False  # protect TTFT (see ollama/Modelfile)
_MS_PER_SECOND = 1000.0

# ============================ CONVERSATION-FEEL KNOBS ============================
# Retuned for buffered Parakeet. Starting values below; FINAL values are
# operator-empirical on the RTX 5090 (14-09) against the felt regression. Do not
# silently change without re-reading agent/metrics rolling_summary.
#   endpointing      : mode-aware (agent/endpointing.py) — Converse 0.3/3.0, Interview 0.7/5.0
#   VAD threshold    : 0.6  (down from 0.65) — recover swallowed openings
#   interrupt min_dur: 0.25 (down from 0.30) — interrupts cut TTS reliably
#   STT chunk        : 320 ms (.env STT_STREAM_CHUNK_MS) — endpointing granularity
#   STT silence      : 640 ms (.env STT_ENDPOINT_SILENCE_MS) — accepted buffered baseline
#   att_context_size : [70,6] (.env STT_ATT_CONTEXT_SIZE) — legacy streaming only
# ================================================================================
#
# Endpointing is mode-aware (FEEL-01): the Converse/Interview floors live in
# agent/endpointing.py (pure, sandbox-testable). build_session seeds the session
# from the initial mode; handle_mode_update live-switches the floor via the public
# AgentSession.update_options(endpointing_opts=...) setter — no teardown.
# METRICS INTERPRETATION (RESEARCH §2.4 / §7.7): the raised interview min_delay (0.7s)
# INTENTIONALLY exceeds metrics.BUDGET_MS["eou"]=300 (agent/metrics.py:31), so interview
# turns flag over_budget:["eou"]. This is EXPECTED and correct for deliberate-answer
# speech, NOT a regression — do not "fix" it. agent/metrics.py is READ-ONLY here.

# Silero VAD speech-onset bar (FEEL-02). Lower = catches quiet/soft onsets so the
# first word isn't swallowed; higher = fewer open-mic false triggers from playout
# tail + room noise. 0.6 is the documented start (down from the 0.65 echo-defense
# value) to recover dropped openings; operator A/B-tunes in 14-09. Headphones (the
# recommended setup) make a lower bar safe.
VAD_ACTIVATION_THRESHOLD: float = 0.6

# Barge-in gate (FEEL-02). min_duration = real speech required before cancelling
# TTS: low enough that a genuine interrupt reliably cuts the agent, high enough to
# ignore the agent's own echo tail + "mm-hmm" backchannels. resume_false_interruption
# + a 2.0s timeout make a no-transcript noise blip resume the agent, not drop the turn.
INTERRUPT_MIN_DURATION_S: float = 0.25
RESUME_FALSE_INTERRUPTION: bool = True
FALSE_INTERRUPT_TIMEOUT_S: float = 2.0
# LiveKit's default 3s AEC warmup sends silence to STT while the agent speaks.
# In a headphone-first local trainer, that drops the first words of real barge-in.
AEC_WARMUP_DURATION_S: float = 0.0
TRANSCRIPT_CORRECTION_TOPIC = "rehearsal.transcript.correction"

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
# User-selectable response models via plain-language OUTCOME labels in the UI
# ("Fast (snappier)" / "Better (more thoughtful)"); v1.2 R2 adds a third "floor" tier
# (a small model for ~6GB hosts — see agent/models.py MODEL_CHOICES). The agent only ever
# sees the validated plain choice key here — NEVER a raw Ollama tag from the client
# (LLM-01). Fast is the default unless REHEARSAL_DEFAULT_MODEL overrides (LLM-02). No
# hardcoded gemma tag: each choice resolves to its own env var (no-hardcoded-tag invariant).
# Session default choice — env-overridable (REHEARSAL_DEFAULT_MODEL) so the R7 installer can
# boot a weak host on "floor". build_session/placement read this once at startup.
DEFAULT_MODEL_CHOICE = default_model_choice(os.environ)

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


def build_session(vad: silero.vad.VAD, transcript_correction_cb=None) -> AgentSession:
    """Construct the AgentSession against the three local endpoints + local turn
    detector. Used by the entrypoint; metrics are attached per-plugin after.
    """
    # STT placement is resolved EXACTLY ONCE here at session start from the worst-case
    # LLM (E4B/Better) — so a mid-session Fast↔Better swap is always VRAM-safe and STT
    # is NEVER re-placed (STT-06; handle_model_update stays LLM-only). The resolver
    # checks STT_FORCE_CPU first (STT-07) and defaults CPU until the operator sets the
    # STT_HEADROOM_MEASURED flag. DEFAULT_MODEL_CHOICE suffices (the worst-case math is
    # what makes a later swap safe — the resolver need not see the live current_model).
    placement = resolve_stt_placement(DEFAULT_MODEL_CHOICE, os.environ)
    stt_url = NEMO_STT_URL if placement == "gpu" else NEMO_STT_CPU_URL
    return AgentSession(
        aec_warmup_duration=AEC_WARMUP_DURATION_S,
        vad=vad,
        stt=NemoSTT(ws_url=stt_url, language="en", correction_cb=transcript_correction_cb),
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
        # TTS engine — a session-lifetime wrapper over BOTH TTS engines so expressive
        # mode can be toggled LIVE (tts.update RPC) without a hot instance swap that
        # would orphan the metrics subscription (see expressive_mode_tts.py). The DEFAULT
        # active engine is Kokoro CaptionedTTS: /dev/captioned_speech returns the SAME
        # 24 kHz mono WAV the room already plays PLUS word-level timestamps for the
        # avatar's word->viseme lip-sync — default behaviour is unchanged. The OPT-IN
        # Chatterbox ExpressiveTTS engine adds mood-driven vocal exaggeration (GPU-only,
        # ~4.3GB, exceeds P50<1.0s by design). Both engines are cheap in-process (httpx
        # only; model VRAM lives in the compose services). The room is attached to both
        # in the entrypoint after connect (see ExpressiveModeTTS.attach_room).
        tts=ExpressiveModeTTS(
            kokoro=CaptionedTTS(
                base_url=KOKORO_BASE_URL,
                voice=DEFAULT_PERSONA.voice_id,
            ),
            chatterbox=ExpressiveTTS(
                base_url=CHATTERBOX_BASE_URL,
                voice=DEFAULT_PERSONA.voice_id,
            ),
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
        # endpointing is now MODE-AWARE (FEEL-01, 14-01): seeded here from the initial
        # mode (MODE_LEARN → snappy Converse floor) via endpointing.endpointing_for_mode,
        # and live-switched on mode.update through the public
        # session.update_options(endpointing_opts=...) setter (handle_mode_update). The
        # Interview floor's raised min_delay intentionally exceeds
        # metrics.BUDGET_MS["eou"]=300 so interview turns flag over_budget:["eou"] —
        # EXPECTED, not a regression. The selector returns a plain dict matching the
        # EndpointingOptions TypedDict (mode/min_delay/max_delay).
        # Barge-in / interruption gate (Plan 02-03-2). Barge-in is built in:
        # AgentSession cancels TTS + rolls back the turn on user speech and
        # `interruption.enabled` defaults True (verified in voice/turn.py
        # _INTERRUPTION_DEFAULTS) — we DO NOT disable it (allow_interruptions
        # stays on). On the dict surface the deprecated direct kwargs map as:
        #   min_interruption_duration   -> interruption["min_duration"]
        #   false_interruption_timeout  -> interruption["false_interruption_timeout"]
        #   resume_false_interruption   -> interruption["resume_false_interruption"]
        # All three keys are verified present on InterruptionOptions across
        # livekit-agents@1.5.0..@1.6.4 (voice/turn.py). min_duration is the named
        # INTERRUPT_MIN_DURATION_S (0.25s, retuned from 0.3 in 14-01) — enough real
        # speech to defend against the agent's own echo tail and "mm-hmm" backchannels
        # while still cutting TTS reliably. resume_false_interruption + the named
        # FALSE_INTERRUPT_TIMEOUT_S make a no-transcript noise-blip barge-in resume the
        # agent instead of dropping the turn (open-mic win).
        # VM-introspection-pending: confirm the installed InterruptionOptions
        # accepts these keys (sandbox cannot import livekit — grounded on tagged
        # source). If a future version renames a key, the dict degrades by
        # ignoring unknown keys at _resolve_interruption (TypedDict, total=False).
        turn_handling={
            "turn_detection": MultilingualModel(),
            "endpointing": endpointing.endpointing_for_mode(interview.MODE_LEARN),
            "interruption": {
                "min_duration": INTERRUPT_MIN_DURATION_S,
                "resume_false_interruption": RESUME_FALSE_INTERRUPTION,
                "false_interruption_timeout": FALSE_INTERRUPT_TIMEOUT_S,
            },
        },
    )


def prewarm(proc: JobProcess) -> None:
    """Worker-startup hook: load VAD and emit the one real warmup metric line.

    Runs once when the worker process boots — before any job/voice turn — so the
    walking-skeleton gate (exactly one real llm_ttft_ms line) is satisfied at
    startup without a participant. The VAD is cached for reuse in the entrypoint.
    """
    # Silero VAD speech-onset bar = VAD_ACTIVATION_THRESHOLD (FEEL-02, 14-01 retune):
    # named constant with tuning rationale at the top of this module (down from 0.65
    # to recover swallowed openings). `activation_threshold` is verified present on
    # silero.VAD.load (livekit-plugins-silero vad.py: default 0.5, alongside
    # min_speech_duration/min_silence_duration/deactivation_threshold).
    proc.userdata["vad"] = silero.VAD.load(activation_threshold=VAD_ACTIVATION_THRESHOLD)
    ttft_ms = _warmup_llm_ttft_ms(resolved_llm_tag())
    metrics.emit_warmup_metric(ttft_ms)


GREETING_INSTRUCTIONS = (
    "Greet the user briefly and invite them to start speaking about a topic they "
    "want to practice."
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
        # REL-02: never answer noise/silence. On a garbled/empty finalize, reprompt
        # and cancel the would-be reply so the agent doesn't hallucinate a response to
        # a cough, open-mic blip, or empty STT final (boundary: garbled STT).
        if transcript_gate.is_garbled(new_message.text_content or ""):
            await self.session.generate_reply(
                instructions="(internal) You didn't catch that. In one short spoken "
                "sentence, say you didn't catch it and ask them to repeat."
            )
            raise StopResponse()
        # Command path: a direct "laugh" request forces the laugh cue onto THIS reply so
        # it always works on demand (test/demo), independent of the LLM's mood. The TTS
        # layer turns the cue into real audio (expressive) or strips it (Kokoro).
        if paralinguistics.wants_laugh(new_message.text_content or ""):
            turn_ctx.add_message(
                role="system",
                content="The learner asked you to laugh. Begin your reply with the exact "
                "token [laugh] — that token is the ONLY real laugh; it is vocalized as a "
                "genuine laugh. Do NOT spell laughter out ('haha', 'hahaha', 'ha ha') "
                "anywhere in the reply — spelled-out laughter is read letter by letter and "
                "sounds fake and robotic. After the [laugh] token, continue warmly and "
                "naturally.",
            )
        if history.should_trim(len(self.chat_ctx.items)):
            trimmed = self.chat_ctx.copy().truncate(max_items=history.window_target())
            await self.update_chat_ctx(trimmed)


def decode_rpc_payload(data, method: str) -> dict | None:
    """Decode an untrusted RPC JSON object payload; None signals a malformed body.

    Every RPC handler crosses the same untrusted boundary, so the JSON-decode +
    is-object guard lives here once instead of being re-implemented per handler
    (a missing guard is how a malformed payload raises an unhandled error mid-RPC).
    """
    try:
        decoded = json.loads(data.payload)
    except json.JSONDecodeError as exc:
        logger.warning("%s rejected: malformed payload (%s)", method, exc)
        return None
    if not isinstance(decoded, dict):
        logger.warning("%s rejected: payload is not an object", method)
        return None
    return decoded


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

    async def publish_transcript_correction(text: str) -> None:
        await ctx.room.local_participant.publish_data(
            json.dumps({"text": text}),
            reliable=True,
            topic=TRANSCRIPT_CORRECTION_TOPIC,
        )

    session = build_session(ctx.proc.userdata["vad"], publish_transcript_correction)
    # Give BOTH TTS engines the room handle so either can publish avatar data (Kokoro's
    # word schedules or Chatterbox's per-sentence mood). Done after connect; before this
    # the agent never speaks, so no frame is ever dropped for lack of a room.
    if isinstance(session.tts, ExpressiveModeTTS):
        session.tts.attach_room(ctx.room)
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
    #
    # F17/G4 pin-tripwire: the live cap AND the model-swap handler mutate the private
    # `session.llm._opts` surface (.model / .extra_body). It is present and forwarded
    # in the pinned livekit-plugins-openai==1.6.4, but a silent version bump could
    # rename or drop it, degrading the cap/model-swap to a silent no-op. Assert the
    # surface exists BEFORE the first mutation so a bad bump fails loudly at startup
    # instead of shipping a broken hot path.
    _opts = getattr(session.llm, "_opts", None)
    if _opts is None or not hasattr(_opts, "model") or not hasattr(_opts, "extra_body"):
        raise RuntimeError(
            "session.llm._opts.{model,extra_body} missing — the live cap + model swap "
            "depend on this private surface; re-pin livekit-plugins-openai==1.6.4 (F17/G4)"
        )
    session.llm._opts.extra_body = {"max_tokens": LIVE_NUM_PREDICT_CAP}
    # Named local ref (was inline): 03-02's RPC handler will close over `agent` to
    # hot-swap the persona via agent.update_instructions(...) without a restart.
    # render_prompt(DEFAULT_PERSONA, "") is byte-identical to the old
    # render_persona(DEFAULT_PERSONA) golden (the empty-KB seam).
    agent = HistoryWindowAgent(instructions=render_prompt(DEFAULT_PERSONA, ""))

    def log_user_input_transcribed(ev) -> None:
        logger.info(
            "transcript-debug user_input_transcribed final=%s chars=%d sha=%s",
            *transcript_debug_values(ev),
        )

    session.on("user_input_transcribed", log_user_input_transcribed)
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

        The persona remains the identity. Non-Learn modes append a compact practice
        pattern fragment. This keeps KB composition centralized in render_prompt and
        avoids a separate agent class for each mode.
        """
        base_prompt = render_prompt(current_persona[0], session_kb.brief)
        mode_prompt = interview.render_mode_prompt(current_mode[0], current_role[0])
        if not mode_prompt:
            return base_prompt
        return f"{base_prompt} {mode_prompt}"

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
        snapshot = decode_rpc_payload(data, "persona.update")
        if snapshot is None:
            return "error"
        try:
            p = Persona(**snapshot)
        except TypeError as exc:
            logger.warning("persona.update rejected: malformed fields (%s)", exc)
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
    # applying->applied ack. ONLY on entering Interview mode or changing the interview
    # target do we fire one ask-Q1 generate_reply (MODE-04 ask boundary — mirrors the
    # greeting/KB-priming calls); toggling back to Learn just re-prefills and lets the
    # normal loop resume.
    async def handle_mode_update(data):
        # mode.update is the UNTRUSTED RPC boundary. VALIDATE before committing the
        # shared holders: compose_instructions() (also used by handle_persona_update /
        # ingest_kb) would raise KeyError on an unknown role_key AFTER the holders were
        # already poisoned, breaking persona edits + KB loads for the rest of the
        # session. Reject malformed payloads up front so a bad client cannot wedge the
        # shared epoch state.
        snapshot = decode_rpc_payload(data, "mode.update")
        if snapshot is None:
            return "error"
        new_mode = snapshot.get("mode")
        new_role = snapshot.get("role_key", current_role[0])
        if new_mode not in interview.MODES:
            logger.warning("mode.update rejected: unknown mode %r", new_mode)
            return "error"
        if not isinstance(new_role, str) or new_role not in interview.ROLES:
            logger.warning("mode.update rejected: unknown role_key %r", new_role)
            return "error"
        previous_mode = current_mode[0]
        previous_role = current_role[0]
        role_changed = new_role != previous_role
        should_ask_first_question = new_mode == interview.MODE_INTERVIEW and (
            previous_mode != interview.MODE_INTERVIEW or role_changed
        )
        current_mode[0] = new_mode
        current_role[0] = new_role
        await agent.update_instructions(compose_instructions())
        # Switch the endpointing floor live (FEEL-01) via the public setter — same
        # in-place runtime-mutation pattern as session.llm._opts.model /
        # session.tts.update_options. No teardown; effective on the next turn.
        session.update_options(
            endpointing_opts=endpointing.endpointing_for_mode(current_mode[0])
        )
        if should_ask_first_question:
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
        snapshot = decode_rpc_payload(data, "model.update")
        if snapshot is None:
            return "error"
        choice = snapshot.get("choice")
        if choice not in MODEL_CHOICES:
            logger.warning("model.update rejected: unknown choice %r", choice)
            return "error"
        try:
            tag = resolved_model_tag(choice)
        except SystemExit:
            logger.warning("model.update rejected: %r has no pinned tag (env unset)", choice)
            return "error"
        current_model[0] = choice
        # In-place swap on the existing LLM instance (mirrors the TTS voice swap at
        # session.tts.update_options above): the next chat() re-reads _opts.model.
        session.llm._opts.model = tag
        return "applied"

    ctx.room.local_participant.register_rpc_method(
        "model.update", handle_model_update
    )

    # avatar.update {on: bool} flips the captioned-TTS lip-sync gate live (AVTR-12).
    # With the avatar OFF the TTS requests no word timestamps and publishes no
    # lk.avatar.lipsync frames (the voice-only auditable invariant); ON re-enables the
    # word-schedule publish. Mirrors handle_model_update's validate-before-mutate shape.
    async def handle_avatar_update(data):
        # avatar.update is the UNTRUSTED RPC boundary — validate the type BEFORE
        # touching the live TTS so a malformed payload never reaches the gate.
        snapshot = decode_rpc_payload(data, "avatar.update")
        if snapshot is None:
            return "error"
        on = snapshot.get("on")
        if not isinstance(on, bool):
            logger.warning("avatar.update rejected: 'on' not a bool: %r", on)
            return "error"
        # Gate BOTH engines so avatar publishing works regardless of the active engine.
        if isinstance(session.tts, ExpressiveModeTTS):
            session.tts.set_avatar_enabled(on)
        return "applied"

    ctx.room.local_participant.register_rpc_method(
        "avatar.update", handle_avatar_update
    )

    # tts.update {expressive: bool} flips the active TTS ENGINE live — Kokoro (fast,
    # lip-sync, default) <-> Chatterbox (opt-in mood-driven vocal exaggeration, GPU-only,
    # exceeds P50<1.0s by design). Mirrors handle_avatar_update's validate-before-mutate
    # shape EXACTLY. No teardown: the wrapper (expressive_mode_tts.py) is the stable
    # session.tts, so the metrics subscription survives; the next turn synthesizes
    # through the newly-selected engine.
    async def handle_tts_update(data):
        # tts.update is the UNTRUSTED RPC boundary — validate the type BEFORE touching
        # the live TTS so a malformed payload never reaches the engine switch.
        snapshot = decode_rpc_payload(data, "tts.update")
        if snapshot is None:
            return "error"
        expressive = snapshot.get("expressive")
        if not isinstance(expressive, bool):
            logger.warning("tts.update rejected: 'expressive' not a bool: %r", expressive)
            return "error"
        logger.info("tts.update received: expressive=%s (tts=%s)", expressive, type(session.tts).__name__)
        if isinstance(session.tts, ExpressiveModeTTS):
            session.tts.set_expressive(expressive)
        return "applied"

    ctx.room.local_participant.register_rpc_method(
        "tts.update", handle_tts_update
    )

    # session.reset {} clears the conversation context WITHOUT tearing the room down
    # (SESS-02). Persona, mode, role, model, and the KB brief are kept — those are
    # session CONFIG, not context — so this does NOT touch the mode and therefore does
    # NOT bypass endpointing.endpointing_for_mode() (the 14-01 seam stays live). The
    # re-prime goes through compose_instructions() for the CURRENT epoch.
    async def handle_session_reset(data):
        try:
            await agent.update_chat_ctx(ChatContext.empty())
            await agent.update_instructions(compose_instructions())
        except Exception as exc:  # boundary: never wedge the live room on reset
            logger.warning("session.reset failed: %s", exc)
            return "error"
        return "applied"

    ctx.room.local_participant.register_rpc_method(
        "session.reset", handle_session_reset
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

    async def _distill_docs(docs: list[ParsedDoc]) -> str:
        # Offload the blocking httpx-stream distill to a worker thread (H3): the
        # synchronous httpx.Client streaming loop would otherwise block the event loop
        # for the whole generation. The client carries a bounded DISTILL_TIMEOUT_SECONDS,
        # so a stalled Ollama maps to DistillError instead of hanging the ingest forever.
        return await asyncio.to_thread(kb_distill, _concat_docs(docs))

    async def _apply_brief(brief: str) -> None:
        # Inject the brief into the frozen KB_SLOT (the single sanctioned re-prefill,
        # mirroring the persona hot-swap). Route through compose_instructions so a KB
        # load while in Interview mode re-emits the INTERVIEW block + the new brief
        # (compose, not clobber). render_prompt composes under the CURRENT persona so a
        # prior persona edit is preserved. Then frozen: no per-turn re-distill/-inject.
        session_kb.brief = brief
        await agent.update_instructions(compose_instructions())

    # O3 Part 2: coalesce a multi-file pick's distills. session_kb.docs IS the committed
    # list the distiller owns; while one distill runs, later uploads pile into its
    # pending queue and drain in ONE batch → ~2 distills per burst instead of N, without
    # losing arrival order or M3 atomicity (the distill lock replaces the old
    # ingest_lock for the distill/inject half; parse stays serialized below).
    kb_distiller = KbBatchDistiller(
        committed=session_kb.docs,
        max_tokens=KB_AGGREGATE_MAX_TOKENS,
        distill_docs=_distill_docs,
        apply_brief=_apply_brief,
        publish_state=set_kb_state,
    )

    async def ingest_kb(reader) -> None:
        """Read one uploaded byte stream, parse it, distill it, inject ONCE.

        On a typed KbParseError the agent surfaces a clear error and RETURNS — the
        voice loop keeps running with the unchanged (empty KB_SLOT) prefix (REL-03).
        On a distill failure the agent surfaces a clear error and RETURNS too, with
        the prefix left unchanged (the session continues without the KB).
        """
        # F12: contain the WHOLE ingest (stream read + parse→distill→inject) in a
        # last-resort net. Typed KbParseError/DistillError are handled below with clean
        # early returns; anything ELSE (a parser bug, an SDK attribute change like the
        # info.mime_type break, a mid-stream network error) would otherwise escape this
        # fire-and-forget task silently and strand the panel at "parsing"/"distilling"
        # forever (the web side has no timeout). CancelledError is BaseException, not
        # Exception, so cooperative cancellation still propagates untouched.
        try:
            info = reader.info
            # F6: accumulate into a bytearray (amortized O(n), vs O(n²) for `raw += chunk`
            # on immutable bytes) AND enforce the raw-byte ceiling INSIDE the loop. The
            # KB_MAX_RAW_BYTES guard inside kb_parse only fires AFTER the whole stream is
            # buffered, so a non-browser room participant could stream unbounded bytes on
            # the KB topic and OOM the agent before rejection. Abort as soon as the cap is
            # crossed, surface the oversize error immediately, and stop reading.
            raw = bytearray()
            oversize = False
            async for chunk in reader:
                raw += chunk
                if len(raw) > KB_MAX_RAW_BYTES:
                    oversize = True
                    break
            if oversize:
                await set_kb_state(
                    status="error",
                    docs=len(session_kb.docs),
                    error="Too large for inline KB — trimmed/skipped",
                )
                return
            raw = bytes(raw)
            # Serialize ONLY the parse (M3): overlapping uploads from a multi-file pick
            # parse in arrival order, and try_add appends to the distiller's pending queue
            # in that same order. The distill/inject half is NOT under this lock — it runs
            # on the distiller's own lock (below) so a later file can parse while an
            # earlier batch is still distilling, which is exactly what lets a burst
            # coalesce (O3 Part 2).
            async with ingest_lock:
                # O3 Part 1: pre-parse aggregate short-circuit. If the session (committed +
                # everything already queued for the next batch) is at KB_AGGREGATE_MAX_TOKENS,
                # EVERY accepted doc adds >= 1 token, so try_add is guaranteed to reject this
                # upload — skip the CPU-heavy PyMuPDF/docx parse (which runs under this lock
                # and would block the next parse) and surface the same "KB is full" error.
                if kb_aggregate_is_full(kb_distiller.current_total()):
                    await set_kb_state(
                        status="error",
                        docs=len(session_kb.docs),
                        error="KB is full — remove material or upload less to add more",
                    )
                    return
                await set_kb_state(status="parsing", docs=len(session_kb.docs))
                # Offload the synchronous, CPU-heavy PyMuPDF / python-docx parse to a worker
                # thread (H3): running it inline on the agent's single event-loop thread would
                # block audio, turn detection, and RPCs for the full parse duration — defeating
                # the "off hot path, voice loop keeps running" guarantee (REL-03).
                result = await asyncio.to_thread(kb_parse, info.name, info.mime_type, raw)
                if isinstance(result, KbParseError):
                    await set_kb_state(status="error", docs=len(session_kb.docs), error=result.message)
                    return

                # Aggregate token-budget guard (M2): the distiller re-distills the FULL
                # concatenation of every accepted doc, so a new doc that would push the
                # running total (committed + pending) past KB_AGGREGATE_MAX_TOKENS is
                # rejected — otherwise Ollama silently truncates the distill prompt past its
                # context (the GAP-1 class of bug, multi-doc edition). try_add rejects BEFORE
                # enqueueing so the prior KB stays intact and the session continues unchanged.
                if not await kb_distiller.try_add(result):
                    return
                await set_kb_state(status="distilling", docs=len(session_kb.docs) + 1)

            # Coalesced distill + inject OUTSIDE the parse lock (O3 Part 2). This drains
            # every currently-pending doc into ONE off-hot-path Ollama call; a burst that
            # arrived during a prior in-flight distill collapses into a single batch. A
            # typed DistillError rolls the batch back out and surfaces a clear kb.state
            # error (the prior brief stays valid; M3 atomicity), returning False here.
            # `fired` is True only for the TERMINAL drain of a burst, so the priming turn
            # below runs exactly once per burst — not once per coalesced-away file.
            fired = await kb_distiller.drain_and_distill()
            if not fired:
                return
        except Exception:
            # Unexpected failure anywhere in the ingest: log with traceback and surface a
            # generic error state so the panel unsticks. Then RETURN so the priming turn
            # below never fires for a failed ingest.
            logger.exception("KB ingest failed unexpectedly")
            await set_kb_state(
                status="error",
                docs=len(session_kb.docs),
                error="Couldn't process the upload — continuing without it",
            )
            return

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
    # prewarm() does a REAL LLM warmup — it cold-loads the model into VRAM and runs
    # one inference. On modest / low-VRAM GPUs that can exceed livekit-agents' 10s
    # default process-init timeout, which then SIGUSR1-kills the worker process and
    # retries forever — cancelling the model load each time so it never goes
    # resident (a permanent crash loop, not a slow start). Give the cold warmup
    # room; env-tunable for fast hosts that want the tighter default back.
    init_timeout = float(os.environ.get("AGENT_INIT_TIMEOUT_S", "300"))
    cli.run_app(WorkerOptions(
        entrypoint_fnc=entrypoint,
        prewarm_fnc=prewarm,
        initialize_process_timeout=init_timeout,
    ))
