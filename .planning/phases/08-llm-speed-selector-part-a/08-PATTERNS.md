# Phase 8 Patterns: LLM Speed Selector (Part A) — File-by-File Analog Map

**Phase goal:** Replace the single stock LLM with two user-selectable Ollama
models (Fast E2B default / Better E4B) exposed via a plain-language UI picker,
session-persisted, swapped IN PLACE on the next turn (no AgentSession/Agent
teardown) — while preserving the v1.0 latency settings and adding a per-build
verification gate for the abliterated community GGUFs.

**Sources:** `08-CONTEXT.md` (user decisions) + `08-RESEARCH.md` (grounded in
installed `livekit-plugins-openai==1.6.4` source). Covers LLM-01..LLM-06.

This document maps each file to be created/modified onto its closest existing
analog in the codebase, with concrete code excerpts, so the planner can write
`read_first` lists and concrete actions. Files are grouped by the slice they
land in (agent swap mechanism / UI picker / pull+verify / runbook).

---

## File inventory (from CONTEXT §decisions + RESEARCH §7, §9)

| # | File | Role | Action | Closest analog |
|---|---|---|---|---|
| 1 | `agent/main.py` | MODIFY worker wiring — Fast/Better resolver, `current_model` holder, `model.update` RPC, in-place `_opts.model` swap, optional `max_completion_tokens` cap | edit | self — clone `handle_mode_update` (448–478); `resolved_llm_tag()` (127); `current_mode` holder (363); `session.tts.update_options(voice=)` in-place swap (431) |
| 2 | `web/app/ModelPanel.tsx` | NEW side-panel control (client→agent RPC, outcome labels only) | create | `web/app/InterviewPanel.tsx` (full file — `performRpc` + `ApplyState` ack + styles + duplication seam) |
| 3 | `web/app/VoiceRoom.tsx` | MODIFY side-panel row — import + mount `<ModelPanel/>` | edit | self — imports (6–9) + the panel row (84–89) |
| 4 | `ollama/pull-and-pin.sh` | MODIFY — pull BOTH tags, pin BOTH env vars, per-model fallback ladder | edit | self — `LADDER`/`resolve_tag`/`write_resolved_tag` generalize to a 2-model loop |
| 5 | `ollama/verify-build.sh` | NEW per-build gate — STRUCTURAL chat-template check (role-turn markers + diff vs stock Gemma) + streamed artifact scan | create | `scripts/vram-validate.sh` (operator-gate `fail()`/`main()` style) + `ollama/warmup.py:106-108` (`<think>` scan) |
| 6 | `.env.example` | MODIFY — add `OLLAMA_MODEL_FAST` / `OLLAMA_MODEL_BETTER` | edit | self — existing `OLLAMA_MODEL=` line (31) |
| 7 | `08-LLM-VERIFY.md` | NEW operator runbook — LLM-05 artifact gate + LLM-06 persona red-team + q8_0 re-check | create | `.planning/phases/06-interview-mode/06-INTERVIEW-VERIFY.md` (frontmatter + gate tables + operator sign-off) |

**`docker-compose.yml` needs NO edit for env** (RESEARCH §7.3): the `agent`
service uses `env_file: .env`, so the two new vars flow through automatically.
The `ollama` service intentionally has no `env_file` and its server-level
flash-attn/keep-alive/ctx vars are global — both new tags inherit them with
zero per-model config (LLM-04 by construction).

**Hand-sync seam (accepted, documented):** the two choice keys (`fast`/`better`)
in `web/app/ModelPanel.tsx` are hand-mirrored against the agent's validation set
in `agent/main.py` — exactly like `InterviewPanel.tsx` mirrors `interview.ROLES`
(there is no `model.get` RPC in the MVP).

---

## File 1 — `agent/main.py` (MODIFY — resolver + holder + RPC + in-place swap)

**Role:** Wire the effects. Generalize the tag resolver to Fast/Better, add a
`current_model` mutable holder, add a `model.update` RPC handler that validates
the choice BEFORE committing, and swap the live LLM in place via
`session.llm._opts.model = tag`. **Simpler than `mode.update`** — NO
`update_instructions` (persona/KB/mode are unchanged by a model swap) and NO
`generate_reply` (a model switch must not inject an agent turn; it lands on the
user's next real turn, LLM-02).

**Data flow:** client RPC (`{"choice":"fast"|"better"}`) → handler → validate
choice → resolve choice→tag from env → write `current_model[0]` → mutate
`session.llm._opts.model` (effective next `chat()`) → return `"applied"`.

### Analog A — `handle_mode_update` (the EXACT validate-before-commit RPC template) — main.py:448–478

```python
# agent/main.py:448-478
    async def handle_mode_update(data):
        snapshot = json.loads(data.payload)
        # mode.update is the UNTRUSTED RPC boundary. VALIDATE before committing the
        # shared holders ...
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
            await session.generate_reply(...)
        return "applied"

    ctx.room.local_participant.register_rpc_method(
        "mode.update", handle_mode_update
    )
```

`handle_model_update` clones this **validate-before-mutate** discipline (the
Phase-6 fix, CONTEXT §"Established Patterns") but is **shorter**:

```python
# agent/main.py (to write) — clone handle_mode_update's validation, drop the
# update_instructions / generate_reply (a model swap touches ONLY the LLM tag).
    async def handle_model_update(data):
        snapshot = json.loads(data.payload)
        choice = snapshot.get("choice")
        # model.update is the UNTRUSTED RPC boundary. VALIDATE the plain choice key
        # BEFORE resolving/mutating: an unknown choice must not reach _opts.model.
        # NEVER accept a raw Ollama tag from the client (LLM-01) — only fast/better.
        if choice not in MODEL_CHOICES:                # {"fast", "better"}
            logger.warning("model.update rejected: unknown choice %r", choice)
            return "error"
        current_model[0] = choice
        session.llm._opts.model = resolved_model_tag(choice)  # in-place; next chat()
        return "applied"

    ctx.room.local_participant.register_rpc_method(
        "model.update", handle_model_update
    )
```

The native RPC return value **is** the applying→applied ack (no custom
protocol). Register AFTER `session.start` so the method exists before the client
calls it. **Do NOT** call `generate_reply` on a model swap (RESEARCH §7.1) and
**do NOT** call `update_instructions` (RESEARCH §7.1 — instructions are
model-independent).

### Analog B — the in-place plugin-instance mutation — main.py:431 (`session.tts.update_options`)

The persona handler already mutates an EXISTING plugin instance in place so its
`metrics_collected` subscription survives — the exact safety property the LLM
swap needs:

```python
# agent/main.py:431  (TTS voice swapped in place — same instance, metrics survive)
        session.tts.update_options(voice=p.voice_id)
```

The LLM analog is one line, but `openai.LLM` (built by `with_ollama`) has **NO**
`update_options()` and `model` is a read-only property — so mutate the mutable
(non-frozen) `_opts` dataclass directly (RESEARCH §1.2–1.3):

```python
# agent/main.py (to write) — wrap behind a tiny helper so the private-attr reach
# is explicit + one-place. Same LLM instance ⇒ the metrics_collected handler from
# metrics.attach() (agent/metrics.py:332) survives, identical to the TTS swap.
# reasoning_effort="none" lives in the SAME _opts (re-read per chat()), so it is
# preserved automatically across the swap — no need to re-pass it.
    session.llm._opts.model = resolved_model_tag(choice)
```

> **[VM-INTROSPECT] branch (RESEARCH §1.4):** the plugin is unpinned; pin
> `livekit-plugins-openai==1.6.4` OR run the probe against whatever installs.
> **If a future version exposes `session.llm.update_options(model=...)` → prefer
> it** (cleaner public API); **else mutate `_opts.model`** (the shipped path).
> Probe:
> ```bash
> docker compose run --rm agent python -c "
> from livekit.plugins import openai
> llm = openai.LLM.with_ollama(model='x', base_url='http://ollama:11434/v1', reasoning_effort='none')
> print('has update_options:', hasattr(llm, 'update_options'))
> print('opts fields:', [f for f in vars(llm._opts)])
> import livekit.plugins.openai as p; print('plugin version:', p.__version__)"
> ```

### Analog C — the mutable epoch holder — main.py:363 (`current_mode`)

```python
# agent/main.py:363-364
    current_mode: list[str] = [interview.MODE_LEARN]
    current_role: list[str] = [interview.DEFAULT_ROLE]
```

Add a parallel `current_model` holder so the choice persists for the session
(LLM-02). **Default = Fast** (`DEFAULT_MODEL_CHOICE`), exactly as
`MODE_LEARN`/`DEFAULT_PERSONA` are the defaults-on-load:

```python
# agent/main.py (to write) — fourth mutable axis; default Fast (LLM-02)
    current_model: list[str] = [DEFAULT_MODEL_CHOICE]   # "fast"
```

> Unlike `current_persona`/`current_mode`/`current_role`, `current_model` does
> **NOT** feed `compose_instructions()` — a model swap does not re-render the
> prefix. It only drives `session.llm._opts.model`. This is the simpler axis.

### Analog D — the env-sourced tag resolver — main.py:127 (`resolved_llm_tag`)

The no-hardcoded-tag invariant generalizes from one env var to a choice→env map:

```python
# agent/main.py:127-132  (today — single OLLAMA_MODEL)
def resolved_llm_tag() -> str:
    """Read the pinned LLM tag from OLLAMA_MODEL (no hardcoded gemma tag)."""
    tag = os.environ.get("OLLAMA_MODEL", "").strip()
    if not tag:
        raise SystemExit("OLLAMA_MODEL is not set — run ollama/pull-and-pin.sh first")
    return tag
```

```python
# agent/main.py (to write) — Fast/Better resolver, SAME SystemExit-if-unset posture.
# NO hardcoded gemma tag anywhere (continues the v1.0 invariant). build_session()
# constructs at the Fast (default) tag; the swap retargets per choice.
MODEL_CHOICES = ("fast", "better")
DEFAULT_MODEL_CHOICE = "fast"
_MODEL_ENV = {"fast": "OLLAMA_MODEL_FAST", "better": "OLLAMA_MODEL_BETTER"}

def resolved_model_tag(choice: str) -> str:
    """Map a Fast/Better choice key to its pinned Ollama tag (no hardcoded tag)."""
    tag = os.environ.get(_MODEL_ENV[choice], "").strip()
    if not tag:
        raise SystemExit(f"{_MODEL_ENV[choice]} is not set — run ollama/pull-and-pin.sh first")
    return tag
```

### Analog E — the construction site — main.py:187–191 (`build_session`)

```python
# agent/main.py:187-191  (today — single resolved tag, reasoning_effort none)
        llm=openai.LLM.with_ollama(
            model=resolved_llm_tag(),
            base_url=OLLAMA_BASE_URL,
            reasoning_effort="none",
        ),
```

Construct at the **Fast** default tag; the swap retargets it later. Optionally
close the LLM-04 `num_predict` gap here (RESEARCH §1.5 — `with_ollama` does NOT
accept `max_completion_tokens`, so set it on `_opts` after construction):

```python
# agent/main.py (to write) — default to Fast; optionally cap num_predict on the
# live path (LLM-04 "capped num_predict"). chat() already forwards
# max_completion_tokens → OpenAI → Ollama num_predict when given.
        llm=openai.LLM.with_ollama(
            model=resolved_model_tag(DEFAULT_MODEL_CHOICE),
            base_url=OLLAMA_BASE_URL,
            reasoning_effort="none",
        ),
        # then (decision point, RESEARCH §8.1): session.llm._opts.max_completion_tokens = LIVE_NUM_PREDICT_CAP
```

> **Decision for the plan (RESEARCH §1.5, §8.1):** the live hot-path LLM
> currently sets NO completion cap (only warmup/distill cap `num_predict` via
> `/api/generate`). LLM-04 lists "capped num_predict" — recommend closing it here
> with a one-line `_opts.max_completion_tokens` that applies equally to both
> models. Verify the OpenAI→Ollama mapping on the VM.

### Invariants enforced in main.py
- **No second hardcoded LLM tag:** every tag resolves from an env var
  (`OLLAMA_MODEL_FAST`/`OLLAMA_MODEL_BETTER`) — RESEARCH §7.1, CONTEXT §decisions.
- **In-place swap, no teardown:** same `LLM` instance ⇒ `metrics_collected`
  subscription survives (RESEARCH §1.3); next-turn effective, no TTS interrupt.
- **Thinking stays OFF across the swap:** `reasoning_effort="none"` lives in the
  same `_opts`, re-read per `chat()` (RESEARCH §3) — carries automatically.
- **Validate-before-mutate:** reject unknown `choice` before touching
  `_opts.model` (the Phase-6 mode.update fix, CONTEXT §"Established Patterns").

---

## File 2 — `web/app/ModelPanel.tsx` (NEW — clone InterviewPanel)

**Role:** Side-panel control: a two-option segmented control / `<select>` with
**outcome labels only** ("Fast (snappier)" / "Better (more thoughtful)") — NEVER
raw Ollama tags or latency numbers (LLM-01). Holds the selection in React state
for the session (LLM-02 per-session persistence), targets the agent identity,
sends `{choice}` over the `model.update` RPC. The RPC return is the
applying→applied ack.

**Data flow:** local React state (default `"fast"`) → `performRpc({ method:
"model.update", payload: JSON.stringify({ choice }) })` → agent handler →
`"applied"`/`"error"`.

### Analog — `web/app/InterviewPanel.tsx` (the EXACT full-file template)

The duplication-seam comment to replicate verbatim (the choice keys mirror the
agent's validation set by hand — no `model.get` RPC):

```tsx
// web/app/InterviewPanel.tsx:6-11  (the seam to replicate for fast/better)
// Duplication seam (06-PATTERNS.md File 3): these mode/role keys MUST
// mirror agent/interview.py (MODE_LEARN, MODE_INTERVIEW, ROLES). There is no
// mode.get RPC in the MVP, so drift here is silent — keep in sync by hand.
const MODE_LEARN = "learn";
```

```tsx
// web/app/ModelPanel.tsx (to write) — the fast/better seam + OUTCOME labels (LLM-01)
// Duplication seam: these choice keys MUST mirror agent/main.py MODEL_CHOICES
// ("fast"/"better"). No model.get RPC in the MVP — keep in sync by hand. NEVER
// surface the raw Ollama tag here; labels are outcomes only (LLM-01).
const CHOICES = ["fast", "better"] as const;
const CHOICE_LABEL: Record<(typeof CHOICES)[number], string> = {
  fast: "Fast (snappier)",
  better: "Better (more thoughtful)",
};
```

The `ApplyState` union + `STATUS_LABEL`/`STATUS_COLOR` + `panelStyle`/
`labelStyle`/`inputStyle` are directly reusable (copy from InterviewPanel.tsx:20–63):

```tsx
// web/app/InterviewPanel.tsx:20-34  (state union + status maps — copy verbatim)
type ApplyState = "idle" | "applying" | "applied" | "error";
const STATUS_LABEL: Record<ApplyState, string> = {
  idle: "", applying: "applying…", applied: "applied",
  error: "error — could not apply",
};
const STATUS_COLOR: Record<ApplyState, string> = {
  idle: "#8b949e", applying: "#d29922", applied: "#3fb950", error: "#f85149",
};
```

The agent-identity targeting + `performRpc` + ack core to copy (only `method`,
`payload`, and the default state change):

```tsx
// web/app/InterviewPanel.tsx:73-104  (the apply() core — clone verbatim)
export default function InterviewPanel() {
  const room = useRoomContext();
  const { agent } = useVoiceAssistant();
  const [mode, setMode] = useState<string>(MODE_LEARN);       // → const [choice, setChoice] = useState("fast")  (LLM-02 default Fast)
  const [status, setStatus] = useState<ApplyState>("idle");

  async function apply() {
    setStatus("applying");
    const fallback = Array.from(room.remoteParticipants.values())[0];
    const agentIdentity = agent?.identity ?? fallback?.identity;
    if (!agentIdentity) { setStatus("error"); return; }
    try {
      const ack = await room.localParticipant.performRpc({
        destinationIdentity: agentIdentity,
        method: "mode.update",                                 // → "model.update"
        payload: JSON.stringify({ mode, role_key: roleKey }),  // → JSON.stringify({ choice })
      });
      setStatus(ack === "applied" ? "applied" : "error");      // native RPC return IS the ack
    } catch { setStatus("error"); }
  }
```

The `<select>` rendering (two options, outcome labels) mirrors InterviewPanel's
Mode select (118–119) over `CHOICES`/`CHOICE_LABEL`. **Default selection = Fast**
(`useState("fast")` — LLM-02).

### Invariants enforced in ModelPanel
- **Outcome labels only (LLM-01):** never render the raw tag or latency numbers.
- **Per-session persistence (LLM-02):** React state holds the choice for the
  session; the agent holds `current_model[0]`. No cross-session persistence
  (matches the ephemeral posture).
- **Must render inside `<LiveKitRoom>`** for room context (same as siblings).

---

## File 3 — `web/app/VoiceRoom.tsx` (MODIFY — mount the panel)

**Role:** One import + one JSX line to slot `<ModelPanel />` into the existing
side-panel row. Must render inside `<LiveKitRoom>` for room context.

### Analog — the existing panel row (self) — VoiceRoom.tsx:6–9, 84–89

```tsx
// web/app/VoiceRoom.tsx:6-9  (imports)
import InterviewPanel from "./InterviewPanel";
import KbPanel from "./KbPanel";
import PersonaPanel from "./PersonaPanel";
import Transcript from "./Transcript";

// web/app/VoiceRoom.tsx:84-89  (the row — add <ModelPanel/> alongside)
      <div style={{ display: "flex", gap: "1rem", alignItems: "flex-start", marginTop: "1rem" }}>
        <PersonaPanel />
        <InterviewPanel />
        <KbPanel />
        <Transcript />
      </div>
```

Add `import ModelPanel from "./ModelPanel";` and place `<ModelPanel />` in the
row (CONTEXT §"Integration Points").

---

## File 4 — `ollama/pull-and-pin.sh` (MODIFY — two tags, two env vars, two ladders)

**Role:** Pull BOTH community tags and pin BOTH env vars, each with its own
fallback ladder rung (CONTEXT §"Model Pull"). The existing single-tag
`resolve_tag()` + `write_resolved_tag()` generalize to a per-model loop writing
two env keys.

**Data flow:** for each model (fast, better): walk its ladder → first tag that
pulls + appears in `ollama list` wins → write `OLLAMA_MODEL_<MODEL>=<tag>` to
`.env`.

### Analog — the single-model ladder (self) — pull-and-pin.sh:18–57

```bash
# ollama/pull-and-pin.sh:18-39  (today — one LADDER, one OLLAMA_MODEL line)
readonly LADDER=(
  "gemma4:e4b-it-q4_K_M"
  "gemma4:e4b"
  "gemma3:4b-it-qat"
)
write_resolved_tag() {
  local tag="$1"
  if grep -q '^OLLAMA_MODEL=' "${ENV_FILE}"; then
    sed -i "s|^OLLAMA_MODEL=.*|OLLAMA_MODEL=${tag}|" "${ENV_FILE}"
  else
    printf 'OLLAMA_MODEL=%s\n' "${tag}" >>"${ENV_FILE}"
  fi
}
```

Generalize to per-model ladders + a parameterized env-var writer (RESEARCH §7.3):

```bash
# ollama/pull-and-pin.sh (to write) — two ladders, parameterized writer.
# Fast ladder:   evalengine/unbound-e2b:latest  → gemma4:e2b
# Better ladder: defyma85/gemma-4-E4B-it-ultra-uncensored-heretic-Q4_K_M_gguf:latest
#                → gemma4:e4b  (or the v1.0-proven gemma4:e4b-it-q4_K_M)
readonly FAST_LADDER=(  "evalengine/unbound-e2b:latest" "gemma4:e2b" )
readonly BETTER_LADDER=( "defyma85/gemma-4-E4B-it-ultra-uncensored-heretic-Q4_K_M_gguf:latest" "gemma4:e4b" )

write_resolved_tag() {   # $1=ENV_KEY  $2=tag  (was hardcoded OLLAMA_MODEL)
  local key="$1" tag="$2"
  if grep -q "^${key}=" "${ENV_FILE}"; then
    sed -i "s|^${key}=.*|${key}=${tag}|" "${ENV_FILE}"
  else
    printf '%s=%s\n' "${key}" "${tag}" >>"${ENV_FILE}"
  fi
}
# main(): resolve FAST_LADDER → write OLLAMA_MODEL_FAST; resolve BETTER_LADDER →
# write OLLAMA_MODEL_BETTER. resolve_tag() takes the ladder array by name.
```

> **`OLLAMA_MODEL` back-compat (RESEARCH §7.3):** keep `OLLAMA_MODEL` pointing at
> the **Fast** (default) tag so the existing readers (`warmup.py`,
> `vram-validate.sh`, `kb/distill.py`, `Modelfile`) keep working unchanged. Add
> the two new vars for the picker on top.

---

## File 5 — `ollama/verify-build.sh` (NEW — per-build LLM-05 gate)

**Role:** Standalone per-build verification run at **pull time** (NOT agent
startup — avoids boot-latency, CONTEXT §"Per-Build Verification"). Takes a tag
argument; asserts (a) the chat template is STRUCTURALLY sane — it contains the
expected role-turn markers AND diffs cleanly against the stock Gemma template
(catching a malformed-but-nonempty template, the abliterated-build failure mode,
RESEARCH §6), (b) thinking-off suppresses reasoning — no stray
`<think>`/`<|channel|>`/`<|analysis|>` artifacts in streamed output. Any
malformed template or artifact ⇒ FAIL ⇒ operator falls back to the stock rung.

**Data flow:** `verify-build.sh <tag>` → `ollama show --template` (role-turn
marker assert + diff against stock Gemma template) → streamed `/api/generate`
with `think:false` → accumulate → scan for artifact tokens → exit 0 (PASS) /
non-zero (FAIL).

### Analog A — the operator-gate script skeleton — scripts/vram-validate.sh:58, 175–197

```bash
# scripts/vram-validate.sh:58  (the fail() idiom to copy)
fail() { echo "FAIL: $*" >&2; exit 1; }

# scripts/vram-validate.sh:175-197  (main() structure: assert → assert → PASS line)
main() {
  parse_args "$@"
  require_tag
  command -v nvidia-smi >/dev/null || fail "nvidia-smi not found"
  ...
  assert_kv_quant_engaged
  assert_three_gpu_procs
  ...
  echo "PASS (${mode_note}): STT+LLM+TTS co-resident at ${peak} MB ..."
}
main "$@"
```

`verify-build.sh` mirrors this exact shape: `set -euo pipefail`, a `fail()`
helper, `main()` that runs each check and prints a single `PASS`/`FAIL` line. It
runs `ollama` inside the model container like `pull-and-pin.sh`'s `ollama_exec`:

```bash
# ollama/pull-and-pin.sh:27-29  (container exec idiom to reuse)
ollama_exec() {
  docker compose exec -T "${OLLAMA_CONTAINER}" ollama "$@"
}
```

### Analog B — the artifact scan — ollama/warmup.py:106–108

The existing `<think>`-only scan is the kernel; LLM-05 broadens it to the full
marker set (RESEARCH §3, §4.2):

```python
# ollama/warmup.py:106-108  (today — narrow, warmup-only)
    output = "".join(text_parts)
    if "<think>" in output or "</think>" in output:
        raise RuntimeError("thinking is ON — <think> preamble present; expected think=false")
```

```bash
# ollama/verify-build.sh (to write) — Check A (STRUCTURAL template) + Check B (broadened scan).
# Artifact superset to scan: <think> </think> <|channel|> <|analysis|> <|message|> <|start|> <|end|>
TAG="$1"
STOCK="${2:-}"   # optional stock Gemma fallback rung to diff against (gemma4:e2b / gemma4:e4b)
# Check A — STRUCTURAL chat-template sanity. A non-empty-only test would PASS a
# malformed-but-nonempty template (the abliterated-build failure mode, RESEARCH §6),
# so (1) assert the Gemma role-turn markers are present, then (2) diff against the
# stock Gemma template to surface structural drift (a real chat-template diff).
tmpl="$(ollama_exec show --template "$TAG")"
printf '%s' "$tmpl" | grep -q '<start_of_turn>' \
  && printf '%s' "$tmpl" | grep -q '<end_of_turn>' \
  || fail "malformed/missing chat template for $TAG — no role-turn structure"
if [ -n "$STOCK" ]; then
  diff <(printf '%s' "$tmpl") <(ollama_exec show --template "$STOCK") \
    || echo "NOTE: $TAG chat-template diff vs stock $STOCK (review above)"
fi
# Check B — thinking-off artifact scan over the accumulated raw stream
curl -s "${OLLAMA_BASE_URL}/api/generate" \
  -d "{\"model\":\"$TAG\",\"prompt\":\"Think step by step, then answer: what is 17*23?\",\"stream\":true,\"think\":false,\"options\":{\"num_predict\":256}}" \
  | python3 -c 'import sys,json; out="".join(json.loads(l).get("response","") for l in sys.stdin if l.strip());
markers=["<think>","</think>","<|channel|>","<|analysis|>","<|message|>","<|start|>","<|end|>"];
hit=[m for m in markers if m in out];
sys.exit(("ARTIFACT LEAK: "+",".join(hit)) if hit else 0)' \
  || fail "$TAG leaked reasoning artifacts with think=false — fall back to the stock rung"
echo "PASS: $TAG template sane + no reasoning-artifact leak (think=false)"
```

> **Fallback wiring (RESEARCH §4.3):** on a FAIL the operator drops to the stock
> rung (Fast→`gemma4:e2b`, Better→`gemma4:e4b`) via `pull-and-pin.sh`'s ladder
> and re-runs `verify-build.sh`. Operator-gated (real GPU), unsigned until run —
> same posture as the v1.0 VM gates.

> **q8_0 re-check carry-forward (RESEARCH §2.3):** both new GGUFs are off the
> stock-Gemma flash-attn path, so `scripts/vram-validate.sh` must be re-run
> per tag to confirm q8_0 did NOT silently fall back to F16. This is an existing
> script reused, not a new one — note it in the runbook (File 7), not here.

---

## File 6 — `.env.example` (MODIFY — two new tag vars)

**Role:** Document the two new env vars the picker resolves through.

### Analog — the existing single tag line (self) — .env.example:26–31

```bash
# .env.example:26-31  (today)
# Ollama VRAM-budget env (Plan 01-02 validates these empirically).
OLLAMA_FLASH_ATTENTION=1
OLLAMA_KV_CACHE_TYPE=q8_0
OLLAMA_KEEP_ALIVE=-1
# LLM tag resolved by ollama/pull-and-pin.sh (01-02). Rung 1 verified real:
OLLAMA_MODEL=gemma4:e4b-it-q4_K_M
```

```bash
# .env.example (to write) — add two picker tags; keep OLLAMA_MODEL as the Fast
# back-compat alias for warmup/vram/distill/Modelfile (RESEARCH §7.3).
# Two user-selectable tags resolved by ollama/pull-and-pin.sh (Phase 8, LLM-03).
# Fast = default (LLM-02). NO hardcoded gemma tag in code — agent reads these.
OLLAMA_MODEL_FAST=evalengine/unbound-e2b:latest
OLLAMA_MODEL_BETTER=defyma85/gemma-4-E4B-it-ultra-uncensored-heretic-Q4_K_M_gguf:latest
# Back-compat: existing scripts (warmup/vram/distill) read OLLAMA_MODEL — point it
# at the Fast/default tag so they keep working unchanged.
OLLAMA_MODEL=evalengine/unbound-e2b:latest
```

> Server-level latency env (`OLLAMA_FLASH_ATTENTION`/`OLLAMA_KV_CACHE_TYPE`/
> `OLLAMA_KEEP_ALIVE`/`OLLAMA_CONTEXT_LENGTH`/`OLLAMA_NUM_PARALLEL`) is UNCHANGED
> and applies to BOTH tags by construction (LLM-04, RESEARCH §2.3).

---

## File 7 — `08-LLM-VERIFY.md` (NEW — operator runbook for LLM-05 + LLM-06)

**Role:** Operator-gated, signed-on-the-real-GPU runbook for the qualitative
gates that cannot run in the sandbox: the LLM-05 artifact gate (driven by
`verify-build.sh` per tag), the LLM-06 persona red-team probe, the per-tag q8_0
re-check, the in-place-swap live proof, and the cold-switch behavior note.
**None marked passed by the executor.**

**Data flow:** N/A (documentation). Mirrors the Phase-6 VERIFY structure exactly.

### Analog — `06-INTERVIEW-VERIFY.md` (frontmatter + build-first guard + gate tables + sign-off)

```markdown
<!-- 06-INTERVIEW-VERIFY.md:1-8  (the frontmatter shape to copy) -->
---
status: pending-operator
phase: 06-interview-mode
plan: 06-02
requirement_ids: [MODE-04, MODE-05]
verifies: [MODE-04, MODE-05, "E4B critique-depth blocker (STATE.md line 101)"]
harness_note: All gates below need the live voice loop (Docker + RTX 5090 + Ollama + browser + LAN device) ...
---
```

```markdown
<!-- 06-INTERVIEW-VERIFY.md:54-66  (the stale-deploy build-first guard to copy) -->
## 0. Build / deploy BEFORE verifying (stale-deploy guard)
The stack runs from baked images — a code edit is NOT live until the image is rebuilt.
docker compose build agent web && docker compose up -d && docker compose ps
```

`08-LLM-VERIFY.md` adopts: the `status: pending-operator` frontmatter
(`verifies: [LLM-05, LLM-06, "q8_0 F16-fallback re-check per new GGUF"]`), the
build-first guard, then per-gate sections with **Results capture** tables and an
**Overall sign-off** table (mirroring 06's Gates A/B/C + the §"24GB fallback"
documented-not-built escalation):

- **Gate 1 [VM-INTROSPECT]** — `update_options` vs `_opts.model` probe
  (RESEARCH §1.4); record which swap path the installed pin uses.
- **Gate A (LLM-05)** — run `ollama/verify-build.sh <tag>` for BOTH community
  tags; STRUCTURAL chat-template sanity (role-turn markers present AND a real diff
  vs the stock Gemma template, RESEARCH §6) + no artifact leak. FAIL → fall back
  to the stock rung (RESEARCH §4). Mirrors Gate A's PASS/FAIL → documented-fallback structure.
- **Gate B (LLM-06)** — persona-boundary red-team: 3–5 boundary prompts through
  the agent's **actual persona prompt** (UNCHANGED); operator judges
  refusal-equivalent behavior (redirects to concepts/defenses, no step-by-step
  attack instructions). Qualitative PASS/FAIL like the Phase-6 strong-vs-weak
  critique gate. Keep prompts as *shape* descriptions in the runbook, not
  committed attack-cookbook fixtures (RESEARCH §5).
- **Gate C (live swap)** — toggle Fast↔Better mid-session; assert the swap lands
  on the NEXT turn, current TTS is NOT interrupted, no agent turn is injected,
  and `docker compose logs agent` shows the new tag serving (LLM-02). Note the
  one-time cold-switch latency on the first turn after a switch (single-resident
  eviction, RESEARCH §2.2) — EXPECTED, not a regression.
- **Gate D (q8_0 re-check)** — re-run `scripts/vram-validate.sh` per new tag;
  confirm no F16 fallback (RESEARCH §2.3).

> **LLM-06 escalation framing (RESEARCH §5, §8.5):** the persona prompt is the
> sole content guardrail and is UNCHANGED (out of scope to edit, CONTEXT
> §specifics). If Gate B FAILs, that is a **finding to escalate**, NOT a silent
> scope expansion — editing the persona would be a follow-up phase.

---

## Cross-cutting invariants (CONTEXT §decisions + RESEARCH §7 — must not break)

1. **No hardcoded model tag:** every tag resolves from
   `OLLAMA_MODEL_FAST`/`OLLAMA_MODEL_BETTER`; `SystemExit` if unset (the v1.0
   invariant, generalized).
2. **In-place swap, no teardown:** same `LLM` instance ⇒ `metrics_collected`
   survives; next-turn effective; current TTS uninterrupted; no `generate_reply`
   and no `update_instructions` on a model swap.
3. **Validate-before-mutate:** reject an unknown `choice` BEFORE touching
   `_opts.model` (the Phase-6 mode.update fix). NEVER accept a raw tag from the
   client (LLM-01).
4. **Thinking stays OFF for both models:** `reasoning_effort="none"` in the
   shared `_opts`, re-read per `chat()` — carries across the swap automatically.
5. **Latency settings apply to BOTH models with zero per-model config:**
   server-level flash-attn / q8_0 / keep-alive / ctx=8192 / num_parallel=1 are
   global on the `ollama` service (LLM-04). No per-model divergence.
6. **Single-resident VRAM:** keep-alive evicts the prior model on switch; do NOT
   raise `OLLAMA_MAX_LOADED_MODELS`; co-residency is Phase 10 (Part C).
7. **Persona prompt UNCHANGED:** it is the sole content guardrail; LLM-06
   verifies it, does not edit it.
8. **Build-from-baked-images:** any agent/web edit requires
   `docker compose build web agent && docker compose up -d` before live
   verification (the `[VM-INTROSPECT]` probe and all live gates run against the
   rebuilt image).

---

## Requirement → file map (RESEARCH §9)

| Req | Mechanism | File(s) |
|-----|-----------|---------|
| LLM-01 | Two-option picker, outcome labels only, never raw tags | File 2 `ModelPanel.tsx` |
| LLM-02 | Default Fast; per-session React state + `current_model[0]`; `_opts.model` swap next-turn, no TTS interrupt | Files 1 + 2 |
| LLM-03 | Both pulled via Ollama; agent targets selected tag via `_opts.model` mutation | Files 1 + 4 |
| LLM-04 | Server-level flash-attn/q8_0/keep-alive/ctx apply to both; `reasoning_effort=none` in `_opts`; optional `_opts.max_completion_tokens` cap | File 1 + compose env (unchanged) |
| LLM-05 | Per-build STRUCTURAL `ollama show --template` check (role-turn markers + diff vs stock Gemma) + streamed artifact scan; fallback ladder rung | Files 5 + 4 + 7 |
| LLM-06 | Operator-gated persona-boundary red-team (persona UNCHANGED, verified intact) | File 7 |

---

## Suggested slice boundaries

- **Slice A (agent swap + UI picker — the vertical slice):** File 1 (resolver +
  holder + `model.update` RPC + in-place swap), File 2 (`ModelPanel.tsx`), File 3
  (VoiceRoom mount), File 6 (`.env.example`). Sandbox-verifiable to `py_compile` /
  type-check; live swap gated to the VM.
- **Slice B (pull + per-build verify + runbook):** File 4 (`pull-and-pin.sh`
  two-model extension), File 5 (`verify-build.sh`), File 7 (`08-LLM-VERIFY.md`).
  Operator-gated on the real GPU.
