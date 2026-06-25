---
phase: 04-knowledge-base-layer
plan: 04-01
subsystem: api
tags: [livekit, byte-stream, pymupdf4llm, python-docx, kb, parser, nextjs, react]

requires:
  - phase: 03-persona-layer
    provides: frozen-prefix render_persona + KB_SLOT seam; lk.agent.state attribute-read pattern; PersonaPanel/VoiceRoom panel row
provides:
  - Pure livekit-free KB parser (agent/kb/parse.py) — dispatch + extraction gate + size guard + typed errors + _self_check
  - Pinned KB parse deps + kb/ package COPY in the agent image
  - kb.upload byte-stream handler in agent/main.py accumulating ParsedDocs in worker memory + kb.state attribute publisher
  - web/app/KbPanel.tsx — sendFile upload loop + kb.state-driven KB-active indicator
  - VoiceRoom mounts KbPanel inside LiveKitRoom
affects: [04-02-distill-inject, 04-03-vram-flat-ttft]

tech-stack:
  added: [pymupdf4llm, pymupdf~=1.27, python-docx~=1.1]
  patterns:
    - "Pure parser module mirroring metrics.py/persona.py (frozen constants, @dataclass, _self_check)"
    - "Typed result union ParsedDoc | KbParseError (boundary returns, never raises)"
    - "Byte-stream ingest (register_byte_stream_handler) + kb.state participant attribute for one-way ack"
    - "Size guard on EXTRACTED tokens, not file bytes"

key-files:
  created:
    - agent/kb/parse.py
    - agent/kb/__init__.py
    - web/app/KbPanel.tsx
  modified:
    - agent/requirements.txt
    - agent/Dockerfile
    - agent/main.py
    - web/app/VoiceRoom.tsx

key-decisions:
  - "Heavy parser deps (pymupdf4llm/fitz/python-docx) imported LAZILY inside _extract so the pure dispatch/gate/guard path (and the txt/md stdlib path the self-check exercises) imports without them in the sandbox"
  - "pymupdf4llm left unpinned (thin meta-package); the bound is on pymupdf~=1.27 which carries the actual PDF parser — avoids guessing a meta-package version"
  - "KbPanel reads kb.state via useParticipantAttributes({ participant: agent }) — type-verified present in installed @livekit/components-react@2.9.21; sendFile(file,{topic}) type-verified in livekit-client@2.20.0"

patterns-established:
  - "kb.upload / kb.state transport contract shared between agent/main.py and web/app/KbPanel.tsx"

requirements-completed: [KB-01, KB-07, KB-08, REL-03]

duration: 12 min
completed: 2026-06-25
status: complete
---

# Phase 4 Plan 04-01: Upload → parse → gate → guard, with a KB-active indicator and clear failure handling Summary

**Ephemeral KB ingest vertical slice: per-file LiveKit byte-stream upload → pure livekit-free per-type parser (pymupdf4llm/python-docx) with extraction-quality gate + extracted-token size guard + four typed errors → in-memory doc accumulation → kb.state-driven KB-active indicator panel — distillation/injection deferred to 04-02.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-06-25T22:37:00Z
- **Completed:** 2026-06-25T22:49:24Z
- **Tasks:** 5
- **Files modified:** 7 (3 created, 4 modified)

## Accomplishments

- `agent/kb/parse.py`: pure, livekit-free `parse(name, mime, raw) -> ParsedDoc | KbParseError` mirroring `metrics.py`/`persona.py` — frozen constants, dataclasses, `_self_check()` green over fixture bytes. Dispatch + UTF-8/BOM/smart-quote normalize + extraction-quality gate (alpha-ratio/min-chars) + size guard on **extracted tokens** + four typed `reason` values (`unsupported`/`scanned`/`corrupt`/`oversize`) + `oversize_warn` signal for 04-02.
- Pinned parse deps + `COPY kb/ ./kb/` in the agent Dockerfile (uv install / download-files / ENV / CMD untouched).
- `agent/main.py`: `register_byte_stream_handler("kb.upload", ...)` after `session.start`, `_active_tasks` GC-guard, in-memory `_SessionKb` (no disk/db), `kb.state` `{status, docs, error}` publisher via `set_attributes`. Parse error → `kb.state` error + return (voice loop continues, prefix unchanged). `agent/metrics.py` untouched.
- `web/app/KbPanel.tsx`: `<input type="file" accept=".pdf,.txt,.md,.docx" multiple>` → `sendFile(file, { topic: "kb.upload" })` loop; reads `kb.state` via `useParticipantAttributes` → `idle→uploading→parsing→distilling→ready (n docs) | error` with verbatim error. No file leaves the LAN.
- `web/app/VoiceRoom.tsx`: `<KbPanel />` mounted inside `<LiveKitRoom>` between PersonaPanel and Transcript.

## Task Commits

1. **Task 04-01-1: pure parser + gate + guard + typed errors + _self_check** - `8177a73` (feat)
2. **Task 04-01-2: pinned deps + Dockerfile COPY kb/** - `772993e` (build)
3. **Task 04-01-3: kb.upload byte-stream handler + kb.state publisher** - `aa57993` (feat)
4. **Task 04-01-4: KbPanel upload loop + indicator** - `b902dc2` (feat)
5. **Task 04-01-5: mount KbPanel in VoiceRoom** - `a5d16cd` (feat)

## Files Created/Modified

- `agent/kb/parse.py` - pure parser, extraction gate, size guard, `ParsedDoc`/`KbParseError`, `_self_check`
- `agent/kb/__init__.py` - re-exports `parse`, `ParsedDoc`, `KbParseError`, `KB_WARN_TOKENS`, `KB_MAX_TOKENS`
- `agent/requirements.txt` - adds `pymupdf4llm`, `pymupdf~=1.27`, `python-docx~=1.1`
- `agent/Dockerfile` - `COPY kb/ ./kb/`
- `agent/main.py` - `_SessionKb`, byte-stream handler, `_active_tasks` GC-guard, ingest pipeline, `kb.state` publisher
- `web/app/KbPanel.tsx` - upload + KB-active indicator client component
- `web/app/VoiceRoom.tsx` - mounts `<KbPanel />` inside `<LiveKitRoom>`

## Decisions Made

- **Lazy parser imports:** `fitz`/`pymupdf4llm`/`python-docx` are imported inside `_extract_pdf`/`_extract_docx` so the pure dispatch/gate/guard path and the txt/md stdlib branch (which the self-check exercises) import without the heavy deps — the deps are absent in the sandbox but present in the image.
- **pymupdf4llm unpinned, pymupdf pinned:** the version bound that matters is on `pymupdf~=1.27` (the actual PDF engine); pinning a guessed meta-package version would violate the "never guess versions" rule.
- **Client API types verified, not guessed:** `sendFile(file, {topic})` confirmed in `livekit-client@2.20.0` `SendFileOptions`, and `useParticipantAttributes` confirmed in `@livekit/components-react@2.9.21` — so the panel compiles against real installed signatures. (Runtime round-trip behavior remains a VM gate.)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The volatile-data acceptance grep (`datetime|time\.|uuid|random|now\(\)`) initially matched a doc comment ("now()"); reworded the comment so the grep returns nothing — the criterion now passes cleanly. No code change.

## Deferred / Operator Gates (NOT marked passed)

These `[VM-INTROSPECT]` and MANUAL items require the Proxmox VM (installed livekit build, GPU/Ollama, browser + a LAN device) and are recorded as pending operator verification — NOT treated as a blocking checkpoint:

- **`[VM-INTROSPECT]` (agent rtc SDK):** confirm `ctx.room.register_byte_stream_handler` exists on the installed `~=1.5` rtc SDK, the reader is async-iterable with `reader.info` (`.name`, `.mimeType`, `.size`), and `local_participant.set_attributes` (vs `set_attribute`) is the correct setter. Fallback: text/data-stream + chunked base64 if absent.
- **`[VM-INTROSPECT]` (parser):** `pymupdf4llm.to_markdown` signature on the pinned version once installed.
- **`[VM-INTROSPECT]` (client):** `sendFile` + participant-attribute change event runtime behavior on `livekit-client@2.20.0` (types verified statically; live event flow is the gate).
- **MANUAL (VM + LAN device):** upload one each of PDF/TXT/MD/DOCX → indicator reaches `ready (1 docs)`; a scanned/empty PDF → `error` "looks scanned" and the voice loop keeps working; an unsupported type → `error` "Unsupported file type"; an oversize doc → `oversize` guard fires.

## Next Phase Readiness

- Ready for **04-02** (distill → inject once via `KB_SLOT` + indicator `distilling` state + ephemeral teardown). The `distilling` status is already in the panel union and the `_SessionKb` is ready to gain a `brief: str` field. The `kb.upload`/`kb.state` transport contract is established.
- Operator must run the VM/LAN upload gates above before relying on the live transport.

---
*Phase: 04-knowledge-base-layer*
*Completed: 2026-06-25*

## Self-Check: PASSED

- `python3 agent/kb/parse.py` → `kb.parse _self_check OK` (exit 0)
- `python3 -m py_compile agent/kb/parse.py agent/kb/__init__.py agent/main.py` → exit 0
- `cd web && npx tsc --noEmit` → exit 0; `npm run build` → compiled successfully
- All five task commits present (`8177a73`, `772993e`, `aa57993`, `b902dc2`, `a5d16cd`)
- key-files.created exist on disk
