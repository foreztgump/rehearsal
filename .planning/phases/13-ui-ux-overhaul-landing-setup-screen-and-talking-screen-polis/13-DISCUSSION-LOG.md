# Phase 13: UI/UX Overhaul — Landing/Setup Screen & Talking Screen Polish - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-26
**Phase:** 13-ui-ux-overhaul-landing-setup-screen-and-talking-screen-polis
**Areas discussed:** Setup screen layout (user confirmed full spec; kept discussion intentionally light)

---

## Gray Areas Presented

The user was offered 5 gray areas: Setup→connect handoff, Visual design language,
Setup screen layout, Talking screen + transcript, Navigation & session controls.

**User's choice:** "Setup screen layout, nothing really. I just need to make
sure you have all the spec that I want."

**Notes:** The user's intent was confirmation that the full vision is captured,
not a deep multi-area design negotiation. The spec was reflected back verbatim
(landing-before-connect, auto-scroll transcript, simple/elegant/clean/animated/
organized, easy navigation, polished, creative) and confirmed.

---

## Setup Screen Layout

| Option | Description | Selected |
|--------|-------------|----------|
| Single elegant panel | One organized screen, all config grouped, prominent Start; fastest path | ✓ |
| Guided multi-step wizard | Step-by-step persona → KB → model/mic → avatar → review | |
| Card dashboard | Grid of config cards opened in any order, then Start | |

**User's choice:** Single elegant panel
**Notes:** Fastest load → talking; sections expandable to customize.

## Defaults

| Option | Description | Selected |
|--------|-------------|----------|
| Sensible defaults, one click to start | Default persona/Fast/default mic/avatar-off preselected; Start enabled immediately | ✓ |
| Require a few key choices first | Gate Start until persona + mic confirmed | |

**User's choice:** Sensible defaults, one click to start
**Notes:** First-time user can connect immediately and customize later.

---

## the agent's Discretion

The user deferred execution craft to the agent (D-03 in CONTEXT.md):
- Concrete styling approach (refine inline dark theme vs. introduce CSS modules /
  framework) and animation mechanism (CSS transitions vs. motion library).
- Talking-screen arrangement of agent-state, transcript, avatar, controls.
- Reversible setup ↔ talking navigation pattern.

## Deferred Ideas

- Session lifecycle (new/reset/end), transcript export, mic-denial prompt,
  garbled-STT reprompt → Phase 14 (SESS-01..04, REL-01/02).
- Final latency tuning (PERF-04) → Phase 14.
