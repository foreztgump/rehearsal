# Phase 4 Research: Knowledge Base Layer

**Phase:** 04-knowledge-base-layer (MVP mode — vertical slices)
**Researched:** 2026-06-25
**Requirements:** KB-01, KB-02, KB-03, KB-04, KB-05, KB-06, KB-07, KB-08, REL-03
**Question answered:** *What do I need to know to PLAN this phase well?*

> **Grounding discipline (carried from Phases 2–3):** the sandbox CANNOT import
> `livekit` and has no Docker / GPU / browser / Ollama. Every LiveKit/Ollama API
> claim below is grounded in **published docs (current 1.5/1.6 line)** + the
> **source-verified Phase 2/3 memory** and the **working repo code**. Claims that
> touch the installed build or live models are tagged **[VM-INTROSPECT]** with the
> exact check to run on the Proxmox VM. Do NOT mark those passed in a plan; defer
> them like 02/03 did. The **pure** pieces (parser, distill-prompt builder, size
> guard, render-prefix byte-stability) ARE sandbox-verifiable and should be the
> client-verifiable acceptance criteria.

---

## 0. TL;DR — the shape of this phase

Phase 4 adds an **ephemeral, per-session knowledge base** that is **distilled once
at session start and injected once into the frozen prefix**, so KB cost is paid
only at prefill on turn 1 and the **flat-TTFT invariant** holds (turn-2 TTFT ≪
turn-1 even with a large KB). It is explicitly **inline-and-cache, NOT per-turn
RAG** (STATE decision, ARCHITECTURE Pattern 4, Anti-Pattern 2). Six moving parts:

1. **Upload transport** — browser → Python agent. Use **LiveKit byte streams**
   (`localParticipant.sendFile(...)` client-side → `room.register_byte_stream_handler(topic, ...)`
   agent-side). This is the *proven, in-stack, LAN-only* path (PERF-03) and reuses
   the existing room/RPC plane — no new HTTP upload endpoint, no file leaving the LAN.
2. **Parser** — bytes → clean text/markdown per type. **PDF/TXT/MD via `pymupdf4llm`/`pymupdf`**;
   **DOCX via `python-docx`** (pymupdf4llm's Office support needs paid PyMuPDF Pro — see §3.2).
3. **Extraction-quality gate** — detect empty / scanned / garbage extraction
   *before* distillation (Pitfall 14) and surface a clear error (REL-03).
4. **Size guard** — measured on **extracted token count**, not file bytes
   (Pitfall 9/14). Over budget → warn + distill harder (KB-08); way over → reject
   with a clear error and continue without the KB (REL-03).
5. **Setup-time distillation** — one Ollama LLM pass (latency invisible here)
   that turns raw text → a **compact domain brief + verbatim fact-anchors**
   (Pitfall 8). Reuse the resident model; off the hot path.
6. **Inject-once into the frozen prefix** — fill the existing **empty `KB_SLOT`**
   seam in `agent/persona.py:render_persona` so the brief sits at
   `[persona] + [KB brief] + [history] + [turn]`, byte-stable for the session
   (Pitfall 7). Then a **KB-active indicator** (doc count, KB-07), **ephemeral
   teardown** at session end (KB-06), and a **priming turn** to warm the KB prefill
   while the user reads "ready" (Pitfall 3).

The roadmap's three-plan split maps cleanly onto vertical slices:
- **04-01** = upload transport + parser + extraction gate + size guard + parse-failure handling (REL-03). *Mostly sandbox-testable as pure functions over fixture bytes.*
- **04-02** = distillation pass → compact brief → inject once via `KB_SLOT` + KB-active indicator + ephemeral teardown.
- **04-03** = prefix-cache invalidation verification (turn-2 TTFT ≪ turn-1) + KB-load VRAM re-check. *Operator/VM gate — the keystone proof.*

The single biggest design constraint (same as Phase 3) is **byte-stability of the
prefix**: the KB brief must be injected ONCE and then frozen for the session, or
Ollama re-prefills the whole brief every turn and the entire strategy collapses.

---

## 1. Upload transport: browser → Python agent

### 1.1 Recommended: LiveKit byte streams (`sendFile` / `register_byte_stream_handler`)

The room data plane already carries persona RPC and transcripts; files ride the
same connection as **byte streams** — the LiveKit-native file transport. No new
REST endpoint, no port, nothing leaves the LAN (PERF-03).

**Client (browser, `livekit-client`, inside `<LiveKitRoom>`):**
```ts
// File picker → sendFile on the local participant. topic routes to the agent handler.
await room.localParticipant.sendFile(file, {
  topic: "kb.upload",
  // optional: mimeType, name are carried in stream info
});
```

**Agent (Python, in `entrypoint` / on enter):**
```python
_active_tasks = []  # prevent GC of the read task (docs-mandated pattern)

def _on_kb_stream(reader, participant_identity):
    task = asyncio.create_task(_ingest_kb(reader, participant_identity))
    _active_tasks.append(task)
    task.add_done_callback(lambda t: _active_tasks.remove(t))

async def _ingest_kb(reader, participant_identity):
    info = reader.info            # info.name, info.mimeType, info.size (size only on sendFile)
    raw = bytes()
    async for chunk in reader:
        raw += chunk
    # parse → gate → guard → distill → inject (Plans 04-01/04-02)

ctx.room.register_byte_stream_handler("kb.upload", _on_kb_stream)
```

- Source: LiveKit docs *Sending files & bytes* + *Vision/Images* (the image-upload
  flow is the canonical `sendFile` → `register_byte_stream_handler` example; KB is
  the same mechanism with a different topic and a parse step instead of
  `ImageContent`). HIGH confidence on the shape; exact signatures are [VM-INTROSPECT].
- The reader is **async-iterable**; `reader.info` carries `name`, `mimeType`, and
  (when sent via `sendFile`) `size`. Accumulate chunks into `bytes()`.
- **Result/error must travel back to the browser.** Byte streams are one-way
  (client→agent). For the upload **ack/error** (REL-03 "clear error", KB-07
  "doc count"), use the **already-wired RPC pattern in reverse OR a participant
  attribute / data message the panel watches.** Simplest, consistent with Phase 3:
  agent sets a **`kb.state` participant attribute** (JSON: `{docs: n, status, error}`)
  that a `KbPanel` reads (the codebase already reads `lk.agent.state` as an
  attribute in `AgentStatePill`, so this pattern is proven). Decide ack channel in 04-01.

**[VM-INTROSPECT]**
```
python -c "from livekit import rtc; print([m for m in dir(rtc.Room) if 'byte_stream' in m or 'stream' in m])"
python -c "from livekit import rtc; print([m for m in dir(rtc.LocalParticipant) if 'file' in m.lower() or 'stream' in m.lower()])"
# JS: confirm sendFile on the pinned livekit-client@2.20.x (02-01 pin)
```

### 1.2 Why not a separate HTTP upload endpoint

A Next.js route + multipart POST to the agent is more plumbing, opens a non-LiveKit
path, and means the **file must reach the agent worker** (which is not the web
container) — you'd proxy through another hop. Byte streams already connect the
browser to the exact worker that owns the sticky `AgentSession`. Prefer byte streams.

### 1.3 Multi-file (KB-01 "documents", KB-07 "how many docs")

`sendFile` is per-file; send N files as N byte streams (loop on the client over the
picked `FileList`). The agent accumulates a **per-session list of parsed docs** and
distills the **concatenation** (or distills each then merges) into one brief. The
**doc count** for KB-07 is `len(parsed_docs)`. Keep the session KB state in a small
in-memory object on the worker (ephemeral by construction — see §6).

---

## 2. Parsing: PDF / TXT / MD / DOCX → clean text

### 2.1 Library choice (from STACK.md, license-checked)

| Type | Library | Call | Notes |
|---|---|---|---|
| PDF | `pymupdf4llm` | `pymupdf4llm.to_markdown(doc)` | Layout-aware, multi-column + tables in reading order, LLM-ready markdown; C-backed (fast). |
| TXT | stdlib | decode bytes | Normalize encoding to UTF-8; strip BOM. |
| MD  | stdlib | decode bytes | Already markdown; pass through (optionally strip). |
| DOCX | `python-docx` | iterate `document.paragraphs` (+ tables) | **Free path.** See §3.2 — pymupdf4llm DOCX needs paid PyMuPDF Pro. |

`uv add pymupdf4llm python-docx` (pulls `pymupdf` as a dep). Pin versions
(`pymupdf ~=1.27`, `python-docx ~=1.1`) per the no-`:latest` rule. **Avoid
`markitdown`** for MVP: heavier dep tree + AGPL-adjacent license questions
(STACK.md) and you don't need a universal converter for 4 known types.

### 2.2 pymupdf4llm API (grounded)

`pymupdf4llm.to_markdown(path_or_doc)` returns a markdown string; `to_text()` and
`to_json()` also exist. It **auto-detects pages needing OCR** but applying OCR is
expensive — for MVP, do **not** enable full-page OCR; instead **detect** the
scanned case and reject it (REL-03, §4). You can open from bytes via PyMuPDF
(`fitz.open(stream=raw, filetype="pdf")`) and hand the doc to `to_markdown`, or
write to a temp file. **[VM-INTROSPECT]** confirm the `to_markdown` signature
accepts an opened `fitz` Document on the pinned version.

### 2.3 DOCX with python-docx

```python
from docx import Document
doc = Document(io.BytesIO(raw))
text = "\n".join(p.text for p in doc.paragraphs)
# tables extract OUT OF ORDER if ignored — iterate doc.tables explicitly and append
```
Handle tables and headings explicitly (Pitfall 14: DOCX tables/headers extract out
of order). Keep it simple for MVP: paragraphs + table cell text, joined.

---

## 3. Pitfalls that dictate the design

### 3.1 Pitfall 7 — KB-as-cached-prefix invalidation (THE keystone risk)

The whole inline-and-cache strategy depends on Ollama reusing the KV/prefix cache
for the KB brief so it costs prefill **only on turn 1**. Ollama's prefix cache
requires the prefix to be **byte-identical** request-to-request. Any upstream
change busts it → full re-prefill of the entire brief every turn → "free after
turn 1" becomes "expensive every turn."

**Design rules (inherit from Phase 3's `render_persona` discipline):**
- Inject the brief into the existing **`KB_SLOT`** seam (`agent/persona.py:78`,
  the empty trailing segment of the persona block, ordered persona→KB→history→turn).
  Fill it **once per session**; then it is FROZEN.
- The brief must be a **plain string with no volatile data** — no timestamps, no
  per-turn counters, no re-serialized JSON whose key order/whitespace can drift.
- **Do not re-distill or re-inject per turn.** KB load is a one-time session event
  (like a persona edit is one re-prefill). After injection, every turn reuses the
  cached prefix.
- The KB injection itself **is one sanctioned re-prefill** (the brief is new bytes
  appended to the persona block). That's the turn-1 cost the design accepts.
- Verification (04-03): turn-2 prompt-eval count ≪ turn-1; turn-2 `llm_ttft_ms` ≪
  turn-1 `llm_ttft_ms` with a large KB loaded. This is **Success Criterion 3**.

### 3.2 PyMuPDF Pro licensing — DOCX is NOT free via pymupdf4llm

pymupdf4llm/pymupdf's Office (DOC/DOCX/XLS/PPT) support requires **PyMuPDF Pro**
(commercial). Free path for DOCX is **python-docx** (STACK.md confirms). Do not
plan DOCX through pymupdf4llm. (PDF/TXT/MD are free via pymupdf4llm/pymupdf.)

### 3.3 Pitfall 14 — parsing quality garbles the KB at the source

Scanned/image PDFs → empty/OCR-garbage; multi-column → interleaved nonsense; DOCX
tables → out of order; encoding (mojibake/BOM/smart quotes) → noise. Distillation
then faithfully distills garbage and the agent confidently coaches from it.
**Mitigations (build the gate in 04-01):**
- **Empty/scanned detection:** if extracted text is near-empty or has a **very low
  alpha-character ratio**, flag as likely scanned/image PDF → clear error
  ("this looks like a scanned document — text couldn't be extracted") and continue
  without that doc (REL-03). This is a pure, testable function.
- **Normalize encoding** to UTF-8; strip BOM and smart-quote artifacts.
- **Size guard on extracted TOKEN count, not file bytes** (a 200-page scanned PDF
  is 0 useful tokens; a dense 10-page MD is many) — see §5.
- Optionally surface a short **word-count / preview** to the user before distilling
  (latency is free here) so a human catches garbage at upload.

### 3.4 Pitfall 8 — distillation drops detail needed for credible coaching

Compact-vs-faithful pull opposite ways; a small model distilling can smooth over
specifics (CVE numbers, command flags, config values) and then the trainer gives
generic, confidently-wrong answers about the user's *own* material (attacks KB-04).
**Mitigations (04-02):**
- Distill at **setup time** where latency is invisible → afford a careful pass
  (can use a larger `num_predict`, a structured prompt, or multi-pass).
- **Preserve verbatim "fact anchors":** extract exact identifiers/numbers/commands
  into a structured facts section that is **NOT paraphrased**, alongside the prose
  brief. The brief = abstractive summary + extractive fact list.
- Size guard with a **quality fallback signal**, not just a hard cutoff: if a doc
  exceeds the brief budget, that's the v2 RAG signal — for v1 MVP, distill harder
  (KB-08) and/or reject with a clear message (REL-03), don't crush it lossily.

### 3.5 Pitfall 9 — three models + KV cache growth → OOM on 16GB at KB load

The KB-as-prefix strategy *requires* a larger `num_ctx`, which Ollama
**pre-allocates upfront** as KV-cache VRAM — the exact tension with the 16GB floor.
**Current state:** `ollama/Modelfile:18` sets `PARAMETER num_ctx 8192` and the
Modelfile comment explicitly says *"this grows in Phase 4 when the distilled KB
brief lands in the frozen prefix."* This is a **Phase-4 decision point:**
- Size `num_ctx` to the **real worst case** = persona (~250 tok) + KB brief budget
  + max history window + headroom — **measure the distilled brief's real token
  count** and set `num_ctx` tightly. Every extra 1k is pre-allocated VRAM you may
  not have.
- Flash attention + `q8_0` KV quant are **already on** (docker-compose ollama env:
  `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`) — these halve KV memory
  and are what make the larger `num_ctx` affordable.
- **04-03 must re-run `scripts/vram-validate.sh` (or equivalent) WITH a KB loaded**
  — KB load is the peak-memory moment. This is the "KB-load VRAM re-check" plan item.
- The brief budget (token cap) and `num_ctx` are **coupled constants** — set them
  together. Recommend: keep the brief small (e.g. ~1–2k tokens) so `num_ctx` stays
  modest (e.g. 8192 may still suffice, or a measured bump). **[VM-INTROSPECT]**
  measure real brief tokens and peak VRAM, then pin `num_ctx`.

### 3.6 Pitfall 3 — model/cache eviction kills the "free after turn 1" win

`OLLAMA_KEEP_ALIVE=-1` is already set (compose) so the model stays resident. But
after a KB loads, **fire one priming turn** to force the KB-prefix prefill while
the user is still reading the "KB ready" indicator — so the user's *first real
turn* is warm, not a cold full-prefill. (Same trick the warmup uses at startup.)

---

## 4. Parse-failure & error handling (REL-03)

REL-03 = "a failed KB upload (parse error, oversize) surfaces a clear error and the
session continues without the KB." Failure modes and required surfacing:

| Failure | Detect | Surface (KB panel) | Session continues? |
|---|---|---|---|
| Unsupported type | mime/extension not in {pdf,txt,md,docx} | "Unsupported file type — use PDF/TXT/MD/DOCX" | yes, no KB |
| Scanned/empty PDF | near-zero text / low alpha ratio | "Couldn't extract text (looks scanned)" | yes, that doc skipped |
| Corrupt/parse exception | parser raises | "Couldn't read this file" | yes, that doc skipped |
| Oversize | extracted tokens > hard cap | "Too large for inline KB — trimmed/skipped" | yes (distill harder or skip) |
| Distillation failure | Ollama error/timeout | "Couldn't build the brief — continuing without KB" | yes, no KB |

**Hard rule (CODE_PRINCIPLES §4 boundary):** KB upload/parse is a named boundary
that always needs handling — **no bare except**, no silent swallow. Each failure
path sets the `kb.state` error and the agent keeps running the voice loop with the
**unchanged** persona prefix (KB_SLOT stays empty). The default-trainer behavior
(KB-04 "with none, it does not reference user material") is the natural fallback.

---

## 5. Size guard (KB-08)

KB-08 = "warns or distills more aggressively when an upload is large enough to bloat
the cached prefix / KV-cache VRAM." Design:

- **Measure on extracted token count**, not file bytes (Pitfall 14). A cheap token
  estimate (e.g. `len(text) / CHARS_PER_TOKEN` with a named constant, or a real
  tokenizer if cheap) is fine for a guard.
- **Two thresholds (named constants, CODE_PRINCIPLES §2):**
  - `KB_WARN_TOKENS` — over this, *distill harder* (tighter brief target) and warn
    in the indicator. (KB-08 "distills more aggressively")
  - `KB_MAX_TOKENS` — hard cap; over this, reject with a clear error (REL-03) and
    continue without that doc. (v2 reserves true RAG for this case.)
- The guard runs **after parse, before distillation** (you guard the real text, and
  the distill target is what protects the prefix/VRAM budget).
- Couple `KB_MAX_TOKENS` to the **distilled-brief budget** and `num_ctx` (§3.5),
  not the raw upload — the brief is what lands in the prefix, so the guard's job is
  ensuring the *brief* fits, possibly by distilling a big input harder.

---

## 6. Ephemeral lifecycle (KB-06) + indicator (KB-07)

- **KB-06 (ephemeral):** the session KB lives **only in worker memory** for the
  `AgentSession`'s lifetime (sessions are sticky to one worker — ARCHITECTURE).
  Nothing is persisted to disk/db (privacy + simplicity; persistent KB is explicit
  v2 SCALE-03, out of scope). "Cleared at session end" = the in-memory KB object is
  dropped when the job ends / room disconnects. If you write a temp file during
  parse, **delete it in a `finally`** (boundary-safe) — don't leave doc bytes on
  disk. Phase 7 (SESS-03) does the formal teardown audit; Phase 4 must not create
  persistent state for it to clean up.
- **KB-07 (indicator):** a `KbPanel` (beside `PersonaPanel`) shows **KB active +
  doc count**, fed by the `kb.state` attribute/ack (§1.1). States:
  `idle → uploading → parsing → distilling → ready (n docs) | error`. Mirror the
  thin inline-styled convention of `PersonaPanel`/`AgentStatePill`.

---

## 7. Distillation pass (KB-02) — the one LLM call

- **Where:** in the agent worker, **at setup time, off the hot path** — reuse the
  resident Ollama model (`resolved_llm_tag()` / `OLLAMA_BASE_URL`), same client
  style as `main.py:_warmup_llm_ttft_ms` (httpx stream) or the livekit `openai.LLM`.
  Latency here is invisible to the conversation, so a **bigger `num_predict`** and a
  **careful prompt** are fine.
- **Prompt shape:** instruct the model to produce (a) a **compact prose domain
  brief** (spoken-coaching oriented) and (b) a **verbatim fact-anchor list**
  (exact terms/numbers/commands, not paraphrased — Pitfall 8). Cap the brief to the
  `KB`-budget token target.
- **Thinking stays OFF** (TTFT discipline is moot here, but keep consistent;
  `reasoning_effort="none"` / `think=false`).
- **Ollama bug #15260 (flagged in `ollama/Modelfile:30`):** `think=false` + `format`
  (structured JSON) **silently drops the format constraint for gemma4**. So if you
  want JSON-structured distillation output, **do not rely on `format=json` with
  think=false** — either (a) parse a delimited/markdown structure out of plain text
  (robust, recommended for MVP), or (b) verify #15260 is fixed on the pinned Ollama
  `0.6.8` before depending on JSON mode. **[VM-INTROSPECT]** if JSON is wanted.
- **Output is injected as the `KB_SLOT` string** (§3.1) and frozen.

---

## 8. Injecting into the frozen prefix (KB-03) — the concrete seam

The seam already exists. `agent/persona.py`:
- `KB_SLOT: str = ""` (line 78) — the empty trailing segment.
- `render_persona(p)` joins `(role, difficulty, verbosity, correction, footer, KB_SLOT)`
  with `" "` (lines 111–118).

**Phase 4 fills `KB_SLOT` with the distilled brief** — but `render_persona` is a
pure function of `Persona`, and the KB is session state, not a persona field. Two
clean options (decide in 04-02):

1. **Add a `kb_brief: str = ""` param to `render_persona`** (or a second function
   `render_prompt(persona, kb_brief)`), appended where `KB_SLOT` is now. This keeps
   byte-stability (still frozen constants + one session-frozen brief string) and
   matches ARCHITECTURE's `render_prompt(persona, brief)`. **Preferred** — explicit,
   testable, preserves the persona→KB→history→turn order.
2. Keep `KB_SLOT` module-level and set it once — **worse** (hidden global mutable,
   breaks the pure-function byte-stability test). Avoid.

**Interaction with the Phase-3 persona hot-swap:** the RPC handler
(`handle_persona_update`, `main.py:241`) calls `agent.update_instructions(render_persona(p))`.
After Phase 4, it must call `render_prompt(p, current_kb_brief)` so a persona edit
**re-emits the SAME KB brief** (else editing persona would drop the KB). Both a
persona edit and a KB load are sanctioned one-time re-prefills; they must compose,
not clobber. Update the golden byte-stability test (`persona.py:_self_check`) to
cover `kb_brief=""` (unchanged default) and a fixed non-empty brief.

**Update the EXPECTED_DEFAULT golden** only if the signature changes the empty-KB
render — with `kb_brief=""` appended identically to today's `KB_SLOT`, the default
render is byte-unchanged (keep the regression test green).

---

## 9. Demonstrating KB grounding (KB-04) + flat-TTFT (KB-05) — the proofs

- **KB-04 (grounding):** the acceptance is behavioral — with a KB loaded, the agent
  references the user's material; with none, it doesn't. Operator gate: upload a doc
  with a distinctive fact, ask about it by voice, confirm the trainer uses it; then
  with no KB confirm it doesn't invent it. The **fact-anchor** design (§3.4) is what
  makes specifics surface. [VM-INTROSPECT] / live UAT.
- **KB-05 / Criterion 3 (flat-TTFT):** the keystone proof, owned by **04-03**.
  `agent/metrics.py` already emits per-turn `llm_ttft_ms` keyed by `speech_id` and a
  rolling P50/P95. Use it: load a **large** KB, then compare **turn-1 `llm_ttft_ms`
  (cold prefill of the brief) vs turn-2+ (`≪`, cached)**. Cross-check Ollama logs:
  turn-2 should show a small "new tokens" prompt-eval count, not a full re-eval
  (Pitfall 7 warning sign). Also compare KB-loaded vs no-KB turn-2 TTFT — should be
  ~flat. **Do not change the metrics key shape** (Phase 3 contract).

---

## 10. Plan-by-plan notes (vertical slices)

### 10.1 Plan 04-01 — upload + parse + gate + guard + failure handling (REL-03)
- **Pure/sandbox-testable core:** a parser module (e.g. `agent/kb/parse.py`) with
  `parse(name, mime, raw) -> ParsedDoc` dispatching by type; an extraction-quality
  gate (alpha-ratio / non-empty); a size guard on token estimate; UTF-8/BOM
  normalization. Unit-test over **fixture bytes** (tiny PDF/TXT/MD/DOCX +
  a scanned-PDF-like empty case) with a `_self_check()` mirroring
  `persona.py`/`metrics.py` (no livekit import needed for the pure parts).
- **Transport (VM):** `register_byte_stream_handler("kb.upload", ...)` on the agent;
  `sendFile` on a new `KbPanel`/upload control in the web app; `kb.state` ack channel.
- **Failure matrix (§4)** wired to clear errors; session continues with empty KB.
- Acceptance (sandbox): parser unit tests pass; unsupported/empty/oversize each
  return a typed error not an exception; `next build` clean with the upload UI.
- Operator gates (VM): upload each of PDF/TXT/MD/DOCX → parsed; a scanned PDF →
  clear error + session continues; oversize → guard fires.

### 10.2 Plan 04-02 — distill → inject once → indicator + ephemeral teardown
- Distillation module (`agent/kb/distill.py`): raw text → brief + fact-anchors via
  one Ollama call (off hot path); brief-budget cap; #15260-safe output parsing (§7).
- `render_prompt(persona, kb_brief)` (or `kb_brief` param) filling `KB_SLOT` (§8);
  update `handle_persona_update` to carry the current brief; update `_self_check`
  golden for `kb_brief=""` and a fixed brief.
- Inject once on KB-ready; **priming turn** to warm the prefill (Pitfall 3).
- `KbPanel` indicator: doc count + state (KB-07); ephemeral in-memory KB, temp-file
  cleanup in `finally` (KB-06).
- Acceptance (sandbox): `render_prompt` deterministic + golden (empty + fixed brief);
  distill-prompt builder is a pure testable function. VM: brief references doc;
  indicator shows count; end session → KB gone.

### 10.3 Plan 04-03 — prefix-cache + VRAM verification (the keystone)
- Load a large KB; record turn-1 vs turn-2 `llm_ttft_ms` from `metrics.py`; assert
  turn-2 ≪ turn-1 and ≈ no-KB turn-2 (KB-05 / Criterion 3). Cross-check Ollama
  prompt-eval logs for cache hits (Pitfall 7 signs).
- Re-run VRAM validation **with KB loaded** (peak-memory moment); pin `num_ctx` to
  the measured worst case (§3.5); confirm `q8_0` KV still engaged, 3 GPU procs.
- This plan is **operator/VM-only** — document the exact commands; defer like the
  Phase-1 VRAM gate and Phase-2/3 [VM-INTROSPECT] items.

### 10.4 Requirement → mechanism map

| Req | Mechanism |
|---|---|
| KB-01 (upload PDF/TXT/MD/DOCX) | `sendFile` byte stream → `register_byte_stream_handler` (§1); per-type parser (§2) |
| KB-02 (distill to brief at upload) | one setup-time Ollama pass → brief + fact-anchors (§7) |
| KB-03 (load once into prefix/KV cache) | fill `KB_SLOT` via `render_prompt(persona, brief)`, frozen for session (§8) |
| KB-04 (grounding vs none) | fact-anchor distillation; empty KB_SLOT = default behavior (§3.4, §9) |
| KB-05 (flat TTFT) | inject once + Ollama prefix cache + `keep_alive=-1`; verified via metrics turn-1 vs turn-2 (§9, 04-03) |
| KB-06 (ephemeral) | in-memory session KB; temp-file cleanup in `finally`; no persistence (§6) |
| KB-07 (active indicator + doc count) | `KbPanel` reads `kb.state` attribute (§1.1, §6) |
| KB-08 (size guard / distill harder) | token-count guard, `KB_WARN_TOKENS`/`KB_MAX_TOKENS` (§5) |
| REL-03 (failed upload → clear error, session continues) | failure matrix → `kb.state` error, empty KB_SLOT fallback (§4) |

---

## 11. Sandbox limits & [VM-INTROSPECT] checklist (defer like 02/03)

```
# Byte-stream transport (Python rtc SDK)
python -c "from livekit import rtc; print([m for m in dir(rtc.Room) if 'byte_stream' in m or 'register' in m])"
python -c "from livekit import rtc; print([m for m in dir(rtc.LocalParticipant) if 'file' in m.lower() or 'stream' in m.lower()])"
# JS sendFile on the pinned livekit-client@2.20.x
# pymupdf4llm API on the pinned version (opened doc vs path; OCR auto-detect)
python -c "import pymupdf4llm, inspect; print(inspect.signature(pymupdf4llm.to_markdown))"
# python-docx import + table iteration
# Ollama bug #15260 (think=false + format=json drops JSON) on ollama 0.6.8 — only if JSON distill is wanted
# Distilled-brief REAL token count → set num_ctx tightly; re-run VRAM validate WITH KB loaded
# Flat-TTFT proof: turn-1 vs turn-2 llm_ttft_ms with a large KB (metrics.py) + Ollama prompt-eval log cache-hit check
```
**Pure, sandbox-verifiable now:** the parser + extraction gate + size guard
(over fixture bytes), the distill-prompt builder, `render_prompt` byte-stability
(empty + fixed brief golden), and the web upload UI `next build`. Make these the
client-verifiable acceptance criteria; the transport round-trip, distillation
quality, flat-TTFT proof, and VRAM re-check are operator gates.

---

## Sources
- Repo: `agent/main.py`, `agent/persona.py` (KB_SLOT seam, frozen prefix),
  `agent/metrics.py` (per-turn `llm_ttft_ms`), `ollama/Modelfile` (num_ctx 8192 +
  #15260 note), `docker-compose.yml` (flash-attn + q8_0 + keep_alive=-1) — HIGH
- `.planning/research/ARCHITECTURE.md` Pattern 4 (inline-and-cache), Anti-Patterns
  2–3, KB path diagram — HIGH
- `.planning/research/PITFALLS.md` Pitfalls 3, 7, 8, 9, 12, 14 — HIGH
- `.planning/research/STACK.md` (pymupdf/pymupdf4llm/python-docx, PyMuPDF Pro for
  Office, q8_0 needs flash-attn, num_ctx pre-allocation) — HIGH
- LiveKit docs — *Sending files & bytes* (`sendFile` / `register_byte_stream_handler`,
  async reader, `reader.info`) + *Vision/Images* (canonical upload flow) — HIGH (shape),
  MEDIUM (exact pinned signatures → [VM-INTROSPECT])
- pymupdf4llm docs/GitHub — `to_markdown()`/`to_text()`/`to_json()`, OCR auto-detect,
  Office needs PyMuPDF Pro — HIGH
- Phase 3 `03-RESEARCH.md` (byte-stable prefix discipline, RPC/attribute control
  channel, hot-swap composition) — HIGH

---
*Phase 4 research — Knowledge Base Layer. Grounded in repo code + installed-version
docs + Phase 2/3 source-verified memory; live-build/model claims tagged
[VM-INTROSPECT] for the VM. Keystone risk = prefix-cache byte-stability (Pitfall 7).*
