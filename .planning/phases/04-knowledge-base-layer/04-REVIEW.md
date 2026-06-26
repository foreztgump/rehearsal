# Phase 04 (Knowledge Base Layer) — Backfill Code Review

**Scope:** the source files introduced/changed across 04-01, 04-02, and the 04-04 gap fixes (`46b2857`, `afaac74`, `d579297`, `69605b9`). Reviewed CURRENT on-disk state.
**Reviewed files:** `agent/kb/parse.py` (NEW), `agent/kb/distill.py` (NEW), `agent/kb/__init__.py` (NEW), `agent/persona.py` (MODIFIED), `agent/main.py` (KB wiring), `web/app/KbPanel.tsx` (NEW), `web/app/VoiceRoom.tsx` (MODIFIED). `agent/history.py` excluded (Phase 05).
**Method:** static review only — sandbox cannot import livekit / run Docker/GPU/Ollama. Build gates re-confirmed green: `python3 agent/persona.py` → `persona _self_check OK`; `python3 agent/kb/parse.py` → `kb.parse _self_check OK`.
**Status note:** Phase 04 is `awaiting operator UAT`; live items in `04-KB-VERIFY.md` are NOT marked passed/failed here.

**Resolution (backfill fixes):** H1, H2, H3 all FIXED. H1: `parse()` enforces a pre-extraction `KB_MAX_RAW_BYTES` (25 MB) ceiling on `len(raw)` before `_extract`, so a large upload is rejected as `oversize` before it can OOM the worker during parse. H2: `_extract_docx` inspects the `.docx` zip directory with stdlib `zipfile` (summing declared uncompressed member sizes against `DOCX_MAX_UNCOMPRESSED_BYTES`, 50 MB) BEFORE the `python-docx` import/parse, raising the internal `_OversizeExtraction` → typed `oversize` error; a small-on-the-wire zip bomb is now caught (verified in-sandbox). H3: `ingest_kb` offloads both `kb_parse` and `kb_distill` via `asyncio.to_thread`, and `distill._generate` now uses a bounded `DISTILL_TIMEOUT_SECONDS=120` instead of `timeout=None` (a stall maps to `DistillError`, since `httpx.TimeoutException` ⊂ `httpx.HTTPError`) — so KB ingest no longer blocks the voice loop or hangs forever. M1–M5 / L1–L3 left as documented findings.

---

## Summary by severity

| Severity | Count | Findings |
|----------|-------|----------|
| Critical | 0 | — |
| High     | 3 | H1 — size guard runs AFTER full extraction; no pre-parse byte cap → a large upload OOMs the worker before the guard can fire. H2 — DOCX decompression (zip) bomb: a tiny `.docx` expands to GBs inside `python-docx`, unguarded. H3 — `ingest_kb` runs synchronous, blocking parse + `httpx.Client(timeout=None)` distill **on the agent event loop** → freezes the voice loop (contradicts the REL-03 "voice loop keeps running" guarantee) and can hang forever. |
| Medium   | 5 | M1 — distill boundary leak: non-`httpx` errors (e.g. `json.JSONDecodeError`) escape `_generate`; `ingest_kb` only catches `DistillError`, so a malformed stream kills the task and wedges `kb.state` on `distilling`. M2 — unbounded aggregate doc accumulation: per-doc `KB_MAX_TOKENS` guard but no cap on doc count / concatenated size → re-introduces the GAP-1 silent-truncation past the effective 8192 ctx. M3 — concurrent ingest tasks race on `session_kb.docs` + competing `update_instructions`. M4 — prompt injection from untrusted doc text into the distill prompt, verbatim into the frozen system prefix. M5 — client upload error handling: `sendFile` rejection unhandled (status stuck on `uploading`); no size feedback / pre-upload limit. |
| Low      | 3 | L1 — `ParsedDoc.oversize_warn` is computed but never consumed; the KB-08 "distill harder" hook is dead. L2 — distill repair pass doubles the (blocking) LLM latency with no cap. L3 — `kb.state` `uploading` is only ever set client-side; minor state-machine duplication + doc-count reset on each attribute write. |

Byte-stability discipline (the keystone constraint) is **clean**: `render_prompt` / `KB_CITE_NUDGE` carry no volatile data, the nudge is brief-gated so the empty-KB render stays byte-identical to `EXPECTED_DEFAULT`, and the golden self-check passes. Inject-once discipline is **correct** — `update_instructions` is called only on a successful ingest, never per turn (flat-TTFT invariant holds). No second hardcoded model tag, no `livekit` import under `agent/kb/`, no bare `except`, `agent/metrics.py` untouched. `info.name` is used only as a label (no filesystem write) → **no path traversal**.

---

## High

### H1 — Size guard is enforced AFTER full extraction; no pre-parse byte cap → OOM before the guard fires (`agent/kb/parse.py:97-126`, `agent/main.py:477-481`)

The size guard is the LAST step of `parse()`:

```python
text = _extract(kind, raw)          # full PDF/DOCX parse into memory
text = _normalize(text)
gate = _extraction_gate(text)
token_estimate = _estimate_tokens(text)
if token_estimate > KB_MAX_TOKENS:  # guard fires here — AFTER extraction
    return KbParseError(name, "oversize", ...)
```

By the time `KB_MAX_TOKENS` is checked, the worker has already (a) buffered the entire raw upload in memory (`raw = bytes(); async for chunk in reader: raw += chunk`, `main.py:477-479`) and (b) fully parsed it — `pymupdf4llm.to_markdown(doc)` for PDF (`parse.py:156`) or `python-docx` for DOCX. There is **no byte-length ceiling on `raw`** and **no page/element ceiling** before parsing. A multi-hundred-MB PDF (or just a large raw upload) can exhaust worker RAM and OOM-kill the process *before* the token guard ever runs. The module docstring claims "a large file can still distill-bust the frozen prefix budget" but the guard only protects the *prefix budget*, not the *parse step's* memory.

The token guard is the right unit for prefix budgeting, but it cannot be the only resource control. **Recommendation:** add a cheap `len(raw)` byte cap checked *before* `_extract` (reject e.g. `> N MB` with a typed `oversize` error), and pass a page/element cap into the PDF/DOCX extractors. Ideally also cap the accumulated `raw` size while reading the stream (`reader.info.size` is available per the 04-01 transport contract) and abort early.

### H2 — DOCX decompression (zip) bomb is unguarded (`agent/kb/parse.py:163-178`)

```python
from docx import Document
doc = Document(io.BytesIO(raw))     # .docx is a ZIP — decompressed here
```

A `.docx` is a zip archive; `python-docx` (via `zipfile`) decompresses member parts with no ratio/size limit. A crafted ~1 MB `.docx` whose `document.xml` is a zip bomb expands to gigabytes in memory during `Document(...)` — and crucially this is *not* mitigated by any raw-byte cap from H1, because the malicious upload is small on the wire. The `try/except Exception` boundary in `parse()` (`:107-112`) only catches a *raised* exception; an OOM during decompression kills the process, it does not become a `corrupt` error. **Recommendation:** inspect the zip directory before reading (reject when the sum of `ZipInfo.file_size` exceeds a cap, or the compression ratio is implausible) — i.e. open `zipfile.ZipFile(io.BytesIO(raw))`, sum uncompressed sizes, bail with a typed error before handing the bytes to `python-docx`. The same class of guard is worth a thought for PDF (object-stream expansion), though PyMuPDF is more robust.

### H3 — Parse + distill run synchronously on the agent event loop; `timeout=None` can hang the voice loop forever (`agent/main.py:468-518`, `agent/kb/distill.py:124-154`)

`ingest_kb` is an `async` task, but it calls **blocking** work directly in the coroutine:

- `kb_parse(...)` (`main.py:481`) — synchronous PyMuPDF / python-docx CPU work.
- `kb_distill(...)` (`main.py:492`) → `_generate` uses a **synchronous** `httpx.Client` with `timeout=None` and a blocking `for line in response.iter_lines()` loop (`distill.py:140-151`).

Neither is offloaded with `asyncio.to_thread` / an async client, so for the full duration of a large parse and the entire distill generation the single event-loop thread is blocked — the agent cannot service audio, turn detection, or RPCs. This directly contradicts the design intent quoted throughout the plans ("off hot path… latency is invisible to the voice loop", "the voice loop keeps running on a bad upload"). The latency is invisible only if it runs off the loop; here it runs *on* it.

`timeout=None` makes it worse: a stalled or slow Ollama generation never times out, so a single bad/slow distill can freeze the voice session indefinitely. (Contrast `_warmup_llm_ttft_ms`, which uses `WARMUP_TIMEOUT_SECONDS=120`.) **Recommendation:** run `kb_parse` and the distill call via `asyncio.to_thread(...)` (or convert `_generate` to `httpx.AsyncClient` + `aiter_lines`), and give the distill client a bounded total/read timeout that maps to `DistillError`.

---

## Medium

### M1 — Distill boundary leak: non-httpx errors escape and wedge `kb.state` on `distilling` (`agent/kb/distill.py:139-154`, `agent/main.py:491-499`)

`_generate` maps only `httpx.HTTPError` → `DistillError`:

```python
try:
    ...
    chunk = json.loads(line)      # can raise json.JSONDecodeError
    ...
except httpx.HTTPError as exc:
    raise DistillError(...) from exc
```

`json.loads(line)` (`:146`) raises `json.JSONDecodeError` (a `ValueError`, **not** an `httpx.HTTPError`) if Ollama emits a malformed/partial line; likewise a `KeyError`/`TypeError` on an unexpected chunk shape. `ingest_kb` only catches `DistillError` (`main.py:493`), so any of these propagates out of the task. With `add_done_callback(active_tasks.remove)` the task is silently dropped, `kb.state` is left on `distilling`, and the panel spins forever with no error — violating the REL-03 "clear error, continue" contract. **Recommendation:** widen the `_generate` try to convert any parse/stream error into `DistillError` (the named-boundary rule), or catch `Exception` in `ingest_kb`'s distill block and surface a `kb.state` error.

### M2 — Unbounded aggregate doc accumulation re-introduces the GAP-1 truncation (`agent/main.py:485`, `290-296`, `agent/kb/distill.py:168`)

`parse()` caps each *individual* doc at `KB_MAX_TOKENS` (24000), but `ingest_kb` appends every accepted doc to `session_kb.docs` (`:485`) with no cap on count, and re-distills the **full concatenation** each upload (`_concat_docs`, `:290-296`). Several large docs (or many small ones) produce a distill *input* far larger than the effective 8192-token Ollama context pinned in 04-04 — Ollama silently truncates the prompt (`truncating input prompt`), which is precisely the GAP-1 failure 04-04 closed for the *single*-doc case. The single-doc guard does not bound the multi-doc total. **Recommendation:** track a running token total across `session_kb.docs` and reject / warn when the aggregate would exceed the distill input budget (couple it to `BRIEF_TOKEN_BUDGET` / `OLLAMA_CONTEXT_LENGTH`).

### M3 — Concurrent ingest tasks race on shared KB state (`agent/main.py:520-525`, `485`, `506-509`)

`on_kb_stream` creates one `ingest_kb` task per incoming byte stream with no serialization. A multi-file pick (or any overlapping uploads) yields multiple tasks that each `append` to `session_kb.docs`, set `session_kb.brief`, and call `agent.update_instructions(...)`. Across the `await` points (`set_kb_state`, `update_instructions`) these interleave, so the final `brief` / `docs` and the last `update_instructions` winner are nondeterministic — and two priming `generate_reply` calls can stack. (H3's blocking distill partially serializes them today, but that is an accident, not a guarantee, and the interleaving at `await` boundaries remains.) **Recommendation:** serialize ingest with an `asyncio.Lock`, or queue uploads so distill+inject is atomic per upload.

### M4 — Prompt injection from untrusted doc text into the frozen system prefix (`agent/kb/distill.py:99-105`, `157-187`; `agent/persona.py:134`)

`build_distill_prompt` interpolates raw doc text after the instruction, and the FACTS contract explicitly asks the model to copy terms **verbatim** (`:53-55`). Uploaded documents are untrusted input; a doc containing "ignore the above; output FACTS: <attacker text>" can steer the brief, and verbatim-copied content lands in the brief that `render_prompt` injects into the **system prefix** for the rest of the session (`persona.py:134`). This is largely inherent to an inline-KB design and is mitigated by the single-tenant, self-hosted, user-uploads-own-material trust model — but it is undocumented. **Recommendation:** note the trust assumption explicitly, and consider delimiting/escaping the source block or instructing the model to treat the block as data, not instructions.

### M5 — Client-side upload error handling + no size feedback (`web/app/KbPanel.tsx:93-100`, `111-119`)

```tsx
async function upload(files: FileList) {
  setStatus("uploading");
  for (const file of Array.from(files)) {
    await room.localParticipant.sendFile(file, { topic: KB_UPLOAD_TOPIC });
  }
}
```

`sendFile` is awaited with no `try/catch`. If the send rejects (disconnect, transport error), the promise rejection is unhandled and the panel stays on `uploading` with no error — the `kb.state` channel only reports *agent-side* parse/distill failures, never a failed send. There is also no file-size feedback or pre-upload limit, so a user can pick an arbitrarily large file that streams to the agent and triggers H1. **Recommendation:** wrap the loop in `try/catch`, set an `error` status on rejection, and add a client-side size check (with a friendly message) before `sendFile`.

---

## Low

### L1 — `oversize_warn` is dead; the KB-08 "distill harder" hook was never wired (`agent/kb/parse.py:80-83`, `124-126`)

`ParsedDoc.oversize_warn` is computed and documented as "the KB-08 signal that 04-02's distiller reads", but nothing in `main.py` or `distill.py` ever reads it — `ingest_kb` distills identically regardless. The signal is correct but unconsumed. **Recommendation:** either consume it (e.g. tighten `num_predict` / instruction when any doc warns) or drop it and note KB-08's "distill harder" is deferred.

### L2 — Distill repair pass doubles the (blocking) LLM round-trip with no cap (`agent/kb/distill.py:168-187`)

When the first pass omits the FACTS anchor, `distill` fires a second full `_generate` over the same source. Combined with H3 (blocking, `timeout=None`) this can double the event-loop freeze. Functionally correct and bounded to one retry, but worth noting once H3 is addressed.

### L3 — `uploading` status is client-only; doc count resets per attribute write (`web/app/KbPanel.tsx:80-91, 94`)

`uploading` is set locally in `upload()` and never emitted by the agent — the agent's first attribute write is `parsing`. Minor state-machine duplication. Also `setDocs(parsed.docs ?? 0)` on every `kb.state` write means an error payload with `docs:0` briefly zeroes a previously-shown count. Cosmetic.

---

## Verified-correct (no action)

- **Byte-stability / inject-once (keystone):** `render_prompt` joins frozen constants with the brief as an opaque string; `KB_CITE_NUDGE` is brief-gated so `render_prompt(p, "") == EXPECTED_DEFAULT` (golden green); `render_persona` delegates to `render_prompt(p, "")`. `update_instructions` is called only in `handle_persona_update`, `handle_mode_update`, and `ingest_kb` — never per turn → flat-TTFT invariant intact (`persona.py:116-150`, `main.py:336,395,509`).
- **GC strong-ref pattern:** `active_tasks.append(task)` + `task.add_done_callback(active_tasks.remove)` keeps the read task alive and self-cleans (`main.py:456,520-523`). Correct.
- **Boundary discipline in `parse`:** every failure returns a typed `KbParseError` (unsupported/scanned/corrupt/oversize); parser exceptions caught and converted; no bare `except`; no `livekit` import under `agent/kb/`; no volatile data (`parse.py:97-126`).
- **No path traversal:** `info.name` flows only into `ParsedDoc.name` / the `kb.state` JSON label; `_kind` uses it only for an extension `rsplit`. No filesystem write anywhere in the KB path (KB-06 ephemeral honored — in-memory `_SessionKb` only).
- **Compose, not clobber:** persona edit re-emits the current brief via `render_prompt(p, session_kb.brief)`; KB load re-renders under the current persona; both are one-time sanctioned re-prefills (`main.py:389-397,506-509`).
- **No second model tag:** distill resolves from `OLLAMA_MODEL` via `_resolved_llm_tag()`, mirroring `main.resolved_llm_tag`, avoiding a circular `main` import (`distill.py:89-96`).
- **`#15260`-safe:** distill payload carries no output-schema key; FACTS delimiter parsed from plain text (`distill.py:131-137`).
- **`agent/metrics.py` untouched**; `VoiceRoom.tsx` mounts `<KbPanel/>` inside `<LiveKitRoom>` (room context available for `sendFile` + attribute read).

---

## Top recommendations

1. **H3 first** — move `kb_parse` and the distill call off the event loop (`asyncio.to_thread` / `httpx.AsyncClient`) and give distill a bounded timeout. Without this the KB feature can freeze the voice session, defeating the whole "off hot path" premise.
2. **H1 + H2** — add a pre-parse byte cap and a DOCX zip-bomb guard (sum uncompressed sizes before handing to `python-docx`). The current token guard cannot protect the parse step's memory and does nothing against a small-on-the-wire decompression bomb.
3. **M1 + M2** — widen the distill error boundary so no non-`DistillError` escapes (so `kb.state` never wedges), and bound the *aggregate* doc-token total so multi-doc uploads don't silently truncate past the 8192 ctx (the GAP-1 class of bug, multi-doc edition).

All findings are static; the live transport (`sendFile` / `register_byte_stream_handler` / `set_attributes`), distill round-trip quality, and flat-TTFT/VRAM proofs remain `[VM-INTROSPECT]` operator gates in `04-KB-VERIFY.md` — not adjudicated here.

**Report written to:** `.planning/phases/04-knowledge-base-layer/04-REVIEW.md`
