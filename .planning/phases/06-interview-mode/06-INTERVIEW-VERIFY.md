---
status: pending-operator
phase: 06-interview-mode
plan: 06-02
requirement_ids: [MODE-04, MODE-05]
verifies: [MODE-04, MODE-05, "E4B critique-depth blocker (STATE.md line 101)"]
harness_note: All gates below need the live voice loop (Docker + RTX 5090 + Ollama + browser + LAN device) and can `import livekit` only inside the agent container. The execution sandbox has no Docker/GPU/Ollama/browser and cannot import livekit, so these are deferred operator/VM gates, mirroring the Phase-1 VRAM gate and the Phase-2/3/4/5 [VM-INTROSPECT] deferrals. NONE are marked passed by the executor.
---

# Phase 06 — Interview Mode: OPERATOR VERIFICATION (the strong-vs-weak critique gate + slow-speech endpointing)

**Status:** PENDING OPERATOR — run on the Proxmox VM (Docker daemon + RTX 5090 +
Ollama + browser + LAN device). The sandbox has **no** Docker/GPU/Ollama/browser and
**cannot import livekit**, so every gate below is a deferred operator gate. **None are
marked passed by the executor** — the operator fills the results tables with measured
observations.

**Owns:**
- **MODE-04** — one role-relevant question at a time, then wait (the loop contract).
- **MODE-05** — rubric-structured critique depth + slow-speech endpointing so a
  deliberate answer is not cut mid-thought.
- **The E4B critique-depth blocker** (STATE.md line 101): *"E4B critique depth unproven
  — gate on a strong-vs-weak answer check; keep 24GB larger-model swap behind LiveKit's
  interface."* Gate A discharges (or triggers the documented fallback for) this blocker.

**What ships sandbox-verified (already green, not re-proven here):**
- `python3 agent/interview.py` → `interview _self_check OK` — the rubric constant names
  technical accuracy / completeness / precise terminology / answer structure, enforces
  the critique → strong model answer → next-question ordering, carries NO numeric score,
  and the `render_interview_prompt` join order is unchanged from 06-01.
- `python3 -m py_compile agent/main.py` → exit 0 — the named interview endpointing
  constants (`INTERVIEW_ENDPOINTING_MIN_DELAY=0.7`, `INTERVIEW_ENDPOINTING_MAX_DELAY=5.0`)
  and the `[VM-INTROSPECT]` switch-mechanism block are syntactically valid without
  importing livekit.

---

## Frozen-contract notes (read before running any gate)

- **`agent/metrics.py` is READ-ONLY.** The per-turn JSON line shape is the frozen
  Phase-3 contract (`eou_ms / stt_ms / llm_ttft_ms / tts_ttfb_ms / e2e_ms /
  over_budget`). Phase 6 only **READS** it; `git diff --stat agent/metrics.py` must show
  **no change**. The frozen per-turn key set is not extended for interview mode.
- **Thinking stays OFF.** The critique runs through the existing session LLM
  (`openai.LLM.with_ollama(reasoning_effort="none")`, `agent/main.py`). Critique depth
  comes from **prompt structure** (the rubric), NOT reasoning tokens — turning thinking
  back on (`reasoning_effort` ≠ `"none"` / `think=true`) would break first-sentence TTS
  and TTFT and is prohibited.
- **No numeric scoring anywhere.** Gate A is a *property-style discrimination* check, not
  a number, rating, or "X out of 10" (REQUIREMENTS line 107 — permanently out of scope).

---

## 0. Build / deploy BEFORE verifying (stale-deploy guard)

The stack runs from **baked images** — a code edit is NOT live until the image is
rebuilt. This bit the Phase-3 UAT (stale deploy) and is a standing STATE.md decision.
Always rebuild + restart before live verification:

```bash
# from the repo root on the VM
set -a && . ./.env && set +a
docker compose build agent web
docker compose up -d
docker compose ps          # all services Up
```

---

## 1. [VM-INTROSPECT] — endpointing-setter probes (which switch mechanism does the installed pin support?)

The endpointing profile-switch mechanism is an **explicit unresolved assumption**
(`agent/main.py` `[VM-INTROSPECT]` block). The installed code ships **mechanism 3** (the
interview floor as the single session profile). These probes confirm whether the cleaner
mechanism 1 or 2 is available so the chosen path can be finalized. Run inside the agent
container so the introspection targets the SAME installed version the worker runs:

```bash
# 1a — Per-Agent override (mechanism 1): does Agent.__init__ accept the endpointing kwargs?
docker compose exec agent python -c "import inspect, livekit.agents as a; print(inspect.signature(a.Agent.__init__))"
# Look for: min_endpointing_delay / max_endpointing_delay / turn_detection / allow_interruptions

# 1b — AgentSession surface (cross-check the wired turn_handling dict surface)
docker compose exec agent python -c "import inspect, livekit.agents as a; print(inspect.signature(a.AgentSession.__init__))"

# 1c — Runtime mutation (mechanism 2): is there a settable turn-options surface on the session?
docker compose exec agent python -c "import inspect, livekit.agents as a; print([m for m in dir(a.AgentSession) if 'option' in m or 'update' in m])"
# Then, if an update_options exists: print its signature
docker compose exec agent python -c "import inspect, livekit.agents as a; print(inspect.signature(a.AgentSession.update_options))" 2>/dev/null || echo "no update_options surface (mechanism 2 unconfirmed)"
```

**Decision rule (record which mechanism the installed pin supports):**
- **If 1a confirms** `min_endpointing_delay`/`max_endpointing_delay`/`turn_detection` on
  `Agent.__init__` → prefer the **per-Agent override** (mechanism 1): an interview-profiled
  Agent carries the slow floor by construction (cleanest; requires re-introducing a
  per-mode Agent under Option B).
- **elif 1c confirms** a runtime `session.update_options(...)` that mutates turn options →
  use **runtime mutation on mode-enter** (mechanism 2): switch profiles in
  `handle_mode_update` without a restart.
- **else** → keep the shipped **single session-profile fallback** (mechanism 3): the
  interview floor serves both modes; accept slightly slower Learn-mode commit.

**Results capture:**

| Probe | Command | Expected | Observed |
|-------|---------|----------|----------|
| 1a Agent.__init__ kwargs | `inspect.signature(Agent.__init__)` | `min_endpointing_delay` / `max_endpointing_delay` / `turn_detection` present? | ___ |
| 1b AgentSession.__init__ | `inspect.signature(AgentSession.__init__)` | `turn_handling` accepted (dict surface) | ___ |
| 1c runtime turn-option setter | `dir` + `update_options` sig | `update_options(...)` mutates turn options? | ___ |
| **Mechanism supported by the installed pin** | — | 1 / 2 / 3 | ___ |
| **Mechanism the installed code uses** | — | 3 (single session profile, shipped) | ___ |

---

## Gate A — strong-vs-weak critique discrimination (the E4B-depth blocker gate)

**Goal (MODE-05 depth / STATE.md line 101):** the agent's critique **DISCRIMINATES** a
strong answer from a weak answer to the SAME question — it praises the strong answer's
correct/precise content AND names the specific gaps/imprecision in the weak one. It must
**NOT** praise the weak answer as good, and must **NOT** generically critique the strong
one. This is a **property-style, scripted, repeatable** check (held-out answers below) —
NOT a subjective vibe and NOT a numeric score.

**Held-out scripted material (default role = SOC analyst).** Use these EXACT answers so
the test is repeatable across runs and across model swaps. The fixed interview question
to drive (let the agent ask it, or steer to it):
**"Walk me through how you'd triage a suspected phishing email reported by a user."**

**STRONG answer (read aloud verbatim):**
> "First I'd preserve the original email and pull the headers to check the real sender
> path and SPF, DKIM, and DMARC results. I'd detonate any attachment in a sandbox and
> check the URLs against threat intel and our proxy logs to see if anyone clicked. If
> there was a click, I'd scope it — which users, did credentials get submitted, any
> mailbox rules created — then contain by resetting credentials and blocking the sender
> and the domain at the gateway. I'd record indicators of compromise and map the
> activity to the relevant MITRE ATT&CK techniques, and escalate to incident response
> if there's confirmed credential theft or lateral movement."

**WEAK answer (read aloud verbatim):**
> "I'd look at the email and see if it looks suspicious. If it seems like phishing I'd
> probably delete it and tell the user not to click anything. Then I'd let my manager
> know so they can decide what to do next."

**Steps:**
1. Toggle Interview mode, default role (SOC analyst). Let the agent ask Q1; steer to the
   triage question above if needed.
2. Read the **STRONG** answer verbatim. Capture the agent's critique + model answer
   (transcript + `docker compose logs agent`).
3. Restart the question (new session or re-toggle) and read the **WEAK** answer verbatim.
   Capture the agent's critique.
4. **ASSERT the discrimination rubric (operator pass/fail):**
   - The **strong-answer critique** acknowledges concrete correct/precise content (e.g.
     names the header/SPF-DKIM-DMARC check, sandbox detonation, scoping, containment, or
     the MITRE mapping as strengths). It does NOT invent major gaps that aren't there.
   - The **weak-answer critique** names **≥1 specific missing element or imprecise term**
     that the strong answer DID cover and the weak one did not — e.g. "you didn't inspect
     the headers / check SPF-DKIM-DMARC", "no sandboxing of the attachment", "no scoping
     of who clicked", "no containment / credential reset", "no IOC capture or ATT&CK
     mapping", "no escalation criteria". It must NOT call the weak answer good/complete.
   - **PASS** = the weak-answer critique surfaces ≥1 real gap the strong one did not
     trigger, AND the strong-answer critique is not generic/dismissive.
   - **FAIL** (weak praised as good, OR strong generically critiqued, OR critiques
     indistinguishable) → **trigger the 24GB fallback (§ "24GB fallback" below)**. This
     discharges or escalates the STATE.md line-101 blocker.

**Results capture:**

| Answer driven | Agent critique (verbatim/summary) | Gaps/strengths named | Discriminates? |
|---------------|-----------------------------------|----------------------|----------------|
| STRONG (scripted) | ___ | ___ | ___ |
| WEAK (scripted)   | ___ | ___ | ___ |

- Weak-answer critique names ≥1 real gap the strong one did not trigger? **[ ] yes**
- Strong-answer critique praises concrete correct content (not generic)? **[ ] yes**
- **Gate A verdict:** PASS / FAIL → if FAIL, 24GB fallback triggered: **[ ] yes**

---

## Gate B — slow-speech endpointing (MODE-05, no mid-thought cut-in)

**Goal:** a deliberate, pause-heavy answer is **NOT** cut in on mid-thought, and the
agent **DOES** respond promptly after a clear finish. The interview profile raises
`min_delay` to ~0.7s and `max_delay` to ~5.0s (`agent/main.py`
`INTERVIEW_ENDPOINTING_MIN_DELAY`/`INTERVIEW_ENDPOINTING_MAX_DELAY`) so a thoughtful pause
isn't read as turn-end; `MultilingualModel()` stays the semantic decider.

**Steps:**
1. In Interview mode, answer a question with a deliberate mid-thought pause, e.g. speak:
   *"Let me think…"* — pause ~1–2 seconds — *"…okay, the answer is, you'd start by
   checking the logs."*
2. **ASSERT:** the agent does NOT start critiquing during the *"let me think…"* pause; it
   waits through the pause and only responds after the clear finish. After a clean,
   complete sentence + silence, it responds promptly (within the ~5s `max_delay` ceiling,
   typically much sooner once the semantic endpointer commits).
3. **Metrics caveat (do NOT misread):** interview turns will show `over_budget:["eou"]`
   because the raised `min_delay` (~0.7s) exceeds `BUDGET_MS["eou"]=300`. This is
   **EXPECTED and correct** for deliberate-answer speech, not a regression. Confirm the
   line shape:

   ```bash
   docker compose logs agent | grep -E 'eou_ms|over_budget'
   ```

   Expected: `eou_ms` around 700ms on interview turns, with `over_budget` including
   `"eou"`. (Learn-mode turns under the shipped single-profile fallback also carry the
   raised floor — see the §1 mechanism note.)

**Results capture:**

| Observation | Expected | Observed |
|-------------|----------|----------|
| cut in on the "let me think…" pause? | NO | ___ |
| responded promptly after a clear finish? | YES | ___ |
| `eou_ms` on interview turns | ~700ms (≥ min_delay) | ___ |
| `over_budget` includes `eou`? | yes (EXPECTED, not a bug) | ___ |

- No mid-thought cut-in? **[ ] yes**
- Prompt response after a clear finish? **[ ] yes**
- `over_budget:["eou"]` understood as expected (not a regression)? **[ ] yes**
- **Gate B verdict:** ___

---

## Gate C — the loop contract per role (MODE-04, end-to-end)

**Goal:** for EACH of the three roles, exactly ONE question is asked then the agent waits;
after the answer it gives critique → strong model answer → next single question; toggling
back to Learn restores conversational behavior.

**Steps (repeat for each role):**
1. Toggle Interview mode; pick the role (`soc_analyst`, then `security_engineer`, then
   `grc`) from the panel. Confirm the RPC ack moves applying → applied.
2. Confirm the agent asks **exactly ONE** role-relevant question, then **stops and waits**
   (it does NOT ask several at once or answer its own question).
3. Give a short answer. Confirm the reply order is: **critique → strong model answer →
   next single question** (the rubric ordering), spoken (no lists/markdown).
4. Toggle back to **Learn**: confirm open conversational behavior resumes (no forced
   question loop). Note that under the shipped single-profile fallback the endpointing
   floor stays at the interview values across both modes (§1 mechanism note) — the
   *conversational contract* returns even though the silence tolerance does not drop.

**Results capture:**

| Role | One Q then waits? | critique → model answer → next? | Learn toggle restores converse? |
|------|-------------------|---------------------------------|---------------------------------|
| soc_analyst       | ___ | ___ | ___ |
| security_engineer | ___ | ___ | ___ |
| grc               | ___ | ___ | ___ |

- **Gate C verdict:** ___

---

## 24GB fallback — DOCUMENTED, not built (trigger: Gate A FAIL)

The LLM is already behind LiveKit's interface
(`openai.LLM.with_ollama(model=resolved_llm_tag())`, tag from `OLLAMA_MODEL`), so a
larger model is a **config change, not a code change**. **No 24GB code path ships in v1.**

**Swap mechanism (on a 24GB host):**
```bash
# pull a larger tag on the 24GB host, then repoint OLLAMA_MODEL and restart
ollama pull gemma4:26b           # or a Qwen3 8B tag
# edit .env: OLLAMA_MODEL=gemma4:26b
docker compose up -d agent       # the with_ollama() tag re-resolves from OLLAMA_MODEL
```

**VRAM math (why this needs a 24GB card — STACK.md):**
- `gemma4:26b` is an MoE model ≈ **18GB**; a Qwen3 8B is a comparable step-up. Neither
  fits the **16GB floor** with faster-whisper STT (~2GB) + Kokoro TTS (~2–3GB) resident.
- The shipped `gemma4:e4b` (9.6GB) is the 16GB-floor choice; the larger tags are the
  **24GB-recommended** tier.

**Model-by-mode idea (v2 / 24GB enhancement — NOT shipped):** run E4B for fast
Converse turns and a larger model only for Interview **critique** turns, where a ~1.5s
reply is acceptable (a slow critique is fine; a slow conversational reply isn't). This is
a v2/24GB enhancement, not an MVP requirement, and is not built here.

**Trigger condition:** ship the larger model ONLY if **Gate A fails** (E4B critique does
not discriminate strong vs weak even with the rubric structure). The rubric (prompt
structure) is the first-line mitigation; the 24GB swap is the documented escalation.

---

## Overall Phase-6 sign-off

| Gate | What it proves | Verdict |
|------|----------------|---------|
| 1 ([VM-INTROSPECT]) | which endpointing switch mechanism the installed pin supports (1/2/3); shipped code uses mechanism 3 | ___ |
| A | strong-vs-weak critique discrimination — the E4B-depth blocker (STATE.md line 101) discharged, or 24GB fallback triggered | ___ |
| B | slow-speech endpointing — no mid-thought cut-in; `over_budget:["eou"]` understood as expected | ___ |
| C | the per-role loop contract — one question at a time → critique → model answer → next; Learn toggle restores converse | ___ |

**Operator:** ___  **Date:** ___  **VM/GPU:** Proxmox + RTX 5090

**Residual notes:** `agent/metrics.py` stays READ-ONLY (frozen per-turn key set);
thinking stays OFF (`reasoning_effort="none"`) — critique depth is prompt structure, not
reasoning tokens. Layer-2 `InterviewState`/`next_directive` and any multi-agent handoff
are NOT built; they are reserved only if Gate A fails AND prompt structure proves
insufficient. The 24GB swap is documented, never coded, in v1.
