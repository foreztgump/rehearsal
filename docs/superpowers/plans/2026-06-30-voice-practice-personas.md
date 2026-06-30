# Voice Practice Personas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Adept a broader voice-practice tool by changing the default persona to Voice Fluency Coach, moving Cybersecurity Trainer into presets, adding broad persona presets, and adding Drill and Roleplay voice modes.

**Architecture:** Keep the existing persona and mode RPCs. Extend the current pure prompt modules and client constants instead of adding agent classes or persistence. Compose mode behavior onto the existing persona + KB prompt so personas remain the identity and modes remain the practice pattern.

**Tech Stack:** Python 3.11 prompt helpers, LiveKit Agents runtime wiring, Next.js/React TypeScript client constants, Node native type stripping for existing TS checks where used.

---

## File Structure

- `agent/persona.py`: owns the default persona prompt and byte-stable self-check.
- `agent/interview.py`: historical name, now also owns voice-practice mode prompt fragments. Keep it livekit-free.
- `agent/main.py`: composes persona + KB + mode instructions and validates RPC payloads.
- `agent/endpointing.py`: keeps Interview on deliberate endpointing and all other modes snappy.
- `tests/test_endpointing.py`: pure truth table for endpointing mode behavior.
- `web/app/PersonaPanel.tsx`: mirrors the server default persona.
- `web/app/personaPresets.ts`: owns preset data.
- `web/app/avatarConfig.ts`: maps preset display names to avatar mood/body.
- `web/app/InterviewPanel.tsx`: existing mode picker, relabeled as practice mode.
- `CHANGELOG.md`: documents the user-facing preset and mode change.

## Task 1: Change the Default Persona

**Files:**
- Modify: `agent/persona.py`
- Modify: `agent/main.py`
- Modify: `web/app/PersonaPanel.tsx`
- Test: `agent/persona.py`

- [ ] **Step 1: Update the golden expectation first**

In `agent/persona.py`, replace `EXPECTED_DEFAULT` with this exact string:

```python
EXPECTED_DEFAULT: str = (
    "You are a Voice Fluency Coach: a practical spoken-practice partner who helps "
    "learners explain ideas clearly, confidently, and precisely. You can coach across "
    "technical, business, career, and everyday professional topics. "
    "Hold a natural spoken conversation. Pull the learner into articulating the subject "
    "out loud: ask focused questions, have them explain concepts back to you, and build on "
    "their answers rather than lecturing. "
    "Assume working familiarity; use standard practitioner terms without over-explaining. "
    "Keep replies short and spoken-friendly, a few sentences at most. "
    "When they use sloppy or imprecise terminology, gently correct it toward precise "
    "practitioner phrasing — name the right term, say it plainly, and move on without "
    "scolding. "
    "Keep replies short and spoken-friendly: a sentence or two at a time, no bullet lists, "
    "no markdown, no code blocks. You are a conversation partner, not a written document. "
)
```

- [ ] **Step 2: Run the persona self-check and confirm it fails**

Run:

```bash
python3 agent/persona.py
```

Expected: FAIL with `AssertionError: default persona text drifted from golden`.

- [ ] **Step 3: Replace the server default role**

In `agent/persona.py`, replace `ROLE_PREAMBLE` with:

```python
ROLE_PREAMBLE: str = (
    "You are a Voice Fluency Coach: a practical spoken-practice partner who helps "
    "learners explain ideas clearly, confidently, and precisely. You can coach across "
    "technical, business, career, and everyday professional topics. "
    "Hold a natural spoken conversation. Pull the learner into articulating the subject "
    "out loud: ask focused questions, have them explain concepts back to you, and build on "
    "their answers rather than lecturing."
)
```

In `DEFAULT_PERSONA`, change the display name:

```python
DEFAULT_PERSONA = Persona(
    role_text=ROLE_PREAMBLE,
    display_name="Voice Fluency Coach",
    difficulty="intermediate",
    verbosity="balanced",
    correction="gentle",
    voice_id="af_bella",
)
```

- [ ] **Step 4: Replace the hardcoded startup greeting**

In `agent/main.py`, replace `GREETING_INSTRUCTIONS` with:

```python
GREETING_INSTRUCTIONS = (
    "Greet the user briefly and invite them to start speaking about a topic they "
    "want to practice."
)
```

- [ ] **Step 5: Mirror the default in the web client**

In `web/app/PersonaPanel.tsx`, change `DEFAULT_PERSONA` to:

```ts
export const DEFAULT_PERSONA: Persona = {
  role_text: "",
  display_name: "Voice Fluency Coach",
  difficulty: "intermediate",
  verbosity: "balanced",
  correction: "gentle",
  voice_id: "af_bella",
};
```

- [ ] **Step 6: Run the persona self-check**

Run:

```bash
python3 agent/persona.py
```

Expected: PASS and stderr contains `persona _self_check OK`.

- [ ] **Step 7: Commit**

```bash
git add agent/persona.py agent/main.py web/app/PersonaPanel.tsx
git commit -m "feat: change default voice practice persona"
```

## Task 2: Add Voice-Practice Modes on the Server

**Files:**
- Modify: `agent/interview.py`
- Modify: `agent/main.py`
- Modify: `agent/endpointing.py`
- Modify: `tests/test_endpointing.py`
- Test: `agent/interview.py`
- Test: `tests/test_endpointing.py`

- [ ] **Step 1: Add failing endpointing coverage**

Append these tests to `tests/test_endpointing.py`:

```python
def test_drill_mode_uses_snappy_converse_floor():
    result = endpointing.endpointing_for_mode(interview.MODE_DRILL)
    assert result["min_delay"] == endpointing.CONVERSE_MIN_DELAY
    assert result["max_delay"] == endpointing.CONVERSE_MAX_DELAY


def test_roleplay_mode_uses_snappy_converse_floor():
    result = endpointing.endpointing_for_mode(interview.MODE_ROLEPLAY)
    assert result["min_delay"] == endpointing.CONVERSE_MIN_DELAY
    assert result["max_delay"] == endpointing.CONVERSE_MAX_DELAY
```

Also add the two calls to the `__main__` block:

```python
    test_drill_mode_uses_snappy_converse_floor()
    test_roleplay_mode_uses_snappy_converse_floor()
```

- [ ] **Step 2: Run endpointing test and confirm it fails**

Run:

```bash
python3 tests/test_endpointing.py
```

Expected: FAIL with `AttributeError` for `MODE_DRILL`.

- [ ] **Step 3: Add mode constants and compact mode prompts**

In `agent/interview.py`, replace the mode constant block with:

```python
# Byte-stable mode keys. MODE_LEARN is the default (MODE-01) — open conversation,
# unchanged from Phases 2-5. The other modes add a voice-practice pattern.
MODE_LEARN: str = "learn"
MODE_DRILL: str = "drill"
MODE_ROLEPLAY: str = "roleplay"
MODE_INTERVIEW: str = "interview"
MODES: tuple[str, ...] = (MODE_LEARN, MODE_DRILL, MODE_ROLEPLAY, MODE_INTERVIEW)
```

After `CRITIQUE_CONTRACT`, add:

```python
MODE_PROMPTS: dict[str, str] = {
    MODE_DRILL: (
        "Use Drill mode. Ask one short question at a time about the current persona's "
        "domain. After the learner answers, give one concise correction or confirmation, "
        "then ask the next question. Keep the pace brisk and do not lecture."
    ),
    MODE_ROLEPLAY: (
        "Use Roleplay mode. Simulate a realistic stakeholder, customer, peer, or "
        "interviewer relevant to the current persona's domain. Stay in character, create "
        "light friction, and ask one spoken prompt at a time. Offer brief feedback only "
        "when the learner asks or the scenario naturally ends."
    ),
}
```

- [ ] **Step 4: Broaden interview roles**

Replace `ROLES` and `DEFAULT_ROLE` in `agent/interview.py` with:

```python
ROLES: dict[str, str] = {
    "general_professional": (
        "The target is a general professional interview. Draw questions from clear "
        "communication, judgment, tradeoffs, collaboration, and examples from the "
        "learner's own experience."
    ),
    "software_engineer": (
        "The target is a software engineering interview. Draw questions from debugging, "
        "system design, code quality, testing, tradeoffs, and production ownership."
    ),
    "ai_ml_practitioner": (
        "The target is an AI or machine-learning practitioner interview. Draw questions "
        "from model behavior, evaluation, data quality, applied GenAI systems, safety, "
        "and deployment tradeoffs."
    ),
    "data_analyst": (
        "The target is a data analyst interview. Draw questions from metrics, SQL-style "
        "reasoning, dashboards, experiment interpretation, stakeholder questions, and "
        "turning data into business insight."
    ),
    "cloud_devops": (
        "The target is a cloud or DevOps interview. Draw questions from containers, "
        "CI/CD, reliability, observability, incident response, cost, and operational "
        "tradeoffs."
    ),
    "cybersecurity": (
        "The target is a cybersecurity practitioner interview. Draw questions from "
        "threats, controls, incident response, identity, vulnerability management, "
        "security architecture, and risk."
    ),
    "product_manager": (
        "The target is a product management interview. Draw questions from product "
        "sense, prioritization, discovery, roadmaps, stakeholder tradeoffs, and metrics."
    ),
    "sales_customer_success": (
        "The target is a sales or customer success interview. Draw questions from "
        "discovery, objection handling, customer outcomes, renewals, difficult calls, "
        "and concise executive communication."
    ),
    "leadership": (
        "The target is a leadership interview. Draw questions from delegation, conflict, "
        "decision-making, feedback, executive communication, and team accountability."
    ),
    "grc_policy": (
        "The target is a governance, risk, compliance, or policy interview. Draw "
        "questions from controls, audit evidence, risk treatment, policy reasoning, "
        "vendor risk, and business alignment."
    ),
}

DEFAULT_ROLE: str = "general_professional"
```

- [ ] **Step 5: Add a mode render helper**

Add this function below `render_interview_prompt`:

```python
def render_mode_prompt(mode: str, role_key: str = DEFAULT_ROLE) -> str:
    """Return the compact voice-practice prompt fragment for ``mode``.

    Learn mode adds no extra fragment. Interview keeps its role-specific block.
    Drill and Roleplay use fixed prompt fragments and the current persona supplies
    the domain identity.
    """
    if mode == MODE_LEARN:
        return ""
    if mode == MODE_INTERVIEW:
        return render_interview_prompt(role_key)
    return MODE_PROMPTS[mode]
```

- [ ] **Step 6: Extend the interview self-check**

In `agent/interview.py` `_self_check`, after the role loop, add:

```python
    assert render_mode_prompt(MODE_LEARN) == "", "learn mode should add no prompt fragment"
    assert MODE_PROMPTS[MODE_DRILL] in render_mode_prompt(MODE_DRILL), "drill prompt missing"
    assert MODE_PROMPTS[MODE_ROLEPLAY] in render_mode_prompt(MODE_ROLEPLAY), (
        "roleplay prompt missing"
    )
    assert ROLES[DEFAULT_ROLE] in render_mode_prompt(MODE_INTERVIEW, DEFAULT_ROLE), (
        "interview role descriptor missing from mode render"
    )
```

- [ ] **Step 7: Run the interview self-check**

Run:

```bash
python3 agent/interview.py
```

Expected: FAIL because `EXPECTED_DEFAULT_INTERVIEW` still contains the old SOC default.

- [ ] **Step 8: Update the interview golden**

Replace `EXPECTED_DEFAULT_INTERVIEW` with this exact string:

```python
EXPECTED_DEFAULT_INTERVIEW: str = (
    "You are conducting a realistic spoken mock interview for the role described "
    "below. Play the part of an experienced, professional interviewer who probes "
    "the candidate's depth with focused, role-relevant questions. "
    "The target is a general professional interview. Draw questions from clear "
    "communication, judgment, tradeoffs, collaboration, and examples from the "
    "learner's own experience. "
    "Ask EXACTLY ONE role-relevant question at a time, then STOP and WAIT for the "
    "candidate's spoken answer. Do not ask several questions at once, do not answer "
    "your own question, and do not move on until they have responded. "
    "After the candidate answers, assess their answer against four qualitative "
    "dimensions: technical accuracy — is what they said correct; completeness — did "
    "they cover the parts that matter or leave gaps; precise practitioner terminology "
    "— did they use the right terms exactly or stay vague; and the structure and "
    "clarity of the answer — was it organised and easy to follow. Do NOT attach a "
    "number or grade; judge the answer qualitatively, in words only. Then respond in "
    "this fixed order, spoken aloud and never as a written list. First, give a SHORT "
    "critique that names what was genuinely strong AND what was missing or imprecise — "
    "be concrete and specific to what they actually said, not generic praise. Second, "
    "demonstrate a STRONG model answer to the same question, the kind an expert in this "
    "role would give. Third, ask the next single role-relevant question, then stop and "
    "wait. Example of the shape only (use their real answer, not this): you were "
    "accurate on the detection step and used the right term, but you skipped the "
    "containment stage; a strong answer would also walk through isolating the host; "
    "next question, … "
    "Keep replies short and spoken-friendly: a sentence or two at a time, no bullet lists, "
    "no markdown, no code blocks. You are a conversation partner, not a written document."
)
```

- [ ] **Step 9: Compose persona + KB + mode in the runtime**

In `agent/main.py`, replace `compose_instructions()` with:

```python
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
```

- [ ] **Step 10: Validate all supported modes in the RPC handler**

In `agent/main.py` `handle_mode_update`, replace the mode and role validation block with:

```python
        if new_mode not in interview.MODES:
            logger.warning("mode.update rejected: unknown mode %r", new_mode)
            return "error"
        if new_role not in interview.ROLES:
            logger.warning("mode.update rejected: unknown role_key %r", new_role)
            return "error"
```

Keep the existing assignment, `agent.update_instructions`, `session.update_options`, and first interview question behavior unchanged.

- [ ] **Step 11: Confirm endpointing still treats only Interview as slow**

No implementation change is needed in `agent/endpointing.py` if it checks only `MODE_INTERVIEW`. Update comments that say "Learn/Converse" to say "non-Interview modes" if they are now misleading.

- [ ] **Step 12: Run server checks**

Run:

```bash
python3 agent/interview.py
python3 tests/test_endpointing.py
python3 agent/persona.py
```

Expected: all pass with:

```text
interview _self_check OK
ok: endpointing selector truth table
persona _self_check OK
```

- [ ] **Step 13: Commit**

```bash
git add agent/interview.py agent/main.py agent/endpointing.py tests/test_endpointing.py
git commit -m "feat: add voice practice modes"
```

## Task 3: Update the Web Practice Mode Picker

**Files:**
- Modify: `web/app/InterviewPanel.tsx`
- Test: `npm --prefix web run typecheck`

- [ ] **Step 1: Expand client mode and role constants**

In `web/app/InterviewPanel.tsx`, replace the constants near the top with:

```ts
const MODE_LEARN = "learn";
const MODE_DRILL = "drill";
const MODE_ROLEPLAY = "roleplay";
const MODE_INTERVIEW = "interview";
const ROLES = [
  "general_professional",
  "software_engineer",
  "ai_ml_practitioner",
  "data_analyst",
  "cloud_devops",
  "cybersecurity",
  "product_manager",
  "sales_customer_success",
  "leadership",
  "grc_policy",
] as const;

const ROLE_LABEL: Record<(typeof ROLES)[number], string> = {
  general_professional: "General Professional",
  software_engineer: "Software Engineer",
  ai_ml_practitioner: "AI / ML Practitioner",
  data_analyst: "Data Analyst",
  cloud_devops: "Cloud / DevOps",
  cybersecurity: "Cybersecurity",
  product_manager: "Product Manager",
  sales_customer_success: "Sales / Customer Success",
  leadership: "Leadership",
  grc_policy: "GRC / Policy",
};
```

- [ ] **Step 2: Relabel the mode UI**

In `InterviewFields`, change the first label text from `Interview mode` to `Practice mode` and replace the mode options with:

```tsx
          <option value={MODE_LEARN}>Learn</option>
          <option value={MODE_DRILL}>Drill</option>
          <option value={MODE_ROLEPLAY}>Roleplay</option>
          <option value={MODE_INTERVIEW}>Interview</option>
```

- [ ] **Step 3: Keep the target role enabled only for Interview**

Change the second field label from `Target role` to `Interview target`.

Keep this disabled condition:

```tsx
          disabled={value.mode !== MODE_INTERVIEW}
```

The Drill and Roleplay modes use the selected persona's domain, so they do not need extra setup fields.

- [ ] **Step 4: Relabel the live settings section**

In `InterviewPanelLive`, change:

```tsx
      <h4>Interview mode</h4>
```

to:

```tsx
      <h4>Practice mode</h4>
```

- [ ] **Step 5: Run web typecheck**

Run:

```bash
npm --prefix web run typecheck
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/app/InterviewPanel.tsx
git commit -m "feat: add practice mode picker options"
```

## Task 4: Add Persona Presets and Avatar Mappings

**Files:**
- Modify: `web/app/personaPresets.ts`
- Modify: `web/app/avatarConfig.ts`
- Test: `npm --prefix web run typecheck`

- [ ] **Step 1: Replace the preset list**

In `web/app/personaPresets.ts`, set:

```ts
export const DEFAULT_PRESET_ID = "voice-fluency-coach";
```

Replace `PERSONA_PRESETS` with:

```ts
export const PERSONA_PRESETS: PersonaPreset[] = [
  {
    id: DEFAULT_PRESET_ID,
    label: "Voice Fluency Coach",
    blurb: "General spoken fluency and clear explanations.",
    persona: DEFAULT_PERSONA,
    mood: "happy",
  },
  {
    id: "cybersecurity-trainer",
    label: "Cybersecurity Trainer",
    blurb: "Threats, controls, IR, identity, appsec, and risk.",
    persona: {
      role_text:
        "You are a cybersecurity trainer: a seasoned security practitioner who coaches " +
        "learners by voice across threats, defenses, network and application security, " +
        "identity, cryptography, incident response, and risk. Pull the learner into " +
        "explaining tradeoffs aloud and keep guidance at a defensive training level.",
      display_name: "Cybersecurity Trainer",
      difficulty: "intermediate",
      verbosity: "balanced",
      correction: "gentle",
      voice_id: "af_bella",
    },
    mood: "neutral",
  },
  {
    id: "ai-ml-coach",
    label: "AI/ML Coach",
    blurb: "GenAI, model behavior, evals, data, and deployment.",
    persona: {
      role_text:
        "You are an AI and machine-learning coach. Help the learner practice explaining " +
        "GenAI systems, model behavior, evaluation, data quality, safety, and deployment " +
        "tradeoffs in clear practitioner language.",
      display_name: "AI/ML Coach",
      difficulty: "intermediate",
      verbosity: "balanced",
      correction: "moderate",
      voice_id: "af_nicole",
    },
    mood: "happy",
  },
  {
    id: "data-analyst-coach",
    label: "Data Analyst Coach",
    blurb: "Metrics, dashboards, SQL-style reasoning, and insight.",
    persona: {
      role_text:
        "You are a data analyst coach. Help the learner practice explaining metrics, " +
        "dashboard tradeoffs, SQL-style reasoning, experiments, stakeholder questions, " +
        "and business insight from data.",
      display_name: "Data Analyst Coach",
      difficulty: "intermediate",
      verbosity: "balanced",
      correction: "moderate",
      voice_id: "bf_alice",
    },
    mood: "neutral",
  },
  {
    id: "software-engineering-mentor",
    label: "Software Engineering Mentor",
    blurb: "Debugging, architecture, testing, and production tradeoffs.",
    persona: {
      role_text:
        "You are a software engineering mentor. Coach the learner on debugging, system " +
        "design, code quality, tests, architecture tradeoffs, production ownership, and " +
        "clear technical communication.",
      display_name: "Software Engineering Mentor",
      difficulty: "intermediate",
      verbosity: "balanced",
      correction: "moderate",
      voice_id: "am_michael",
    },
    mood: "neutral",
  },
  {
    id: "cloud-devops-coach",
    label: "Cloud/DevOps Coach",
    blurb: "Containers, CI/CD, reliability, incidents, and observability.",
    persona: {
      role_text:
        "You are a cloud and DevOps coach. Help the learner practice explaining " +
        "containers, CI/CD, reliability, observability, incident response, cloud cost, " +
        "and operational tradeoffs.",
      display_name: "Cloud/DevOps Coach",
      difficulty: "intermediate",
      verbosity: "balanced",
      correction: "moderate",
      voice_id: "bm_george",
    },
    mood: "neutral",
  },
  {
    id: "product-manager-coach",
    label: "Product Manager Coach",
    blurb: "Product sense, discovery, prioritization, and metrics.",
    persona: {
      role_text:
        "You are a product management coach. Help the learner practice product sense, " +
        "user discovery, prioritization, roadmap tradeoffs, stakeholder alignment, and " +
        "metric-driven reasoning aloud.",
      display_name: "Product Manager Coach",
      difficulty: "intermediate",
      verbosity: "balanced",
      correction: "gentle",
      voice_id: "af_sarah",
    },
    mood: "happy",
  },
  {
    id: "sales-roleplay-partner",
    label: "Sales Roleplay Partner",
    blurb: "Discovery, qualification, objections, and closing.",
    persona: {
      role_text:
        "You are a sales roleplay partner. Help the learner practice discovery, " +
        "qualification, objection handling, value framing, closing, and concise " +
        "follow-up in realistic spoken sales conversations.",
      display_name: "Sales Roleplay Partner",
      difficulty: "intermediate",
      verbosity: "terse",
      correction: "moderate",
      voice_id: "am_puck",
    },
    mood: "neutral",
  },
  {
    id: "customer-success-coach",
    label: "Customer Success Coach",
    blurb: "Onboarding, renewals, adoption, and difficult calls.",
    persona: {
      role_text:
        "You are a customer success coach. Help the learner practice onboarding, " +
        "renewals, adoption conversations, executive updates, escalations, and difficult " +
        "customer calls with calm, outcome-focused language.",
      display_name: "Customer Success Coach",
      difficulty: "intermediate",
      verbosity: "balanced",
      correction: "gentle",
      voice_id: "bf_emma",
    },
    mood: "happy",
  },
  {
    id: "leadership-coach",
    label: "Leadership Coach",
    blurb: "Executive communication, conflict, feedback, and delegation.",
    persona: {
      role_text:
        "You are a leadership communication coach. Help the learner practice concise " +
        "executive updates, feedback, conflict conversations, delegation, decision " +
        "framing, and team accountability.",
      display_name: "Leadership Coach",
      difficulty: "intermediate",
      verbosity: "balanced",
      correction: "gentle",
      voice_id: "am_adam",
    },
    mood: "neutral",
  },
  {
    id: "healthcare-communication-coach",
    label: "Healthcare Communication Coach",
    blurb: "Patient-safe explanations, empathy, and care conversations.",
    persona: {
      role_text:
        "You are a healthcare communication coach. Help the learner practice patient-safe " +
        "explanations, empathy, consent, handoffs, and questions for clinicians. Do not " +
        "diagnose, recommend treatment, or replace a clinician; redirect urgent symptoms " +
        "to professional care.",
      display_name: "Healthcare Communication Coach",
      difficulty: "intermediate",
      verbosity: "balanced",
      correction: "gentle",
      voice_id: "af_heart",
    },
    mood: "love",
  },
  {
    id: "finance-business-coach",
    label: "Finance & Business Coach",
    blurb: "Markets, statements, unit economics, and tradeoffs.",
    persona: {
      role_text:
        "You are a finance and business concepts coach. Help the learner practice " +
        "explaining markets, financial statements, budgeting, unit economics, strategy, " +
        "and business tradeoffs. Keep guidance educational, not personal investment, " +
        "tax, or legal advice.",
      display_name: "Finance & Business Coach",
      difficulty: "intermediate",
      verbosity: "balanced",
      correction: "gentle",
      voice_id: "bm_daniel",
    },
    mood: "neutral",
  },
  {
    id: "grc-policy-advisor",
    label: "GRC / Policy Advisor",
    blurb: "Risk, controls, audit evidence, policy, and vendor risk.",
    persona: {
      role_text:
        "You are a governance, risk, compliance, and policy advisor. Help the learner " +
        "practice explaining controls, audit evidence, risk treatment, policy tradeoffs, " +
        "vendor risk, and business alignment without presenting legal advice.",
      display_name: "GRC / Policy Advisor",
      difficulty: "intermediate",
      verbosity: "detailed",
      correction: "gentle",
      voice_id: "bf_emma",
    },
    mood: "neutral",
  },
  {
    id: "climate-energy-coach",
    label: "Climate & Energy Coach",
    blurb: "Sustainability, energy transition, policy, and tradeoffs.",
    persona: {
      role_text:
        "You are a climate and energy coach. Help the learner practice explaining " +
        "sustainability, energy transition, grid constraints, policy tradeoffs, climate " +
        "risk, and practical business decisions.",
      display_name: "Climate & Energy Coach",
      difficulty: "intermediate",
      verbosity: "balanced",
      correction: "gentle",
      voice_id: "af_kore",
    },
    mood: "neutral",
  },
  {
    id: "language-conversation-partner",
    label: "Language Conversation Partner",
    blurb: "Conversational fluency, phrasing, pronunciation, and confidence.",
    persona: {
      role_text:
        "You are a language conversation partner. Help the learner practice everyday and " +
        "professional conversation, clearer phrasing, pronunciation awareness, and " +
        "confidence. Correct gently and keep the conversation moving.",
      display_name: "Language Conversation Partner",
      difficulty: "beginner",
      verbosity: "terse",
      correction: "gentle",
      voice_id: "af_sarah",
    },
    mood: "happy",
  },
];
```

- [ ] **Step 2: Sync avatar mappings**

In `web/app/avatarConfig.ts`, replace `PERSONA_AVATARS` with:

```ts
export const PERSONA_AVATARS: Record<string, AvatarSpec> = {
  "Voice Fluency Coach": { glb: DEFAULT_AVATAR.glb, mood: "happy", body: "F" },
  "Cybersecurity Trainer": DEFAULT_AVATAR,
  "AI/ML Coach": { glb: DEFAULT_AVATAR.glb, mood: "happy", body: "F" },
  "Data Analyst Coach": { glb: DEFAULT_AVATAR.glb, mood: "neutral", body: "F" },
  "Software Engineering Mentor": { glb: DEFAULT_AVATAR.glb, mood: "neutral", body: "M" },
  "Cloud/DevOps Coach": { glb: DEFAULT_AVATAR.glb, mood: "neutral", body: "M" },
  "Product Manager Coach": { glb: DEFAULT_AVATAR.glb, mood: "happy", body: "F" },
  "Sales Roleplay Partner": { glb: DEFAULT_AVATAR.glb, mood: "neutral", body: "M" },
  "Customer Success Coach": { glb: DEFAULT_AVATAR.glb, mood: "happy", body: "F" },
  "Leadership Coach": { glb: DEFAULT_AVATAR.glb, mood: "neutral", body: "M" },
  "Healthcare Communication Coach": { glb: DEFAULT_AVATAR.glb, mood: "love", body: "F" },
  "Finance & Business Coach": { glb: DEFAULT_AVATAR.glb, mood: "neutral", body: "M" },
  "GRC / Policy Advisor": { glb: DEFAULT_AVATAR.glb, mood: "neutral", body: "F" },
  "Climate & Energy Coach": { glb: DEFAULT_AVATAR.glb, mood: "neutral", body: "F" },
  "Language Conversation Partner": { glb: DEFAULT_AVATAR.glb, mood: "happy", body: "F" },
};
```

- [ ] **Step 3: Run web typecheck**

Run:

```bash
npm --prefix web run typecheck
```

Expected: PASS. This catches bad mood/body values and persona object shape drift.

- [ ] **Step 4: Commit**

```bash
git add web/app/personaPresets.ts web/app/avatarConfig.ts
git commit -m "feat: add voice practice persona presets"
```

## Task 5: Documentation and Final Verification

**Files:**
- Modify: `CHANGELOG.md`
- Optionally modify: `README.md` only if the current first paragraph still implies cybersecurity is the default
- Test: full focused verification commands

- [ ] **Step 1: Add a changelog entry**

In `CHANGELOG.md`, under the current `[unreleased]` section, add these bullets:

```markdown
- Default persona changed to Voice Fluency Coach, with Cybersecurity Trainer
  moved into the preset library.
- Added broad voice-practice persona presets across AI/ML, data, software,
  cloud/DevOps, product, sales, customer success, leadership, healthcare
  communication, finance/business, GRC/policy, climate/energy, and language
  conversation practice.
- Added Drill and Roleplay practice modes alongside Learn and Interview.
```

- [ ] **Step 2: Check README wording**

Run:

```bash
rg -n "Cybersecurity Trainer|cybersecurity-first|default persona|persona" README.md
```

Expected: if README says Cybersecurity Trainer is the default, replace that sentence with:

```markdown
The default persona is a general Voice Fluency Coach, and the setup screen includes
domain presets such as Cybersecurity Trainer, AI/ML Coach, Data Analyst Coach, and
others.
```

If README has no default-persona claim, leave it unchanged.

- [ ] **Step 3: Run focused verification**

Run:

```bash
python3 agent/persona.py
python3 agent/interview.py
python3 tests/test_endpointing.py
npm --prefix web run typecheck
```

Expected: all pass.

- [ ] **Step 4: Inspect the final diff**

Run:

```bash
git diff --stat
git diff -- agent/persona.py agent/interview.py agent/main.py agent/endpointing.py tests/test_endpointing.py web/app/PersonaPanel.tsx web/app/InterviewPanel.tsx web/app/personaPresets.ts web/app/avatarConfig.ts CHANGELOG.md README.md
```

Expected: changes are limited to default persona, mode prompts, preset data, avatar mappings, docs, and endpointing tests.

- [ ] **Step 5: Commit**

```bash
git add agent/persona.py agent/interview.py agent/main.py agent/endpointing.py tests/test_endpointing.py web/app/PersonaPanel.tsx web/app/InterviewPanel.tsx web/app/personaPresets.ts web/app/avatarConfig.ts CHANGELOG.md README.md
git commit -m "docs: document voice practice personas"
```

If `README.md` is unchanged, omit it from `git add`.

## Self-Review

Spec coverage:

- Default persona change: Task 1.
- Cybersecurity moved into preset list: Task 4.
- More persona variety across trending domains: Task 4.
- Voice-only modes Learn, Drill, Roleplay, Interview: Tasks 2 and 3.
- Existing RPCs preserved: Tasks 2 and 3 update constants and validation only.
- Frozen prompt path preserved: Task 2 composes through `render_prompt`.
- No new agent classes: no task creates one.
- No written-output modes: mode prompts are voice-practice only.
- Tests and docs: Task 5.

Intentional simplifications:

- No preset category UI. The wrapped preset picker is enough for the first pass.
- No preset integrity test imports `personaPresets.ts`, because that file depends on the React persona panel. TypeScript typecheck is the smaller reliable check here.
- No new avatar assets. All presets reuse the default GLB.
