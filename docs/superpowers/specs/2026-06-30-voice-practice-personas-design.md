# Voice Practice Personas Design

Date: 2026-06-30

## Goal

Expand Adept from a cybersecurity-first trainer into a broader voice-practice
tool with more default personas and a small set of voice-only agent modes.

The user should be able to choose a domain persona, pick a practice pattern, and
start speaking without configuring prompt text by hand.

## Decisions

- The default persona becomes **Voice Fluency Coach**.
- **Cybersecurity Trainer** moves into the preset list.
- Personas remain editable `Persona` snapshots.
- Agent modes remain voice-practice modes, not written-output workflows.
- Keep the existing `persona.update` and `mode.update` RPCs.
- Preserve the frozen persona + KB prompt path and low-latency voice loop.
- Do not add new agent classes unless the current mode helper cannot carry the
  behavior cleanly.

## Prompting Principles

Research points to compact, explicit prompts for voice agents:

- Set role, purpose, scope, and behavior in the persona text.
- Keep shared voice rules outside each preset: short replies, no markdown, no
  code blocks unless asked, one focused question at a time.
- Use positive behavioral instructions over long backstories.
- Use mode prompts for conversation pattern, not domain identity.
- Add simple boundaries for regulated domains:
  - Healthcare communication practice, not diagnosis or treatment.
  - Finance and business education, not personal investment instructions.
  - Legal/policy practice, not legal advice.
- Avoid hidden reasoning or chain-of-thought language in prompts.
- Keep prompts short enough to protect TTFT on local models.

## Product Model

### Personas

Personas are selectable domain identities. Selecting a preset fills the existing
editable fields:

- `role_text`
- `display_name`
- `difficulty`
- `verbosity`
- `correction`
- `voice_id`

Presets remain plain client data. The agent receives the same full persona
snapshot it already accepts.

### Agent Modes

Modes change how the voice conversation runs:

- **Learn**: teach briefly, ask one follow-up, correct terminology.
- **Drill**: rapid-fire questions with short feedback after each answer.
- **Roleplay**: simulate a stakeholder, customer, peer, or interviewer.
- **Interview**: structured interview practice with critique and a strong answer.

All modes are voice practice only. They should not generate study guides, written
plans, documents, or long reports.

## Persona Coverage

Add these presets:

- **Voice Fluency Coach**: general spoken explanation practice and default.
- **Cybersecurity Trainer**: broad security practitioner coaching.
- **AI/ML Coach**: GenAI, model behavior, evaluation, applied AI.
- **Data Analyst Coach**: metrics, dashboards, SQL-style reasoning, insight.
- **Software Engineering Mentor**: architecture, debugging, tradeoffs.
- **Cloud/DevOps Coach**: containers, CI/CD, reliability, observability.
- **Product Manager Coach**: product sense, prioritization, roadmaps.
- **Sales Roleplay Partner**: discovery, objection handling, closing.
- **Customer Success Coach**: onboarding, renewals, difficult customer calls.
- **Leadership Coach**: executive communication, conflict, delegation.
- **Healthcare Communication Coach**: patient-safe communication practice.
- **Finance & Business Coach**: markets and business concepts.
- **GRC / Policy Advisor**: risk, compliance, controls, audit evidence.
- **Climate & Energy Coach**: sustainability, energy transition, policy tradeoffs.
- **Language Conversation Partner**: conversational fluency and pronunciation.

No category UI is required in the first pass. A wrapped preset picker is enough
unless the existing setup screen becomes crowded.

## Architecture

### Server

`agent/persona.py` owns the default persona and render contract.

Changes:

- Update `ROLE_PREAMBLE`, `DEFAULT_PERSONA`, and `EXPECTED_DEFAULT` to the new
  Voice Fluency Coach.
- Keep `DIFFICULTY`, `VERBOSITY`, `CORRECTION`, `SPOKEN_STYLE_FOOTER`,
  `KB_SLOT`, and `KB_CITE_NUDGE` unchanged unless a test proves a conflict.
- Keep the prompt join order unchanged.

`agent/interview.py` or the existing mode module owns mode prompts.

Changes:

- Add `drill` and `roleplay` modes if the current structure supports them.
- Broaden interview roles beyond cybersecurity without changing the RPC shape.
- Keep mode prompts compact and voice-first.

### Web

`web/app/PersonaPanel.tsx` mirrors the server default.

Changes:

- Update `DEFAULT_PERSONA` to Voice Fluency Coach.

`web/app/personaPresets.ts` owns the preset list.

Changes:

- Add the preset set above.
- Keep each `role_text` compact.
- Use existing voice IDs only.

`web/app/avatarConfig.ts` maps preset display names to the default avatar.

Changes:

- Add each new preset display name to `PERSONA_AVATARS`.
- Reuse the current GLB and vary only mood/body where useful.

`web/app/InterviewPanel.tsx` may need copy and option updates if the mode list
is expanded there.

## Data Flow

1. User chooses a persona preset on the setup screen.
2. The preset fills the existing editable persona fields.
3. On connect, `ApplySetupOnConnect` sends the persona snapshot through
   `persona.update` only when it differs from the default.
4. User chooses a mode.
5. The web app sends `{mode, role_key}` through `mode.update`.
6. The agent composes persona + KB + mode into instructions exactly once per
   user-initiated change.
7. Normal voice turn handling continues through the existing LiveKit session.

## Error Handling

- Reject malformed persona snapshots exactly as today.
- Reject unknown voice IDs and knob values exactly as today.
- Unknown modes should fall back to Learn or return `"error"` without poisoning
  the current session state.
- Avatar mapping must fall back to `DEFAULT_AVATAR` for any unmapped name.
- Regulated-domain personas must phrase boundaries as practice constraints, not
  heavy refusal scripts.

## Testing

Use the smallest checks that catch real drift:

- Run `python3 agent/persona.py`.
- Add or update a tiny preset integrity check if practical:
  - unique preset IDs
  - valid voice IDs
  - default preset ID exists
  - avatar mappings exist for preset display names
- Run `npm --prefix web run typecheck`.

If mode logic changes server-side, add a small pure-function check for accepted
modes and fallback behavior.

## Out of Scope

- Persona library persistence.
- Category filters or search.
- New avatar assets.
- Separate agent classes.
- Written-output modes.
- Cloud prompt services or cloud inference.
