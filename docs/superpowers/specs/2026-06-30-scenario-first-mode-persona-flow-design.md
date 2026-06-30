# Scenario-First Mode and Persona Flow Design

## Context

The current setup screen asks the user to choose `Practice mode` visibly, but keeps
the persona controls under `Customize`. `Interview target` is visible beside the
mode picker even though it is disabled unless the mode is `Interview`. Live
Settings then re-create persona, mode, and model panels with default state instead
of the setup-applied state.

The result is a confusing mental model: users are trying to choose one practice
scenario, but the UI splits that decision across mode, target, persona preset,
saved persona, and custom persona fields.

## Goals

- Make the first setup decision read as: "What do you want to practice?"
- Make persona/coach choice a primary part of setup, not an advanced option.
- Only show interview-specific target controls when the selected mode is Interview.
- Prevent contradictory combinations where possible, such as Sales persona with
  Cybersecurity interview target.
- Ensure live Settings reflects the running session before any Apply click.
- Keep all persistence browser-local and reuse the existing persona/mode/model RPCs.

## Non-Goals

- No server-side saved sessions.
- No new persona or interview database.
- No multi-step wizard unless a single-screen layout proves too dense.
- No automatic cloud sync or account model.

## Proposed Flow

### 1. Practice Scenario

Replace the raw `Practice mode` select with a first-class scenario picker:

- `General Chat` maps to `learn`.
- `Drill` maps to `drill`.
- `Roleplay` maps to `roleplay`.
- `Mock Interview` maps to `interview`.

Use compact cards or a segmented control with short labels. This is the first
visible choice because it changes the structure of the conversation.

### 2. Guide / Persona

Move persona preset, saved persona load/save, and custom persona fields out of the
collapsed `Customize` section. The user should see who they are about to talk to
before starting.

The default remains `Voice Fluency Coach`. Presets and saved personas fill the same
editable persona form. Custom editing stays available without requiring a separate
mode.

### 3. Interview Target

Render `Interview target` only when the scenario is `Mock Interview`. In all other
modes, omit it instead of showing a disabled field.

When a user chooses `Mock Interview`, default the target from the selected persona
when there is an obvious match:

- Software Engineering Mentor -> Software Engineer
- AI/ML Coach -> AI / ML Practitioner
- Cybersecurity Trainer -> Cybersecurity
- Product Manager Coach -> Product Manager
- GRC / Policy Advisor -> GRC / Policy

If there is no match, keep `General Professional`.

### 4. Advanced Setup

Keep response model, microphone, avatar, knowledge base, voice, correction style,
difficulty, and verbosity as setup controls. The layout can still be one screen,
but the visual hierarchy should separate core scenario choices from tuning knobs.

### 5. Live Settings

Live Settings must receive the current session config from `VoiceRoom` and seed the
persona, mode, and model panels from it. Applying a live change should also update
the shell's current config so reopening Settings shows the running state.

This fixes the current default-state drift where a user can start with a custom
setup, open Settings, and accidentally apply defaults over the running session.

## Data Flow

- `VoiceRoom` continues to own `sessionConfig`.
- `SetupScreen` edits `sessionConfig` before connect.
- `ApplySetupOnConnect` applies the same config once after the agent joins.
- `SettingsDrawer` receives current config and update callbacks.
- Live persona/mode/model panels become controlled by `SettingsDrawer` or
  `VoiceRoom`, rather than owning disconnected default state.
- Existing RPC payloads stay unchanged:
  - `persona.update`
  - `mode.update`
  - `model.update`

## Error Handling

- Setup remains startable with defaults.
- Saved persona save/load/delete failures keep the visible saved list intact.
- Live Apply failures leave the local form state unchanged and show the existing
  inline error status.
- If setup auto-apply fails after connect, the existing note remains and the user
  can re-apply from Settings.

## Testing

- Unit/self-check coverage for any new mode/persona matching helper.
- Typecheck the web app.
- Build the web app.
- Browser smoke, when available:
  - Non-interview scenarios do not show `Interview target`.
  - Mock Interview shows `Interview target`.
  - Choosing a matching persona seeds the matching interview target.
  - Starting with custom setup, then opening Settings, shows the same running
    persona/mode/model values.
  - Loading a saved persona in live Settings does not affect the agent until Apply.

## Scope for First Implementation

Do the smallest useful slice:

1. Make live Settings reflect and update current session config.
2. Hide `Interview target` outside Mock Interview.
3. Move persona preset and saved persona controls into the primary setup flow.
4. Add simple persona-to-interview-target matching for obvious preset pairs.

Session presets, account sync, and a full wizard can wait.
