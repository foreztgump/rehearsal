"""Setup-time KB distillation for the Adept trainer (Plan 04-02).

Turns the concatenated uploaded docs into a compact, byte-stable brief that lands
ONCE in the frozen ``KB_SLOT`` prefix (persona.render_prompt). Two surfaces:

  * ``build_distill_prompt(text) -> str`` — PURE, deterministic; sandbox-testable
    with NO network and NO rtc-SDK dependency. The only interpolation is the static
    ``DISTILL_INSTRUCTION`` + the input text.
  * ``distill(text) -> str`` — one OFF-HOT-PATH Ollama call (the latency is invisible
    to the voice loop, so a larger ``num_predict`` is fine). Mirrors
    ``main._warmup_llm_ttft_ms``'s httpx-stream-to-/api/generate shape: ``think=false``,
    ``stream=true``, ``options.num_predict``; accumulates ``response`` chunks.

Design rules (mirror ``metrics.py`` / ``persona.py`` / ``parse.py``):
  * rtc-SDK-free: ``httpx`` + stdlib only, so the module imports in the sandbox.
  * No second hardcoded LLM tag — the model resolves from ``OLLAMA_MODEL`` exactly
    like ``main.resolved_llm_tag`` (read from ``os.environ`` directly to stay free
    of a circular ``main`` import, which would also pull in the rtc SDK).
  * Ollama bug #15260 (``think=false`` + structured-JSON mode silently drops the JSON
    constraint for the pinned model family): do NOT request structured output — the
    brief is plain text with a ``FACTS:`` delimiter parsed downstream (the fact-anchor
    design, Pitfall 8 / KB-04). The payload carries no output-schema key.
  * Boundary discipline: a network/timeout failure raises a typed ``DistillError``
    (NO bare except) so ``main._ingest_kb`` can surface a clear message (REL-03).
  * The OUTPUT brief lands in the frozen prefix, so it must carry no volatile data;
    this module adds none (the model is instructed to copy facts verbatim).
"""
from __future__ import annotations

import json
import os

import httpx

# Resident-model endpoints (read from env the same way main.py does, so distill
# stays importable WITHOUT importing main — which would be circular and would pull
# in the rtc SDK, breaking sandbox importability).
OLLAMA_GENERATE_URL = os.environ.get("OLLAMA_GENERATE_URL", "http://ollama:11434/api/generate")

# Fixed instruction for the distill pass. Produces (1) a compact spoken-coaching
# domain brief and (2) a FACTS: list of EXACT terms/numbers/commands/identifiers
# copied VERBATIM — the fact-anchor design (Pitfall 8 / KB-04) that makes the
# trainer reference the learner's own material instead of paraphrasing it away.
DISTILL_INSTRUCTION: str = (
    "You are preparing reference material for a spoken coaching session. Read the "
    "source material below and produce TWO sections, plain text only (no markdown, "
    "no JSON, no code fences):\n"
    "1. A compact prose DOMAIN BRIEF (a few short paragraphs) a voice coach can use "
    "to ground a spoken conversation in this material. Spoken-friendly, no lists.\n"
    "2. A line that begins with 'FACTS:' followed by the EXACT terms, numbers, "
    "commands, identifiers, and proper nouns from the source — copied VERBATIM, not "
    "paraphrased. These are the anchors the coach must reference precisely."
)

# Off-hot-path generation budget: far larger than the warmup's 16 because this call
# is NOT on the voice loop (latency invisible to the user). COUPLED to BRIEF_TOKEN_BUDGET.
BRIEF_NUM_PREDICT: int = 2048

# Target size of the distilled brief, in tokens. COUPLED to the Modelfile num_ctx
# (pinned in 04-03) and to KB_MAX_TOKENS / KB_WARN_TOKENS (parse.py): the brief
# must fit the frozen-prefix budget once it lands in KB_SLOT.
BRIEF_TOKEN_BUDGET: int = 1500


class DistillError(Exception):
    """Typed failure of the distill network call (timeout / HTTP / empty output).

    Raised (not swallowed) so ``main._ingest_kb`` can surface a clear message and
    continue the session with the unchanged (empty KB) prefix (REL-03).
    """


def _resolved_llm_tag() -> str:
    """Read the pinned LLM tag from OLLAMA_MODEL (mirrors main.resolved_llm_tag —
    no hardcoded model tag).
    """
    tag = os.environ.get("OLLAMA_MODEL", "").strip()
    if not tag:
        raise DistillError("OLLAMA_MODEL is not set — run ollama/pull-and-pin.sh first")
    return tag


def build_distill_prompt(text: str) -> str:
    """PURE, deterministic distill prompt: the static instruction + the source text.

    The only interpolation is over ``DISTILL_INSTRUCTION`` (a frozen constant) and
    the input ``text``. No volatile data; identical input -> identical bytes.
    """
    return f"{DISTILL_INSTRUCTION}\n\n---\n{text}\n---"


def distill(text: str) -> str:
    """One off-hot-path Ollama call: source text -> compact brief + FACTS anchors.

    Streams from ``OLLAMA_GENERATE_URL`` with ``think=false`` and a generous
    ``num_predict`` (off the voice loop). Accumulates ``response`` chunks until
    ``done``. Requests no structured-output schema (Ollama #15260). Raises
    ``DistillError`` on any network/timeout failure or empty output.
    """
    payload = {
        "model": _resolved_llm_tag(),
        "prompt": build_distill_prompt(text),
        "stream": True,
        "think": False,
        "options": {"num_predict": BRIEF_NUM_PREDICT},
    }
    brief_parts: list[str] = []
    try:
        with httpx.Client(timeout=None) as client:
            with client.stream("POST", OLLAMA_GENERATE_URL, json=payload) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    piece = chunk.get("response")
                    if piece:
                        brief_parts.append(piece)
                    if chunk.get("done"):
                        break
    except httpx.HTTPError as exc:
        raise DistillError(f"distill request failed: {exc}") from exc
    brief = "".join(brief_parts).strip()
    if not brief:
        raise DistillError("distill produced no output")
    return brief
