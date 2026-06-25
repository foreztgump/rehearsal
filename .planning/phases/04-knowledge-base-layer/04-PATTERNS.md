# Phase 4 Patterns: Knowledge Base Layer

**Status:** NOT greenfield — every touched seam has a strong in-repo analog. Phase 1/2/3
built the full `AgentSession` (`agent/main.py`), the pure-testable `render_persona` with the
**already-empty `KB_SLOT` seam** (`agent/persona.py:78`), the per-turn metrics contract
(`agent/metrics.py`, `llm_ttft_ms` keyed by `speech_id`), the RPC control channel + the
`lk.agent.state` participant-attribute read pattern (`AgentStatePill.tsx`), and the thin
inline-styled side panel (`PersonaPanel.tsx`). Phase 4 is **"fill the `KB_SLOT` seam once
per session from a distilled brief, fed by a byte-stream upload + parser, with a status
panel and an ephemeral teardown — without busting the frozen prefix."**

Net-new files: a small `agent/kb/` package (parser, gate/guard, distiller) + `web/app/KbPanel.tsx`.
Everything else MODIFIES a live analog (`persona.py`, `main.py`, `VoiceRoom.tsx`,
`requirements.txt`, `Dockerfile`, `ollama/Modelfile`).

**Source of file list:** `04-RESEARCH.md` §10 (plan-by-plan) + §7/§8 + the roadmap three-plan
split (no CONTEXT.md — proceed without). Plans: **04-01** (upload transport + parser + gate +
size guard + parse-failure handling), **04-02** (distill → inject once via `KB_SLOT` +
indicator + ephemeral teardown), **04-03** (prefix-cache + VRAM verification — operator/VM gate).

**Core discipline (carried from Phase 1/2/3, do not break):**
- **Byte-stability of the frozen prefix is THE keystone constraint** (Pitfall 7). The KB brief
  is injected **ONCE per session**, then FROZEN. No re-distill / re-inject per turn; no
  timestamps / counters / re-serialized JSON / whitespace drift in the brief string.
- **Persona edit and KB load MUST compose, not clobber.** The Phase-3 hot-swap handler
  (`handle_persona_update`, `main.py:241`) re-renders the prefix on every persona edit; after
  Phase 4 it must re-emit the **current KB brief** too (else editing persona drops the KB).
  Both are sanctioned one-time re-prefills — the "epoch" model extends to (persona × KB).
- **Metrics contract is frozen** (`agent/metrics.py`): per-turn key set
  `{eou_ms,stt_ms,llm_ttft_ms,tts_ttfb_ms,e2e_ms,over_budget}` must NOT change. 04-03 READS
  `llm_ttft_ms` (turn-1 vs turn-2) as the flat-TTFT proof — do not edit the emitter.
- **Local-first / no egress (PERF-03):** files ride the existing LiveKit room data plane as
  byte streams — no new HTTP endpoint, nothing leaves the LAN. KB is **ephemeral**, in worker
  memory only; any temp file deleted in a `finally` (KB-06).
- **Boundary discipline (CODE_PRINCIPLES §4):** KB upload/parse/distill is a named boundary —
  no bare except, no silent swallow. Every failure sets `kb.state` error and the voice loop
  continues with the **unchanged** prefix (empty `KB_SLOT`).
- **`OLLAMA_MODEL` is the single LLM-tag source**; distillation reuses `resolved_llm_tag()` /
  `OLLAMA_BASE_URL` (no second hardcoded tag). Pin new deps tight (no `:latest`).
- **Sandbox cannot import livekit / no browser / GPU / Ollama.** Every claim touching the
  installed build is `[VM-INTROSPECT]` (defer like 02/03). Pure pieces — parser, extraction
  gate, size guard, distill-prompt builder, `render_prompt` byte-stability — ARE
  sandbox-verifiable and become the client-verifiable acceptance criteria.

---

## Planned files (extracted from RESEARCH §10 + plan split)

| # | File (path) | Role | Data flow | In-repo analog | Plan |
|---|-------------|------|-----------|----------------|------|
| 1 | `agent/kb/parse.py` *(new)* | Compute / pure | `parse(name, mime, raw) -> ParsedDoc`; type dispatch (pdf/txt/md/docx); UTF-8/BOM normalize; extraction-quality gate (alpha-ratio/non-empty); token-count size guard; typed errors; `_self_check()` over fixture bytes | **`agent/metrics.py`** / **`agent/persona.py`** (pure module: dataclasses, frozen constants, `_self_check()` under `if __name__=="__main__"`) | 04-01 |
| 2 | `agent/kb/distill.py` *(new)* | Compute (LLM) + pure builder | `build_distill_prompt(text) -> str` (PURE, testable) + `distill(text) -> str` (one off-hot-path Ollama call → brief + verbatim fact-anchors); `#15260`-safe plain-text output parsing | **`main.py:_warmup_llm_ttft_ms`** (httpx stream to `OLLAMA_GENERATE_URL`, `think=false`, `num_predict`) | 04-02 |
| 3 | `agent/kb/__init__.py` *(new)* | Package seam | Exports `parse`, `distill`, `ParsedDoc`, error types, KB constants | n/a (trivial) | 04-01 |
| 4 | `agent/persona.py` | Compute / pure config | Add `kb_brief` param → `render_prompt(persona, kb_brief="")` (or extend `render_persona`) filling the **existing `KB_SLOT`** seam (line 78/117); update `EXPECTED_DEFAULT` only if empty render shifts (it must NOT); extend `_self_check` for `kb_brief=""` + a fixed brief | **self** — `render_persona` + `KB_SLOT` + golden `_self_check` already built FOR this | 04-02 |
| 5 | `agent/main.py` | Orchestration / compute | `register_byte_stream_handler("kb.upload", ...)` after `ctx.connect()`; `_active_tasks` GC-guard; per-session KB state (in-memory); ingest→parse→gate→guard→distill→inject `render_prompt(p, brief)`; set `kb.state` attribute; **priming turn**; update `handle_persona_update` to carry current brief; teardown | **self** — `entrypoint`, `handle_persona_update` (RPC analog), `set_attributes` (mirror `lk.agent.state`) | 04-01 / 04-02 |
| 6 | `web/app/KbPanel.tsx` *(new)* | Frontend / upload + indicator | File picker → loop `localParticipant.sendFile(file, {topic:"kb.upload"})`; read `kb.state` participant attribute → status union `idle→uploading→parsing→distilling→ready(n)/error` + doc count (KB-07) + clear errors (REL-03) | **`PersonaPanel.tsx`** (thin `"use client"`, inline-styled, `useRoomContext`) + **`AgentStatePill.tsx`** (reads a participant attribute) | 04-01 / 04-02 |
| 7 | `web/app/VoiceRoom.tsx` | Frontend / room shell | Mount `<KbPanel />` beside `<PersonaPanel/>`/`<Transcript/>` **inside** `<LiveKitRoom>` (needs room context for `sendFile` + attribute read) | **self** — already composes the flex panel row (lines 82-85) | 04-01 |
| 8 | `agent/requirements.txt` | Deps | Add `pymupdf4llm` (+ `pymupdf`), `python-docx`, pinned (`pymupdf~=1.27`, `python-docx~=1.1`) | **self** — pinned-deps list | 04-01 |
| 9 | `agent/Dockerfile` | Build | `COPY` the `kb/` package alongside `metrics.py persona.py main.py` (line 28) | **self** — explicit `COPY` of agent modules | 04-01 |
| 10 | `ollama/Modelfile` | Model / config | Bump `PARAMETER num_ctx 8192` → measured worst case (persona + KB brief budget + history + headroom); update the line-14-18 comment that already forecasts this | **self** — the comment literally says *"grows in Phase 4 when the distilled KB brief lands"* | 04-03 |
| 11 | `agent/metrics.py` | Observability | **No code change** — 04-03 READS `llm_ttft_ms` turn-1 vs turn-2 as the flat-TTFT proof; keys frozen | **self** — REUSE AS-IS | (contract only) |
| 12 | `scripts/vram-validate.sh` | Ops / verify | **Reuse** — re-run WITH a KB loaded (peak-memory moment); document commands; operator gate | **self** — existing q8_0/VRAM validator | 04-03 |

> `AgentStatePill.tsx`, `Transcript.tsx`, `web/app/api/token/route.ts` are **READ-ONLY analogs**
> — they do not change. The KB status is a **separate panel** reading a **separate `kb.state`
> attribute**, NOT overloaded onto the global agent-state pill.

---

## Role / data-flow classification

**Compute (pure, testable) — #1 `agent/kb/parse.py` + #2 `build_distill_prompt`:** bytes →
`ParsedDoc` (dispatch + normalize + gate + guard) and text → distill-prompt string are pure
functions over fixtures. Zero livekit import → fully sandbox-verifiable, exactly like
`metrics.py`/`persona.py`. These carry the client-verifiable acceptance criteria.

**Compute (LLM, off hot path) — #2 `distill()`:** one Ollama pass at setup time. Latency is
invisible (not on the voice loop), so a bigger `num_predict` + careful prompt are fine. Reuses
the resident model via the `_warmup_llm_ttft_ms` httpx-stream style.

**Config (pure) — #4 `agent/persona.py`:** the `KB_SLOT` seam already exists and already
renders to a trailing empty segment. Adding a `kb_brief` param that fills that slot is the
*minimal, byte-stable* change the Phase-3 design pre-engineered. `render_prompt(p, "")` MUST
be byte-identical to today's `render_persona(p)` (regression-protected by the golden).

**Transport-in (browser → agent) — #6 → byte stream → #5:** `sendFile(topic:"kb.upload")`
client-side → `register_byte_stream_handler("kb.upload", ...)` agent-side. One-way (client→agent).

**Control-out (agent → browser) — #5 → attribute → #6:** byte streams are one-way, so the
ack/error/doc-count travels back via a **`kb.state` participant attribute** the panel reads —
the **same pattern** `AgentStatePill` already uses for `lk.agent.state`. Proven in-repo.

**Orchestration / lifecycle — #5 `agent/main.py`:** owns the in-memory per-session KB state
(list of parsed docs + current brief), runs the ingest pipeline, injects once via
`render_prompt`, fires the priming turn, composes with persona edits, tears down on job end.

**Observability — #11 `agent/metrics.py`:** untouched. Turn-1 after KB inject shows an elevated
`llm_ttft_ms` (sanctioned re-prefill); turn-2+ ≪ turn-1 is the KB-05 proof (04-03 reads it).

---

## Pattern A — Pure parser + gate + guard (file #1 `agent/kb/parse.py`) — 04-01

**Analog — `agent/metrics.py` / `agent/persona.py` are the template for a pure, testable,
livekit-free module:** frozen module-level constants, `@dataclass`, typed returns, and a
`_self_check()` under `if __name__ == "__main__":` (`python3 agent/kb/parse.py`). Mirror exactly.

### A1 — Typed result + per-type dispatch (KB-01)
Dispatch by mime/extension; return a `ParsedDoc` or a **typed error** (never raise across the
boundary — the failure matrix §4 maps each to a `kb.state` message).
```python
from __future__ import annotations
from dataclasses import dataclass

SUPPORTED = ("pdf", "txt", "md", "docx")

@dataclass
class ParsedDoc:
    name: str
    text: str          # normalized UTF-8, BOM/smart-quote cleaned
    token_estimate: int

@dataclass
class KbParseError:
    name: str
    reason: str        # "unsupported" | "scanned" | "corrupt" | "oversize"
    message: str       # the user-facing clear error (REL-03)

def parse(name: str, mime: str, raw: bytes) -> ParsedDoc | KbParseError:
    kind = _kind(name, mime)
    if kind not in SUPPORTED:
        return KbParseError(name, "unsupported", "Unsupported file type — use PDF/TXT/MD/DOCX")
    text = _extract(kind, raw)          # pdf→pymupdf4llm, docx→python-docx, txt/md→decode
    text = _normalize(text)             # UTF-8, strip BOM + smart-quote artifacts
    gate = _extraction_gate(text)       # A2
    if gate is not None:
        return KbParseError(name, gate.reason, gate.message)
    return ParsedDoc(name=name, text=text, token_estimate=_estimate_tokens(text))
```
> **DOCX is NOT free via pymupdf4llm** (Pitfall §3.2 — needs paid PyMuPDF Pro). Use
> `python-docx`: `Document(io.BytesIO(raw))`, join `doc.paragraphs` **and** iterate `doc.tables`
> explicitly (tables extract out of order if ignored, Pitfall 14). PDF/TXT/MD are free.

### A2 — Extraction-quality gate (Pitfall 14, REL-03) — pure & testable
Detect empty/scanned/garbage **before** distillation via a **low alpha-character ratio** /
near-empty check. A scanned 200-page PDF is ~0 useful tokens → clear error, doc skipped.
```python
ALPHA_RATIO_FLOOR = 0.50     # named constant (CODE_PRINCIPLES §2)
MIN_USEFUL_CHARS  = 32

def _extraction_gate(text: str) -> KbParseError | None:
    stripped = text.strip()
    if len(stripped) < MIN_USEFUL_CHARS:
        return KbParseError("", "scanned", "Couldn't extract text (looks scanned)")
    alpha = sum(c.isalpha() for c in stripped) / len(stripped)
    if alpha < ALPHA_RATIO_FLOOR:
        return KbParseError("", "scanned", "Couldn't extract text (looks scanned)")
    return None
```

### A3 — Size guard on EXTRACTED TOKENS, not file bytes (KB-08, §5)
Two named thresholds, coupled to the brief budget + `num_ctx` (Pattern F). Over `WARN` →
distill harder; over `MAX` → reject that doc with a clear error and continue.
```python
CHARS_PER_TOKEN = 4              # cheap estimate; a real tokenizer is optional
KB_WARN_TOKENS  = 6000           # over → distill more aggressively (KB-08)
KB_MAX_TOKENS   = 24000          # hard cap → reject doc (REL-03); v2 reserves true RAG

def _estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN
```

### A4 — `_self_check()` over fixture bytes (mirror `metrics.py:269` / `persona.py:154`)
Pure stdlib, runs in the sandbox. Assert: each of pdf/txt/md/docx fixture → `ParsedDoc`;
a near-empty/low-alpha fixture → `scanned` error; an unsupported type → `unsupported`; an
oversize fixture → `oversize`. **No livekit import** for the pure parts (PDF/DOCX libs are
the only new deps — keep the parse functions importable without livekit).
```python
def _self_check() -> None:
    assert isinstance(parse("a.txt", "text/plain", b"hello world ..."), ParsedDoc)
    assert parse("x.bin", "application/octet-stream", b"..").reason == "unsupported"
    assert parse("scan.txt", "text/plain", b"\x00\x01\x02").reason == "scanned"
    print("kb.parse _self_check OK", file=sys.stderr)

if __name__ == "__main__":
    _self_check()
```

---

## Pattern B — Distillation: one off-hot-path Ollama call (file #2 `agent/kb/distill.py`) — 04-02

**Analog — `main.py:_warmup_llm_ttft_ms` (lines 73-102):** httpx stream to
`OLLAMA_GENERATE_URL` with `{"model": tag, "prompt": ..., "stream": True, "think": False,
"options": {"num_predict": N}}`. Distillation is the same shape with a bigger `num_predict`
and a careful prompt — latency is invisible here (NOT the voice loop).

### B1 — `build_distill_prompt(text)` is PURE and testable
Split the prompt builder (pure string) from the network call so the sandbox can test it.
```python
DISTILL_INSTRUCTION = (
    "Summarize the following material for a spoken coaching session. Produce (1) a compact "
    "domain brief in plain prose, and (2) a 'FACTS:' list of EXACT terms, numbers, commands, "
    "and identifiers copied VERBATIM (do not paraphrase)."
)
BRIEF_TOKEN_BUDGET = 1500        # coupled to num_ctx (Pattern F)

def build_distill_prompt(text: str) -> str:
    return f"{DISTILL_INSTRUCTION}\n\n---\n{text}\n---"
```

### B2 — `distill()` reuses the resident model
```python
def distill(text: str) -> str:
    payload = {
        "model": resolved_llm_tag(), "prompt": build_distill_prompt(text),
        "stream": True, "think": False,                 # thinking OFF (consistency)
        "options": {"num_predict": 2048},               # bigger — off hot path
    }
    # httpx stream to OLLAMA_GENERATE_URL, accumulate chunk["response"]; return the brief
```
> **#15260 (Modelfile:30):** `think=false` + `format=json` silently drops the JSON constraint
> for gemma4. **Do NOT rely on `format=json`.** Parse a delimited/markdown structure out of
> plain text (the `FACTS:` delimiter above) — robust, MVP-recommended. JSON mode is
> `[VM-INTROSPECT]` only-if-wanted (verify #15260 fixed on Ollama 0.6.8 first).
> The output string becomes the `kb_brief` — it must be **byte-stable** (no timestamps).

---

## Pattern C — Fill the `KB_SLOT` seam (file #4 `agent/persona.py`) — 04-02

**The seam already exists and was BUILT for this** (`persona.py:76-78`, `:104-118`,
`03-PATTERNS.md` Pattern A2). `KB_SLOT: str = ""` is the empty trailing segment; `render_persona`
joins it last. Phase 4 fills it via a **session-frozen brief param**.

### C1 — Add a `kb_brief` param (RESEARCH §8 option 1 — PREFERRED)
Keep `render_persona(p)` byte-identical for the empty case; add `render_prompt(p, kb_brief="")`
(or extend the signature). The brief replaces the empty `KB_SLOT` constant in the SAME position.
```python
def render_prompt(p: Persona, kb_brief: str = "") -> str:
    """Byte-stable prompt with an optional session-frozen KB brief in the KB slot."""
    return " ".join((
        p.role_text or ROLE_PREAMBLE,
        DIFFICULTY[p.difficulty],
        VERBOSITY[p.verbosity],
        CORRECTION[p.correction],
        SPOKEN_STYLE_FOOTER,
        kb_brief or KB_SLOT,            # "" → identical bytes to today's render (regression-safe)
    ))
```
> **Why a param, not a module-level mutable:** keeping a hidden global `KB_SLOT` and mutating
> it would break the pure-function byte-stability test (RESEARCH §8 option 2 — AVOID).

### C2 — Golden + `_self_check` must stay green (mirror `persona.py:154-191`)
`render_prompt(DEFAULT_PERSONA, "")` MUST equal the existing `EXPECTED_DEFAULT` (line 136) —
the empty-KB render is byte-unchanged, so the regression stays green. Add two assertions: the
empty-brief equivalence, and a **fixed non-empty brief** rendering deterministically (same
brief twice → identical bytes; the brief lands at the slot position).
```python
assert render_prompt(DEFAULT_PERSONA, "") == EXPECTED_DEFAULT, "empty-KB render drifted"
FIXED = "DOMAIN BRIEF: ... FACTS: CVE-2021-1234, --flag, port 8443."
assert render_prompt(DEFAULT_PERSONA, FIXED) == render_prompt(DEFAULT_PERSONA, FIXED)
assert FIXED in render_prompt(DEFAULT_PERSONA, FIXED)
```

---

## Pattern D — Byte-stream ingest + inject + compose (file #5 `agent/main.py`) — 04-01 / 04-02

### D1 — Register the byte-stream handler (04-01, RESEARCH §1.1)
Register **after `ctx.connect()`** (same placement rule as the persona RPC at `main.py:249`).
Keep a module/closure `_active_tasks` list to prevent GC of the read task (docs-mandated).
```python
_active_tasks: list[asyncio.Task] = []

def _on_kb_stream(reader, participant_identity):
    task = asyncio.create_task(_ingest_kb(reader, participant_identity))
    _active_tasks.append(task)
    task.add_done_callback(lambda t: _active_tasks.remove(t))

# inside entrypoint, after session.start(...):
ctx.room.register_byte_stream_handler("kb.upload", _on_kb_stream)
```
> `[VM-INTROSPECT]` (defer — do NOT mark passed in a plan):
> ```
> python -c "from livekit import rtc; print([m for m in dir(rtc.Room) if 'byte_stream' in m or 'stream' in m])"
> python -c "from livekit import rtc; print([m for m in dir(rtc.LocalParticipant) if 'file' in m.lower() or 'stream' in m.lower()])"
> python -c "import pymupdf4llm, inspect; print(inspect.signature(pymupdf4llm.to_markdown))"
> ```
> Confirm: `register_byte_stream_handler` exists on the installed `rtc.Room`; the reader is
> async-iterable with `reader.info` (`.name`, `.mimeType`, `.size`); `sendFile` on the pinned
> `livekit-client@2.20.x`. **Fallback** if `register_byte_stream_handler` is absent: the
> text/data-stream handler with chunked base64 (worse) — decide in 04-01 after introspection.

### D2 — Ingest pipeline + inject ONCE (04-01 parse / 04-02 distill+inject)
```python
async def _ingest_kb(reader, participant_identity):
    info = reader.info
    raw = bytes()
    async for chunk in reader:
        raw += chunk
    await _set_kb_state(status="parsing")
    result = kb.parse(info.name, info.mimeType, raw)      # Pattern A
    if isinstance(result, kb.KbParseError):
        await _set_kb_state(status="error", error=result.message)   # REL-03, prefix unchanged
        return
    _session_kb.docs.append(result)
    await _set_kb_state(status="distilling")
    brief = kb.distill(_concat(_session_kb.docs))          # Pattern B (off hot path)
    _session_kb.brief = brief
    await agent.update_instructions(render_prompt(_current_persona, brief))  # ONE re-prefill
    await _set_kb_state(status="ready", docs=len(_session_kb.docs))          # KB-07
    await _prime(session)                                  # Pattern E
```
- **Inject ONCE** via `agent.update_instructions(render_prompt(persona, brief))` — the single
  sanctioned re-prefill (mirrors the persona hot-swap at `main.py:244`). After this the prefix
  is FROZEN; every turn reuses the cache (KB-05).
- **In-memory only** (KB-06): `_session_kb` is a small worker object; nothing persisted. If a
  temp file is written during parse, delete it in `finally`.

### D3 — Compose with persona edits — UPDATE `handle_persona_update` (04-02, RESEARCH §8)
The Phase-3 handler (`main.py:241-246`) currently calls `render_persona(p)`; it must carry the
**current brief** so a persona edit re-emits the SAME KB (else editing persona drops the KB).
```python
async def handle_persona_update(data):
    snapshot = json.loads(data.payload)
    p = Persona(**snapshot)
    _current_persona = p                                   # remember for KB re-inject
    await agent.update_instructions(render_prompt(p, _session_kb.brief))  # was render_persona(p)
    session.tts.update_options(voice=p.voice_id)
    return "applied"
```
> Persona edit and KB load are BOTH one-time re-prefills; they must compose (the prefix is now
> keyed by persona × KB epoch), not clobber. Don't auto-edit either per turn (Pitfall 7).

### D4 — `kb.state` participant attribute (ack channel, RESEARCH §1.1) — analog `lk.agent.state`
Byte streams are one-way, so the panel learns status from an attribute the agent sets — the
exact pattern `AgentStatePill` reads (`lk.agent.state`). JSON value: `{docs, status, error}`.
```python
async def _set_kb_state(*, status, docs=0, error=""):
    await ctx.room.local_participant.set_attributes(
        {"kb.state": json.dumps({"status": status, "docs": docs, "error": error})}
    )
```
> `[VM-INTROSPECT]` confirm `set_attributes` (or `set_attribute`) on the installed
> `rtc.LocalParticipant`; confirm the browser observes attribute changes (the
> `useVoiceAssistant().state` proves the read side works for `lk.agent.state`).

### D5 — Ephemeral teardown (KB-06)
KB lives only in `_session_kb` for the job lifetime; it drops when the job ends / room
disconnects (sticky single-worker session). No disk/db writes. Any temp file → `finally`-delete.
Phase 7 (SESS-03) does the formal teardown audit; Phase 4 must create **no persistent state**.

---

## Pattern E — Priming turn to warm the KB prefill (Pitfall 3) — 04-02

`OLLAMA_KEEP_ALIVE=-1` keeps the model resident, but the new KB-prefix must be prefilled once.
After injection, fire **one priming generation** (like the startup warmup `_warmup_llm_ttft_ms`
and the greeting `session.generate_reply` at `main.py:253`) so the user's first *real* turn is
warm, not a cold full-prefill — fired while the panel shows "ready".
```python
async def _prime(session):
    await session.generate_reply(instructions="(internal) acknowledge the loaded material briefly")
```
> Decide in 04-02 whether the priming reply is spoken or suppressed; the goal is the prefill, not
> a user-visible utterance. `[VM-INTROSPECT]` whether a silent prime is supported.

---

## Pattern F — `num_ctx` ↔ brief-budget coupling (file #10 `ollama/Modelfile`) — 04-03

**The Modelfile already forecasts this** (`Modelfile:14-18`): *"8192 is ample for Phase 1 (no
KB yet); this grows in Phase 4 when the distilled KB brief lands in the frozen prefix."*
Ollama **pre-allocates the full `num_ctx` KV cache upfront** — every extra 1k is reserved VRAM
against the 16GB floor. `BRIEF_TOKEN_BUDGET` (Pattern B), `KB_MAX_TOKENS` (Pattern A3), and
`num_ctx` are **coupled constants — set them together**:

```
num_ctx ≈ persona(~250) + KB brief budget(~1500) + max history window + headroom
```
- Keep the brief small (~1–2k tokens) so `num_ctx` stays modest (8192 may still suffice, or a
  measured bump). **Measure the real distilled-brief token count on the VM**, then pin `num_ctx`
  tightly. `q8_0` KV + flash-attn (compose env, verified) halve KV memory and make the bump
  affordable.
- **04-03 re-runs `scripts/vram-validate.sh` WITH a KB loaded** — the peak-memory moment.
  Confirm q8_0 still engaged + 3 GPU procs co-resident under 16GB. This is the "KB-load VRAM
  re-check" plan item (operator/VM gate).
> `[VM-INTROSPECT]`: measure brief tokens → set `num_ctx`; re-run VRAM validate with KB loaded.

---

## Pattern G — KB upload + indicator panel (file #6 `web/app/KbPanel.tsx`) — 04-01 / 04-02

**Analog — `PersonaPanel.tsx` (thin `"use client"`, inline-styled, `useRoomContext`) +
`AgentStatePill.tsx` (reads a participant attribute → colored status).** Compose these; don't
hand-roll `livekit-client` plumbing.

### G1 — Upload: loop `sendFile` over the picked FileList (KB-01, multi-file §1.3)
```tsx
"use client";
import { useRoomContext } from "@livekit/components-react";
import { useState } from "react";

export default function KbPanel() {
  const room = useRoomContext();
  const [status, setStatus] = useState<"idle"|"uploading"|"parsing"|"distilling"|"ready"|"error">("idle");
  const [docs, setDocs] = useState(0);
  const [error, setError] = useState("");

  async function upload(files: FileList) {
    setStatus("uploading");
    for (const file of Array.from(files)) {
      await room.localParticipant.sendFile(file, { topic: "kb.upload" }); // per-file stream
    }
  }
  // <input type="file" accept=".pdf,.txt,.md,.docx" multiple onChange=... />
}
```

### G2 — Indicator: read the `kb.state` attribute (KB-07, REL-03) — mirror `AgentStatePill`
The agent pushes `kb.state` (Pattern D4); the panel subscribes to participant-attribute changes
and renders `idle→uploading→parsing→distilling→ready (n docs) | error`. Errors are shown
verbatim (clear error, REL-03). Mirror the inline `STATUS_LABEL`/`STATUS_COLOR` style of
`PersonaPanel.tsx:33-45`.
```tsx
// useParticipantAttributes / room "attributesChanged" → parse JSON → setStatus/setDocs/setError
```
> `[VM-INTROSPECT]` confirm `sendFile` + the participant-attribute change event on the pinned
> `livekit-client@2.20.x`. **No file leaves the LAN** (PERF-03) — it rides the existing room
> connection to the sticky worker.

---

## Pattern H — Mount the panel in the room shell (file #7 `web/app/VoiceRoom.tsx`) — 04-01

**Analog — the existing flex panel row (`VoiceRoom.tsx:82-85`):**
```tsx
<div style={{ display: "flex", gap: "1rem", alignItems: "flex-start", marginTop: "1rem" }}>
  <PersonaPanel />
  <KbPanel />        {/* new — INSIDE LiveKitRoom for room context (sendFile + attribute read) */}
  <Transcript />
</div>
```

---

## Pattern I — Metrics contract frozen; flat-TTFT proof (file #11 `agent/metrics.py`) — 04-03

No code change. The KB-inject turn shows an **elevated `llm_ttft_ms`** (cold prefix re-prefill)
and correctly flags `over_budget: ["llm_ttft"]` for that ONE turn — **expected, do not "fix"**
(same as the Phase-3 persona-swap turn). 04-03 READS the per-turn `llm_ttft_ms`
(`metrics.py:69,176`) to prove **Success Criterion 3 / KB-05**: with a large KB loaded,
**turn-2+ `llm_ttft_ms` ≪ turn-1** and ≈ no-KB turn-2 (flat). Cross-check Ollama prompt-eval
logs for a small turn-2 "new tokens" count (a full re-eval = Pitfall 7 cache-bust warning).
The frozen key set (`metrics.py:284`) must stay byte-identical.

---

## Parse-failure matrix (REL-03, RESEARCH §4) — wire each to `kb.state` error

| Failure | Detect (Pattern A) | `kb.state` message | Session continues? |
|---|---|---|---|
| Unsupported type | mime/ext ∉ {pdf,txt,md,docx} | "Unsupported file type — use PDF/TXT/MD/DOCX" | yes, no KB |
| Scanned/empty PDF | near-zero text / low alpha ratio | "Couldn't extract text (looks scanned)" | yes, doc skipped |
| Corrupt / parser raises | exception at extract (caught at boundary) | "Couldn't read this file" | yes, doc skipped |
| Oversize | `token_estimate > KB_MAX_TOKENS` | "Too large for inline KB — trimmed/skipped" | yes (distill harder or skip) |
| Distillation failure | Ollama error/timeout | "Couldn't build the brief — continuing without KB" | yes, no KB |

**Hard rule (CODE_PRINCIPLES §4):** named boundary — no bare except, no silent swallow. Each
path sets the `kb.state` error and the voice loop keeps running with the **unchanged** prefix
(`KB_SLOT` stays empty / `kb_brief=""`). The default-trainer behavior (KB-04 "no KB → doesn't
reference user material") is the natural fallback.

---

## The "(persona × KB) epoch" model (carry into both plans) — extends RESEARCH §8 / 03 §3.4

Within a session the frozen prefix is `[persona] + [KB brief] + [history] + [turn]`, frozen
until the user **edits persona** OR **loads/changes the KB**. Each is a **user-initiated,
one-time re-prefill** (the sanctioned "applying…"/"loading…" turn); after it, the prefix is
frozen again and caches from the turn after. The two must **compose** — a persona edit re-emits
the current brief (Pattern D3); a KB load re-emits under the current persona (Pattern D2). Never
silent per-turn busting. This is exactly what the byte-stability tests (A4, C2) and
`render_prompt` (C1) protect, and the seam Phase 5's history management will sit *behind*.

---

## Notes for the planner

- **Reuse, don't re-plumb.** The `KB_SLOT` seam, the RPC/attribute control plane, the metrics
  `attach()` surface, the `<LiveKitRoom>` shell, and the flex panel row are DONE — extend only.
  Net-new: the `agent/kb/` package + `KbPanel.tsx`.
- **04-01 pure core is sandbox-verifiable:** `python3 agent/kb/parse.py` self-check (dispatch +
  gate + guard over fixtures), `build_distill_prompt` determinism, `next build` clean with the
  upload UI. The byte-stream round-trip + parser-on-real-PDF/DOCX are **operator gates** (VM).
- **04-02 sandbox acceptance:** `render_prompt(p, "")` == golden (empty-KB byte-unchanged);
  `render_prompt(p, FIXED)` deterministic; distill-prompt builder pure-testable; panel renders.
  **Operator gates:** upload → parsed → distilled → brief references the doc; indicator shows
  count; persona edit keeps the KB; end session → KB gone.
- **04-03 is operator/VM-only** (the keystone proof): turn-1 vs turn-2 `llm_ttft_ms` with a
  large KB; Ollama prompt-eval cache-hit check; VRAM re-validate WITH KB loaded; pin `num_ctx`.
  Document exact commands; defer like the Phase-1 VRAM gate and 02/03 `[VM-INTROSPECT]` items.
- **Coupled constants — set together (Pattern F):** `BRIEF_TOKEN_BUDGET` (B1), `KB_WARN_TOKENS`/
  `KB_MAX_TOKENS` (A3), `num_ctx` (Modelfile). Pin after measuring real brief tokens on the VM.
- **#15260 (Modelfile:30):** do NOT depend on `format=json` with `think=false`; parse delimited
  plain text. JSON mode only if introspection confirms the bug is fixed on Ollama 0.6.8.
- **DOCX via `python-docx` only** (PyMuPDF Pro is paid). PDF/TXT/MD free via pymupdf4llm/stdlib.
- **No second hardcoded LLM tag** — distill resolves the model from `OLLAMA_MODEL` via
  `resolved_llm_tag()`. New deps pinned tight (no float).
- **Defer every `[VM-INTROSPECT]` (do not mark passed in a plan)** — byte-stream/`sendFile`
  signatures, `set_attributes`, pymupdf4llm signature, #15260, brief token count, flat-TTFT,
  VRAM re-check. Consolidated checklist in RESEARCH §11.

## Requirement → mechanism map (from RESEARCH §10.4)

| Req | Mechanism | Files |
|---|---|---|
| KB-01 (upload PDF/TXT/MD/DOCX) | `sendFile(topic:"kb.upload")` → `register_byte_stream_handler` → per-type `parse()` | #6 → #5 → #1 |
| KB-02 (distill to brief at upload) | one setup-time Ollama pass → brief + fact-anchors | #2 ← #5 |
| KB-03 (load once into prefix/KV) | `render_prompt(persona, brief)` fills `KB_SLOT`, frozen for session | #4 ← #5 |
| KB-04 (grounding vs none) | verbatim fact-anchors; empty `kb_brief` = default behavior | #2, #4 |
| KB-05 (flat TTFT) | inject once + Ollama prefix cache + `keep_alive=-1`; verified turn-1 vs turn-2 | #5, #11, #12 |
| KB-06 (ephemeral) | in-memory `_session_kb`; temp-file `finally`-delete; no persistence | #5 |
| KB-07 (active indicator + doc count) | `KbPanel` reads `kb.state` attribute | #6 ← #5 |
| KB-08 (size guard / distill harder) | token-count guard `KB_WARN_TOKENS`/`KB_MAX_TOKENS` | #1, #2 |
| REL-03 (failed upload → clear error, continue) | failure matrix → `kb.state` error, empty `KB_SLOT` fallback | #1 → #5 → #6 |

## Build order (vertical slices, from RESEARCH §10)
1. **04-01** — `agent/kb/parse.py` (dispatch + gate + guard + `_self_check`) + deps/Dockerfile;
   `register_byte_stream_handler` + `kb.state` attribute in `main.py`; `KbPanel.tsx` upload +
   indicator; mount in `VoiceRoom`. Pure parser testable in the sandbox; transport = VM gate.
2. **04-02** — `agent/kb/distill.py` (pure builder + Ollama call); `render_prompt(p, kb_brief)`
   in `persona.py` (+ golden/`_self_check`); ingest→distill→inject-once + priming turn in
   `main.py`; compose with `handle_persona_update`; indicator doc count + ephemeral teardown.
3. **04-03** — operator/VM: turn-1 vs turn-2 `llm_ttft_ms` flat-TTFT proof + Ollama cache-hit
   check; pin `num_ctx` (Modelfile); re-run `scripts/vram-validate.sh` WITH KB loaded.

**Phase-4 done = an ephemeral per-session KB** uploaded over byte streams, parsed/gated/guarded,
distilled once into a byte-stable brief injected once into the frozen `KB_SLOT`, with a doc-count
indicator, clear failure handling, ephemeral teardown, and the flat-TTFT invariant proven
(turn-2 ≪ turn-1 with a large KB) under the 16GB floor.

---
*Phase 4 patterns — mostly MODIFY against live Phase-1/2/3 analogs (the `KB_SLOT` seam, RPC/
attribute plane, metrics contract were pre-built for this); net-new is the `agent/kb/` package +
`KbPanel.tsx`. Live-build/model claims tagged `[VM-INTROSPECT]` for the VM. Keystone risk =
prefix-cache byte-stability (Pitfall 7).*
