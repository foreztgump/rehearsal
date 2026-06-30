# Local Saved Personas Design

Date: 2026-06-30

## Goal

Let users save and reload their own persona setups without changing the agent,
the prompt contract, or the local-first privacy posture.

Users can already create a custom persona by editing the existing Display name,
Role / instructions, difficulty, verbosity, correction, and voice fields. This
slice adds browser-local save/load/delete around that same `Persona` snapshot.

## Decisions

- Persist saved personas in browser `localStorage` only.
- Reuse the existing `Persona` shape exactly.
- Keep `persona.update` unchanged; loading a saved persona only fills the form.
- Save current form values under a user-provided name.
- Allow loading and deleting saved personas from setup and in-session settings.
- Ignore malformed stored records rather than migrating them.

## User Experience

The persona editor gains a compact saved-persona control:

- A name input for saving the current persona.
- A saved-persona select list.
- `Save`, `Load`, and `Delete` actions.

On the setup screen, loading a persona fills the editable persona fields before
the user connects. On the settings drawer, loading a persona fills the same
fields; the user still clicks the existing `Apply` button to send
`persona.update`.

## Data Model

Use one versioned key:

```ts
const SAVED_PERSONAS_KEY = "adept.savedPersonas.v1";
```

Stored value:

```ts
type SavedPersona = {
  id: string;
  name: string;
  persona: Persona;
  createdAt: string;
  updatedAt: string;
};
```

`id` can be generated with `crypto.randomUUID()` when available, falling back to
`Date.now().toString(36)`. Dates are ISO strings for display/debugging only.

## Validation

Before rendering saved entries:

- Stored root must be an array.
- `name` must be a non-empty string.
- `persona` must contain string values for the existing six persona fields.
- `difficulty`, `verbosity`, `correction`, and `voice_id` must remain valid by
  the existing client-side option lists.

Invalid entries are dropped from the in-memory list. If `localStorage` is blocked
or throws, the control behaves as empty and shows no fatal error.

## Architecture

Keep the change in the web app:

- `web/app/savedPersonas.ts`: pure storage helpers for parse, save, load, delete,
  and validation. No React and no module-load `localStorage` access.
- `web/app/PersonaPanel.tsx`: export the client option lists, render the
  saved-persona control near the existing fields, and reuse it in live settings.
- `web/app/SetupScreen.tsx`: render the saved-persona control beside the preset
  picker for pre-connect setup.

No agent code changes. No database. No network calls. No changes to avatar,
model, KB, mode, or transcript state.

## Testing

Smallest useful checks:

- Add a tiny `web/app/savedPersonas.ts` self-check for parsing and dropping bad
  records.
- Run `npm --prefix web run typecheck`.
- Manually verify save, load, delete, and blocked/empty storage behavior in the
  setup screen and settings drawer.

## Out of Scope

- Cross-browser or cross-device sync.
- Server-side saved personas.
- Accounts or a persona marketplace.
- JSON import/export.
- Saved KB collections or transcript persistence.
- Prompt templates beyond the existing persona fields.
