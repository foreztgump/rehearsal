---
phase: 14
plan: 14-05
slug: persona-avatar-presets
depends_on: [14-02]
status: ready
files_modified:
  - web/app/personaPresets.ts   # NEW — pure preset table
  - web/app/avatarConfig.ts      # register preset display_names → per-preset mood (reuse GLB)
  - web/app/PersonaPresetPicker.tsx # NEW — the setup chooser
  - web/app/SetupScreen.tsx       # mount the picker (pre-fills the editable persona)
requirements: [AVTR-13]
---

# Plan 14-05 — Persona + Avatar Presets

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:executing-plans`. Read
> `14-00-STATE-AND-SEQUENCING.md` first. Frontend-only; **reuses the existing
> `persona.update` apply path** (no new agent RPC) and the existing
> `avatarForPersona()` mood seam. No web test runner — verify with `tsc --noEmit` +
> `npm run build` + manual.

**Goal:** Let the user pick a persona preset on the setup screen that pre-fills the
(still live-editable) persona fields, voice, and avatar mood — seeded to the existing
domains — with every preset reusing the default GLB.

**Architecture:** A preset is a frontend `Persona` snapshot + a mood. A pure
`personaPresets.ts` holds the table; selecting one calls the existing
`onChange({...config, persona})` so it flows through the unchanged
`persona.update` RPC on Start (voice applied via `session.tts.update_options`, fields
shown in the "Customize" disclosure and editable). Avatar mood follows automatically:
`AvatarStage` already resolves mood through `avatarForPersona(displayName)` — we
register each preset's `display_name` in `PERSONA_AVATARS` pointing at the **default
GLB** with a per-preset mood.

**Tech Stack:** React 19, pure TS modules (`personaPresets.ts`, `avatarConfig.ts`).

**Current state (vs PRD §2):** No preset chooser exists. `Persona`
(`{role_text, display_name, difficulty, verbosity, correction, voice_id}`),
`DEFAULT_PERSONA`, `VOICE_IDS`, and `PERSONA_AVATARS`/`avatarForPersona` all exist and
are reused as-is. Interview ROLES (SOC/SecEng/GRC) are a separate *mode* concept; these
presets are Learn-mode personas whose `role_text` frames the domain.

## Global Constraints
Inherit `14-00 §5`. Plan-specific: presets are **frontend-only** (no `persona.update`
payload-shape change, no server field); all presets **reuse the default GLB**
(`/avatars/cyber-trainer.glb`); preset `voice_id` values MUST be in `VOICE_IDS`; preset
`mood` values MUST be valid TalkingHead moods (`neutral|happy|angry|sad|fear|disgust|
love|sleep`); the CTA is never disabled — defaults still pre-fill everything.

---

## Task 1: Pure preset table (`web/app/personaPresets.ts`)

**Files:**
- Create: `web/app/personaPresets.ts`

**Interfaces:**
- Consumes: `Persona`, `DEFAULT_PERSONA` from `./PersonaPanel`.
- Produces: `PersonaPreset` type; `PERSONA_PRESETS: PersonaPreset[]`;
  `DEFAULT_PRESET_ID`. Each preset: `{ id, label, blurb, persona: Persona, mood }`.

- [ ] **Step 1: Create the table**

```typescript
// Persona presets (AVTR-13). A preset is a ready-made Persona snapshot + an avatar
// mood; selecting one pre-fills the still-editable persona fields and voice. All
// presets reuse the default GLB (mood varies per preset — see avatarConfig). Pure
// data, no React — same bundle discipline as avatarConfig.ts.
import { DEFAULT_PERSONA, type Persona } from "./PersonaPanel";

export type PersonaPreset = {
  id: string;
  label: string;
  blurb: string;
  persona: Persona;
  mood: "neutral" | "happy" | "angry" | "sad" | "fear" | "disgust" | "love" | "sleep";
};

export const DEFAULT_PRESET_ID = "cyber-trainer";

export const PERSONA_PRESETS: PersonaPreset[] = [
  {
    id: DEFAULT_PRESET_ID,
    label: "Cybersecurity Trainer",
    blurb: "General cyber coach — the default.",
    persona: DEFAULT_PERSONA, // role_text "" → agent ROLE_PREAMBLE; voice af_bella
    mood: "neutral",
  },
  {
    id: "soc-analyst-coach",
    label: "SOC Analyst Coach",
    blurb: "Alert triage, SIEM, MITRE ATT&CK, incident escalation.",
    persona: {
      role_text:
        "You are a SOC analyst mentor. Coach the learner on alert triage, SIEM and " +
        "log analysis, the MITRE ATT&CK framework, phishing and malware " +
        "investigation, and incident escalation — practitioner-level, spoken aloud.",
      display_name: "SOC Analyst Coach",
      difficulty: "intermediate",
      verbosity: "balanced",
      correction: "moderate",
      voice_id: "am_michael",
    },
    mood: "neutral",
  },
  {
    id: "security-engineer-coach",
    label: "Security Engineer Coach",
    blurb: "Secure architecture, IAM, vuln mgmt, cloud hardening, automation.",
    persona: {
      role_text:
        "You are a security engineering mentor. Coach the learner on secure " +
        "architecture and network segmentation, identity and access management, " +
        "vulnerability management, cloud and infrastructure hardening, and security " +
        "automation — practitioner-level, spoken aloud.",
      display_name: "Security Engineer Coach",
      difficulty: "intermediate",
      verbosity: "balanced",
      correction: "moderate",
      voice_id: "bm_george",
    },
    mood: "neutral",
  },
  {
    id: "grc-advisor",
    label: "GRC Advisor",
    blurb: "Risk, NIST/ISO 27001, audit evidence, policy, vendor risk.",
    persona: {
      role_text:
        "You are a governance, risk, and compliance advisor. Coach the learner on " +
        "risk assessment and treatment, control frameworks such as NIST and " +
        "ISO 27001, audit and compliance evidence, policy development, and " +
        "third-party risk — practitioner-level, spoken aloud.",
      display_name: "GRC Advisor",
      difficulty: "intermediate",
      verbosity: "detailed",
      correction: "gentle",
      voice_id: "bf_emma",
    },
    mood: "neutral",
  },
  {
    id: "domain-expert",
    label: "Domain Expert",
    blurb: "General expert sounding board for any topic you set.",
    persona: {
      role_text:
        "You are a knowledgeable domain expert and Socratic sounding board. Help the " +
        "learner practice explaining and reasoning about whatever domain they raise, " +
        "spoken aloud, with precise terminology.",
      display_name: "Domain Expert",
      difficulty: "expert",
      verbosity: "balanced",
      correction: "gentle",
      voice_id: "af_nicole",
    },
    mood: "happy",
  },
];

const PRESET_BY_ID = new Map(PERSONA_PRESETS.map((p) => [p.id, p]));
export function presetById(id: string): PersonaPreset | undefined {
  return PRESET_BY_ID.get(id);
}
```

- [ ] **Step 2: Sanity-check voices are valid**

Run:
```bash
cd web && grep -n "voice_id:" app/personaPresets.ts
grep -n "VOICE_IDS" app/PersonaPanel.tsx
```
Expected: every preset `voice_id` (`af_bella`, `am_michael`, `bm_george`, `bf_emma`,
`af_nicole`) appears in `PersonaPanel`'s `VOICE_IDS` list (and the agent's
`persona.VOICE_IDS`). If not, swap to a listed voice.

- [ ] **Step 3: Typecheck + commit**

```bash
cd web && npx tsc --noEmit
cd .. && git add web/app/personaPresets.ts
git commit -m "feat(14-05): pure persona-preset table (reuses default GLB, distinct voices)"
```

---

## Task 2: Register preset moods in `avatarConfig.ts` (reuse the GLB)

**Files:**
- Modify: `web/app/avatarConfig.ts` (extend `PERSONA_AVATARS`)

**Interfaces:**
- Produces: `avatarForPersona(displayName)` returns each preset's mood over the default
  GLB, so the avatar's resting expression follows the chosen preset with no new asset.

- [ ] **Step 1: Add a per-preset entry pointing at the default GLB**

In `web/app/avatarConfig.ts`, extend `PERSONA_AVATARS` (keep `body: "F"` since the GLB
is reused; only `mood` varies):
```typescript
export const PERSONA_AVATARS: Record<string, AvatarSpec> = {
  "Cybersecurity Trainer": DEFAULT_AVATAR,
  "SOC Analyst Coach": { glb: DEFAULT_AVATAR.glb, mood: "neutral", body: "F" },
  "Security Engineer Coach": { glb: DEFAULT_AVATAR.glb, mood: "neutral", body: "F" },
  "GRC Advisor": { glb: DEFAULT_AVATAR.glb, mood: "neutral", body: "F" },
  "Domain Expert": { glb: DEFAULT_AVATAR.glb, mood: "happy", body: "F" },
};
```
(These `display_name` keys must match the preset `display_name`s exactly; an unmapped
name still falls back to `DEFAULT_AVATAR` — never breaks.)

- [ ] **Step 2: Typecheck + commit**

```bash
cd web && npx tsc --noEmit
cd .. && git add web/app/avatarConfig.ts
git commit -m "feat(14-05): map preset display_names to per-preset mood over the default GLB"
```

---

## Task 3: The setup chooser (`PersonaPresetPicker`) + wire into `SetupScreen`

**Files:**
- Create: `web/app/PersonaPresetPicker.tsx`
- Modify: `web/app/SetupScreen.tsx` (render the picker; selecting pre-fills the persona)

**Interfaces:**
- Consumes: `PERSONA_PRESETS`, the current `config.persona`, `onChange`.
- Produces: a preset selection that calls `onChange({ ...config, persona: preset.persona })`.

- [ ] **Step 1: Create the picker**

```tsx
"use client";

import { PERSONA_PRESETS, type PersonaPreset } from "./personaPresets";

// Setup-screen persona chooser. Selecting a preset pre-fills the (still editable)
// persona fields below it; it never disables the CTA. Presentational — the parent
// owns state via onSelect.
export default function PersonaPresetPicker({
  activeDisplayName,
  onSelect,
}: {
  activeDisplayName: string;
  onSelect: (preset: PersonaPreset) => void;
}) {
  return (
    <div className="field full">
      <label className="field-label">Persona preset</label>
      <div className="seg-wrap" role="radiogroup" aria-label="Persona preset" style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
        {PERSONA_PRESETS.map((preset) => {
          const active = preset.persona.display_name === activeDisplayName;
          return (
            <button
              key={preset.id}
              type="button"
              role="radio"
              aria-checked={active}
              title={preset.blurb}
              className="btn-ghost"
              // Active state via the theme accent (there is no .btn-ghost.on rule in
              // globals.css; an inline accent border is the smallest correct indicator).
              style={active ? { borderColor: "var(--accent)", color: "var(--text)" } : undefined}
              onClick={() => onSelect(preset)}
            >
              {preset.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Render it in `SetupScreen` above the persona fields**

In `web/app/SetupScreen.tsx`, import the picker and place it inside the "Customize"
disclosure, directly above the `<PersonaFields …/>` grid, so a chosen preset pre-fills
the editable fields:
```tsx
import PersonaPresetPicker from "./PersonaPresetPicker";
// …inside the disclosure, before <PersonaFields>:
<PersonaPresetPicker
  activeDisplayName={config.persona.display_name}
  onSelect={(preset) => onChange({ ...config, persona: preset.persona })}
/>
```
(Optionally update the disclosure summary label to show the active preset name — the
existing summary already shows `config.persona.display_name`.)

- [ ] **Step 3: Typecheck + build**

Run: `cd web && npx tsc --noEmit && npm run build`
Expected: green.

- [ ] **Step 4: Commit**

```bash
cd .. && git add web/app/PersonaPresetPicker.tsx web/app/SetupScreen.tsx
git commit -m "feat(14-05): persona preset chooser on setup (pre-fills editable persona)"
```

---

## Task 4: Verify apply path + manual sign-off

**Files:** none (verification).

- [ ] **Step 1: Confirm the apply path is unchanged**

The chosen preset becomes `config.persona`; on Start, `ApplySetupOnConnect` sends
`persona.update` with it (skipping only when it equals `DEFAULT_PERSONA`). Confirm:
```bash
cd web && grep -n "persona.update\|sameAsDefault" app/ApplySetupOnConnect.tsx
```
Expected: `persona.update` fires for any non-default preset; the agent validates the
knobs + `voice_id` and applies voice via `session.tts.update_options`. No code change.

- [ ] **Step 2: Manual — pick → edit → start → talk**

`npm run dev`. Open Customize, pick **SOC Analyst Coach**. Expected: the persona fields
+ voice pre-fill to the preset and remain editable (change one field — it sticks).
Start a session: the agent adopts the SOC persona and the distinct voice; with Avatar
ON, the avatar loads the default GLB with the preset's mood. Pick **Domain Expert**
before Start instead → distinct voice + `happy` mood. Default (Cyber Trainer) starts
with no `persona.update` (matches `DEFAULT_PERSONA`).

- [ ] **Step 3: Record sign-off + commit**

Append a verification record (presets pre-fill + stay editable + voice/mood applied +
default GLB reused). Note the optional follow-up: the same picker could be added to the
in-room `SettingsDrawer` for live mid-session preset switching (PRD §10 — deferred,
YAGNI for the release).
```bash
cd .. && git add .planning/phases/14-release-polish-conversation-feel-ui-avatar-lifecycle/14-05-persona-avatar-presets-PLAN.md
git commit -m "docs(14-05): sign persona-preset verification"
```

## Verification
- `cd web && npx tsc --noEmit && npm run build` green.
- Selecting a preset pre-fills the editable persona + voice; mood follows via
  `avatarForPersona(display_name)`; all presets reuse `/avatars/cyber-trainer.glb`.
- Non-default preset → `persona.update` applies persona + voice live on Start; default
  preset → no-op (already the agent default).

## Artifacts this plan produces
- **NEW** `web/app/personaPresets.ts` — pure preset table.
- **NEW** `web/app/PersonaPresetPicker.tsx` — setup chooser.
- **MODIFIED** `web/app/avatarConfig.ts` — preset moods over the default GLB.
- **MODIFIED** `web/app/SetupScreen.tsx` — picker mounted above the editable persona.
