---
status: pending-operator
phase: 04-knowledge-base-layer
plan: 04-03
requirement_ids: [KB-05]
verifies: [PERF-02]
---

# Phase 04 — KB Layer: OPERATOR VERIFICATION (the keystone flat-TTFT + cache-hit + VRAM proofs)

**Status:** PENDING OPERATOR — run on the Proxmox VM (Docker daemon + RTX 5090 + Ollama +
browser + LAN device). The execution sandbox has **no** Docker/GPU/Ollama/browser, so all four
proofs below are deferred operator gates, mirroring the Phase-1 VRAM gate and the Phase-2/3
`[VM-INTROSPECT]` deferrals. **None are marked passed by the executor** — the operator fills the
results tables with measured numbers.

**Owns:** Success Criterion 3 / **KB-05** (per-turn TTFT stays flat whether or not a KB is loaded)
and the PERF-02 re-validation at the KB peak-memory moment.

---

## `agent/metrics.py` is READ-ONLY for these proofs

The per-turn JSON line shape is the **frozen Phase-3 contract** — keys
`eou_ms / stt_ms / llm_ttft_ms / tts_ttfb_ms / e2e_ms / over_budget` (see `agent/metrics.py`
`emit_turn`, lines 148–182). These proofs only **READ** that emitted line; they do **not** modify
the emitter. `git diff --stat agent/metrics.py` must show **no change**.

The **turn-1** KB-inject `llm_ttft_ms` spike (with `over_budget: ["llm_ttft"]`) is the single
**sanctioned re-prefill** — the one-time cost of loading the distilled brief into the frozen
prefix. It is **EXPECTED, not a regression**. The whole point of KB-05 is that turn-2+ does NOT
pay it again (the brief is held in Ollama's prefix/KV cache via `keep_alive=-1`).

---

## 0. Build / deploy BEFORE verifying (stale-deploy guard)

The stack runs from **baked images** — a code edit is NOT live until the image is rebuilt. This bit
the Phase-3 UAT (stale deploy). Always rebuild + restart before live verification:

```bash
# from the repo root on the VM
set -a && . ./.env && set +a
# (re)create the pinned model with the 04-03 num_ctx Modelfile if it changed:
envsubst '${OLLAMA_MODEL}' < ollama/Modelfile \
  | docker compose exec -T ollama ollama create adept-gemma -f -
docker compose build agent web
docker compose up -d
docker compose ps          # all services Up
```

---

## Proof A — flat-TTFT (KB-05): turn-2 `llm_ttft_ms` ≪ turn-1, and ≈ no-KB turn-2

**Goal:** loading a large KB costs prefill **only on turn 1**. turn-2+ TTFT is cached and flat,
and matches a no-KB session's turn-2.

**Steps:**

1. **KB session.** Open `https://<vm-lan-ip>/` on a LAN device, start a session, and upload a
   **LARGE** KB doc (a multi-page PDF/MD containing a **distinctive fact** you can later ask about —
   e.g. a made-up project code-name or a specific number). Wait for the KB indicator to reach
   `ready (1 docs)`.
2. **Drive 3 turns.** Speak three short turns (the priming turn already warmed the prefill; these
   are user turns 1, 2, 3).
3. **Capture the per-turn metric lines** from the agent:

   ```bash
   docker compose logs agent | grep llm_ttft_ms
   ```

   Each line is the frozen JSON record. Read `llm_ttft_ms` and `over_budget` per turn.
4. **No-KB session.** Start a fresh session, do **not** upload a KB, drive 3 turns, capture the
   same metric lines.
5. **ASSERT (KB-05):**
   - turn-2(KB) `llm_ttft_ms` **≪** turn-1(KB) `llm_ttft_ms` (the cache hit — turn-1 is the one
     sanctioned re-prefill).
   - turn-2(KB) `llm_ttft_ms` **≈** turn-2(no-KB) `llm_ttft_ms` (**flat** — KB presence does not
     tax per-turn TTFT).
   - Only turn-1(KB) carries `over_budget: ["llm_ttft"]`; turn-2+ do not (expected).

**Results capture:**

| Session | Turn | `llm_ttft_ms` | `over_budget` |
|---------|------|---------------|---------------|
| KB      | 1    |               |               |
| KB      | 2    |               |               |
| KB      | 3    |               |               |
| no-KB   | 2    |               |               |

- turn-2(KB) ≪ turn-1(KB)? **[ ] yes / [ ] no**
- turn-2(KB) ≈ turn-2(no-KB) (flat)? **[ ] yes / [ ] no**
- **KB-05 verdict:** ____________________

---

## Proof B — Ollama prefix-cache-hit (Pitfall 7 cross-check)

**Goal:** confirm turn-2 is a genuine prefix-cache hit, not a silent re-eval of the whole brief
(a full re-eval = byte-drift in the frozen prefix = Pitfall 7 cache-bust).

**Steps:**

1. Inspect the Ollama prompt-eval counts around the same turns:

   ```bash
   docker compose logs ollama | grep -iE 'prompt eval|prompt_eval|n_past|cache'
   ```

2. Read the **prompt-eval token count** (the "new tokens" actually evaluated) per request:
   - **turn-1:** LARGE (the full brief + persona prefix is evaluated once).
   - **turn-2:** **SMALL** — only the new turn's tokens are evaluated; the brief prefix is reused
     from cache.

3. **Cache-BUST signature (FAIL):** if turn-2's prompt-eval count is ≈ the brief size again (a full
   re-eval), the prefix bytes drifted between turns. Investigate brief byte-stability (no
   timestamps/counters/re-serialized JSON/whitespace drift in the brief string — Pitfall 7) and the
   inject-once path (the brief must land via `update_instructions` exactly once, then stay frozen).

**Results capture:**

| Turn | prompt-eval (new tokens) | cache hit? |
|------|--------------------------|------------|
| 1    |                          | n/a (cold) |
| 2    |                          |            |

- turn-2 prompt-eval is small (cache hit, not a brief re-eval)? **[ ] yes / [ ] no**
- **Proof B verdict:** ____________________

---

## Proof C — brief token measurement → `num_ctx` pin

**Goal:** measure the REAL distilled-brief token count for a representative KB, then confirm the
`ollama/Modelfile` `num_ctx` (pinned at **8192** in 04-03-1) is the smallest value covering the
worst case `persona + brief + history + headroom`.

**Steps:**

1. Load a representative LARGE KB (as in Proof A). Capture the distilled brief length. Either log
   the brief that `distill()` returns, or measure its char length and divide by `CHARS_PER_TOKEN`
   (= 4, the `agent/kb/parse.py` estimate), or run it through the model's tokenizer:

   ```bash
   # char-based estimate (matches parse.py CHARS_PER_TOKEN=4):
   #   brief_tokens ≈ len(brief_text) / 4
   # tokenizer-accurate (optional, on the VM):
   #   docker compose exec ollama sh -c \
   #     'echo "$BRIEF" | ollama run "$OLLAMA_MODEL" --verbose' 2>&1 | grep -i 'prompt eval count'
   ```

2. Plug the measured brief token count into the accounting:

   ```
   num_ctx ≈ persona(~250) + brief(measured) + max history window(~5000) + headroom(~1440)
   ```

3. **ASSERT:** the measured worst case fits the pinned `num_ctx`. Keep **8192** if it fits; bump
   `ollama/Modelfile` only to a measured value (e.g. 12288 / 16384) **and** re-run Proof D if you
   bump. `BRIEF_TOKEN_BUDGET` (distill.py), `KB_MAX_TOKENS`/`KB_WARN_TOKENS` (parse.py), and
   `num_ctx` are coupled — adjust together.

**Results capture:**

| Quantity | Value |
|----------|-------|
| measured brief tokens |  |
| persona tokens (~250) |  |
| max history window (~5000) |  |
| headroom (~1440) |  |
| **worst-case total** |  |
| **chosen `num_ctx`** | 8192 (kept) / ____ (bumped) |

- worst case fits the chosen `num_ctx`? **[ ] yes / [ ] no**
- **Proof C verdict:** ____________________

---

## Proof D — KB-load VRAM re-check (PERF-02 re-validation)

**Goal:** three models + the larger (KB-loaded) KV cache still co-reside under the 16GB floor with
q8_0 engaged and exactly 3 GPU procs. KB load is the **peak-memory moment**.

**Steps:**

1. **Synthetic proxy (repeatable):** run the 04-03 KB-loaded mode of the validator:

   ```bash
   ./scripts/vram-validate.sh --with-kb
   # or seed the prefix from a real brief:
   KB_FIXTURE=/path/to/brief.txt ./scripts/vram-validate.sh --with-kb
   ```

   This samples peak VRAM with a `BRIEF_TOKEN_BUDGET`-sized prefix resident. It asserts: peak
   used-VRAM < `VRAM_CEILING_MB` (16384 − 1024 = **15360**), q8_0 KV engaged (FAILS LOUDLY on F16
   fallback), exactly 3 GPU procs, tag from `OLLAMA_MODEL`.

2. **Authoritative (real KB):** load a real LARGE KB via the agent UI (Proof A), then sample peak:

   ```bash
   nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits
   nvidia-smi --query-compute-apps=pid --format=csv,noheader | wc -l   # expect 3
   docker compose logs ollama | grep -iE 'flash.?attention|q8_0'        # q8_0 engaged
   ```

3. **ASSERT:** peak used-VRAM < 16384 MB (with the 1GB headroom → < 15360 MB), q8_0 engaged (NOT
   F16), exactly 3 GPU procs (ollama, whisper, kokoro — **no embedder/vector store**), with the
   pinned `num_ctx` from 04-03-1.

**Results capture:**

| Check | Synthetic (`--with-kb`) | Real KB (`nvidia-smi`) |
|-------|-------------------------|------------------------|
| peak used-VRAM (MB) |  |  |
| < 15360 MB (ceiling w/ headroom)? |  |  |
| q8_0 KV engaged (not F16)? |  |  |
| GPU procs (expect 3) |  |  |

- KB-loaded peak < 16384 MB, q8_0 engaged, 3 procs? **[ ] yes / [ ] no**
- **Proof D verdict:** ____________________

---

## Overall KB-05 / PERF-02 sign-off

| Proof | What it proves | Verdict |
|-------|----------------|---------|
| A | flat-TTFT (turn-2 ≪ turn-1, ≈ no-KB turn-2) — **KB-05** |  |
| B | Ollama prefix-cache hit (turn-2 small prompt-eval, no brief re-eval) |  |
| C | real brief tokens measured → `num_ctx` smallest covering value |  |
| D | KB-loaded peak VRAM < 16GB, q8_0 engaged, 3 procs — **PERF-02** |  |

**Operator:** ____________________  **Date:** ____________________  **VM/GPU:** ____________________
