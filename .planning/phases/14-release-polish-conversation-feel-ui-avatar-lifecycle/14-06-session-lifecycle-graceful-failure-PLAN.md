---
phase: 14
plan: 14-06
slug: session-lifecycle-graceful-failure
depends_on: []
status: ready
files_modified:
  - agent/transcript_gate.py        # NEW — pure garbled-finalize predicate
  - agent/main.py                   # session.reset RPC; REL-02 reprompt hook
  - web/app/transcriptExport.ts     # NEW — pure txt/md formatter + download
  - web/app/VoiceRoom.tsx           # End/New/Reset handlers; config reset; mic precheck
  - web/app/TalkingScreen.tsx       # thread onNew/onReset/onEnd + resetMarker to drawer/transcript
  - web/app/SettingsDrawer.tsx      # New/Reset/End actions + Export buttons
  - web/app/Transcript.tsx          # capture per-segment timestamp; reset marker
  - tests/test_transcript_gate.py   # NEW — garbled predicate truth table
requirements: [SESS-01, SESS-02, SESS-03, SESS-04, REL-01, REL-02]
---

# Plan 14-06 — Session Lifecycle + Graceful Failure

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.
> Read `14-00-STATE-AND-SEQUENCING.md` first. This plan has **three livekit/agent
> API-uncertainty hooks** (user-turn gate, history reset, transcript timestamp field).
> Each has an explicit introspection step before the wiring — confirm against the
> installed versions, exactly like the repo's existing `VM-introspection` comments.

**Goal:** Ship the carried v1.0 polish — new/reset/end session with a full ephemeral
teardown audit, client-side transcript export, an actionable mic-denied prompt, and an
empty/garbled-finalize reprompt instead of the agent answering noise.

**Architecture:**
- **End (SESS-03)** = `setToken(null)` (unmounts `<LiveKitRoom>` → room teardown → the
  agent *job* ends, so its closure state `current_persona/mode/role/model`, `session_kb`,
  history, and the per-connection STT decoder cache all die) **plus** resetting the held
  `SessionConfig` to defaults (clears KB files + model + persona + avatarOn in the UI).
- **New (SESS-01)** = End-style teardown then immediately `start()` a fresh room/token,
  keeping the user's setup choices.
- **Reset (SESS-02)** = same room; a `session.reset` RPC clears the agent's chat
  history + re-primes instructions, and the transcript view clears via a reset marker.
- **Export (SESS-04)** = `useTranscriptions()` → pure `transcriptExport.ts` formatter →
  client `Blob` download (txt/md), no server round-trip.
- **REL-01** = a pre-connect `getUserMedia` probe in `start()` surfaces an actionable
  message on `NotAllowedError` instead of a silent dead room.
- **REL-02** = a pure `is_garbled(text)` predicate gates the user turn: garbled →
  reprompt + suppress the LLM reply.

**Tech Stack:** `livekit-agents` (Agent turn hooks, ChatContext), `@livekit/
components-react` (`useTranscriptions`), Python pure predicate, browser `Blob` download.

**Current state (vs PRD §2):** Confirmed unbuilt. `onLeave` only `setToken(null)`
(no config reset); `SettingsDrawer` has only the two-step Leave; `Transcript` stores no
timestamps; `NemoSTT._emit_final` emits empty text unfiltered; `MicPicker` degrades the
*picker* gracefully but there's no *session* mic-denied prompt.

## Global Constraints
Inherit `14-00 §5`. Plan-specific: transcript export is **client-side only** (no
server round-trip — PERF-03 local-first); the End teardown audit must leave **no**
ephemeral residue across sessions; every fallible boundary (mic denial, empty STT,
LiveKit disconnect) has explicit handling.

---

## Task 1: Pure garbled-finalize predicate (`agent/transcript_gate.py`) + test

**Files:**
- Create: `agent/transcript_gate.py`
- Test: `tests/test_transcript_gate.py`

**Interfaces:**
- Produces: `is_garbled(text: str) -> bool` — True for empty/whitespace or
  sub-threshold noise that should not become an LLM turn.

- [ ] **Step 1: Write the failing test**

Create `tests/test_transcript_gate.py`:
```python
"""REL-02 garbled-finalize predicate. Pure stdlib, no LiveKit."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

import transcript_gate  # noqa: E402


def test_empty_and_whitespace_are_garbled():
    assert transcript_gate.is_garbled("")
    assert transcript_gate.is_garbled("   \n\t ")


def test_single_noise_token_is_garbled():
    assert transcript_gate.is_garbled("uh")
    assert transcript_gate.is_garbled("...")


def test_real_utterance_is_not_garbled():
    assert not transcript_gate.is_garbled("what is a SOC")
    assert not transcript_gate.is_garbled("explain ATT&CK")


if __name__ == "__main__":
    test_empty_and_whitespace_are_garbled()
    test_single_noise_token_is_garbled()
    test_real_utterance_is_not_garbled()
    print("ok: transcript gate truth table")
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python3 tests/test_transcript_gate.py`
Expected: `ModuleNotFoundError: No module named 'transcript_gate'`.

- [ ] **Step 3: Write the minimal implementation**

Create `agent/transcript_gate.py`:
```python
"""REL-02: decide whether a finalized STT transcript is too empty/garbled to answer.

Pure module (no LiveKit) so the truth table runs in the sandbox. The agent reprompts
("didn't catch that") instead of generating a reply to noise/silence.
"""
from __future__ import annotations

# A real spoken turn carries at least a couple of word characters. Below this, treat
# the finalize as noise (open-mic blip, cough, single backchannel) and reprompt.
MIN_MEANINGFUL_CHARS = 3


def is_garbled(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < MIN_MEANINGFUL_CHARS:
        return True
    # No alphanumeric content (pure punctuation / dots) is noise.
    return not any(ch.isalnum() for ch in stripped)
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `python3 tests/test_transcript_gate.py`
Expected: `ok: transcript gate truth table`

- [ ] **Step 5: Commit**

```bash
git add agent/transcript_gate.py tests/test_transcript_gate.py
git commit -m "feat(14-06): pure garbled-finalize predicate + truth table (REL-02)"
```

---

## Task 2: Wire the REL-02 reprompt into the agent turn

**Files:**
- Modify: `agent/main.py` (the agent class / user-turn hook)

**Interfaces:**
- Consumes: `transcript_gate.is_garbled`, `session.generate_reply`.
- Produces: garbled user turn → spoken reprompt + suppressed LLM answer.

- [ ] **Step 1: Confirm the user-turn hook + suppression API (introspection)**

livekit-agents exposes a per-turn hook to inspect/veto the user message before the LLM
runs. Confirm the exact names on the installed version:
```bash
python -c "import inspect, livekit.agents as a; print([n for n in dir(a) if 'Stop' in n or 'Response' in n]); from livekit.agents import Agent; print([m for m in dir(Agent) if 'turn' in m.lower()])"
```
Expected: a `StopResponse` (or equivalent) exception and an
`on_user_turn_completed(self, turn_ctx, new_message)` override point on `Agent`. Note
the exact import + signature (call them `<STOP_RESPONSE>` / `<USER_TURN_HOOK>`).

- [ ] **Step 2: Add the gate to the agent class**

`agent/main.py` builds `HistoryWindowAgent(instructions=…)`. Add the hook to that class
(or wherever the `Agent` subclass is defined). Import the predicate (`import
transcript_gate`) and the suppression symbol confirmed in Step 1, then:
```python
    async def on_user_turn_completed(self, turn_ctx, new_message):
        # REL-02: never answer noise/silence. On a garbled finalize, reprompt and
        # cancel the would-be reply so the agent doesn't hallucinate a response.
        text = new_message.text_content or ""
        if transcript_gate.is_garbled(text):
            await self.session.generate_reply(
                instructions="(internal) You didn't catch that. In one short spoken "
                "sentence, say you didn't catch it and ask them to repeat."
            )
            raise StopResponse()  # use the symbol confirmed in Step 1
        return await super().on_user_turn_completed(turn_ctx, new_message)
```
(If the installed API differs, adapt to the confirmed hook/suppression names — the
predicate call and the reprompt instruction are the load-bearing parts.)

- [ ] **Step 3: Byte-compile**

Run: `python3 -m py_compile agent/main.py && python3 tests/test_transcript_gate.py`
Expected: clean compile; `ok:` line.

- [ ] **Step 4: Commit**

```bash
git add agent/main.py
git commit -m "feat(14-06): reprompt on garbled finalize instead of answering noise (REL-02)"
```

---

## Task 3: Reset RPC — clear context, same session (SESS-02)

**Files:**
- Modify: `agent/main.py` (new `handle_session_reset`; register; history clear)

**Interfaces:**
- Produces: RPC `"session.reset"`, payload `{}` (no body needed), returns
  `"applied"`/`"error"`; clears chat history, keeps persona/mode/model/KB.

- [ ] **Step 1: Confirm the history-clear API (introspection)**

```bash
python -c "from livekit.agents import Agent, ChatContext; print([m for m in dir(Agent) if 'chat' in m.lower()]); print([m for m in dir(ChatContext) if not m.startswith('_')])"
```
Expected: `Agent.update_chat_ctx(chat_ctx)` + an empty-context constructor (e.g.
`ChatContext.empty()`). Also inspect `HistoryWindowAgent` in `agent/main.py` for any
internal history buffer it keeps beyond `chat_ctx` (clear that too). Note the exact
calls.

- [ ] **Step 2: Add the reset handler**

In `agent/main.py`, near the other RPC handlers:
```python
    async def handle_session_reset(data):
        # SESS-02: clear conversation context WITHOUT tearing the room down. Persona,
        # mode, model, and the KB brief are kept (those are session config, not
        # context). Re-prime the system prompt for the current epoch.
        try:
            await agent.update_chat_ctx(ChatContext.empty())  # confirm in Step 1
            await agent.update_instructions(compose_instructions())
        except Exception as exc:  # boundary: never wedge the live room on reset
            logger.warning("session.reset failed: %s", exc)
            return "error"
        return "applied"
```
Import `ChatContext` (the confirmed symbol) at top. Register:
```python
    ctx.room.local_participant.register_rpc_method("session.reset", handle_session_reset)
```

- [ ] **Step 3: Byte-compile + commit**

```bash
python3 -m py_compile agent/main.py
git add agent/main.py
git commit -m "feat(14-06): session.reset RPC clears context without teardown (SESS-02)"
```

---

## Task 4: Transcript export — pure formatter + download (SESS-04)

**Files:**
- Create: `web/app/transcriptExport.ts`
- Modify: `web/app/Transcript.tsx` (capture a per-segment finalize timestamp)
- Modify: `web/app/SettingsDrawer.tsx` (Export txt / Export md buttons)

**Interfaces:**
- Produces: `formatTranscript(entries, format) -> string` and
  `downloadTranscript(text, filename)`; `TranscriptEntry = {speaker, text, at}`.

- [ ] **Step 1: Confirm the segment timestamp field (introspection)**

The export needs a timestamp per finalized line. Confirm what
`useTranscriptions()` segments expose on `@livekit/components-react@2.9.21`:
```bash
cd web && grep -rn "firstReceivedTime\|receivedAt\|timestamp" node_modules/@livekit/components-react/dist/ | head
```
Expected: a receive-time field on `streamInfo` (e.g. `timestamp` /
`firstReceivedTime`). If none is stable, fall back to capturing `Date.now()` in
`Transcript` when a segment first becomes final (Step 2 does this regardless, so export
never depends on an unstable field).

- [ ] **Step 2: Capture a finalize timestamp in `Transcript.tsx`**

In `web/app/Transcript.tsx`, add a `useRef<Map<string, number>>(new Map())` keyed by
`segment.streamInfo.id`; in the render/effect over segments, when a segment is final
and not yet in the map, record `Date.now()`. (This is display-invisible; it only
backs export with a reliable wall-clock.)

- [ ] **Step 3: Create the pure formatter**

```typescript
// SESS-04: client-side transcript export (txt/md). Pure — no room, no network.
export type TranscriptEntry = { speaker: "You" | "Agent"; text: string; at: number };

function stamp(at: number): string {
  // Local HH:MM:SS — no date (a single session never spans days).
  return new Date(at).toLocaleTimeString([], { hour12: false });
}

export function formatTranscript(entries: TranscriptEntry[], format: "txt" | "md"): string {
  if (format === "md") {
    const head = "# Adept session transcript\n\n";
    return head + entries.map((e) => `- **${e.speaker}** _(${stamp(e.at)})_: ${e.text}`).join("\n") + "\n";
  }
  return entries.map((e) => `[${stamp(e.at)}] ${e.speaker}: ${e.text}`).join("\n") + "\n";
}

export function downloadTranscript(text: string, filename: string): void {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
  } finally {
    URL.revokeObjectURL(url); // boundary: always release the object URL
  }
}
```

- [ ] **Step 4: Add Export buttons to the drawer**

In `web/app/SettingsDrawer.tsx` (inside `<LiveKitRoom>`, so hooks are valid), call
`useTranscriptions()`, build `TranscriptEntry[]` (map `identity.startsWith("user-")` →
`"You"` else `"Agent"`; `text`; `at` from the finalize-timestamp map exposed by
`Transcript` — or recompute here from the same segments), and add two buttons:
```tsx
<button type="button" className="btn-ghost" onClick={() =>
  downloadTranscript(formatTranscript(entries, "txt"), "adept-transcript.txt")}>
  Export .txt
</button>
<button type="button" className="btn-ghost" onClick={() =>
  downloadTranscript(formatTranscript(entries, "md"), "adept-transcript.md")}>
  Export .md
</button>
```
(If threading the timestamp map across components is awkward, capture `at` directly in
the drawer with the same first-seen-final `Map<id, Date.now()>` ref — both components
read the same `useTranscriptions()` stream.)

- [ ] **Step 5: Typecheck + build + manual**

Run: `cd web && npx tsc --noEmit && npm run build`
Manual: hold a short conversation, Export .txt and .md. Expected: both download with
`You`/`Agent` labels + timestamps, no network request (check the Network panel).

- [ ] **Step 6: Commit**

```bash
cd .. && git add web/app/transcriptExport.ts web/app/Transcript.tsx web/app/SettingsDrawer.tsx
git commit -m "feat(14-06): client-side transcript export txt/md with speaker + timestamps (SESS-04)"
```

---

## Task 5: New / End lifecycle + teardown audit (SESS-01, SESS-03)

**Files:**
- Modify: `web/app/VoiceRoom.tsx` (End/New/Reset handlers; config reset)
- Modify: `web/app/TalkingScreen.tsx` (thread `onNew`/`onReset`/`onEnd` + `resetMarker`
  through to `SettingsDrawer` and `Transcript` — it owns both today)
- Modify: `web/app/SettingsDrawer.tsx` (New / Reset actions; relabel Leave → End)

> Note: `TalkingScreen` currently renders `<SettingsDrawer open onClose onLeave>` and
> `<Transcript/>`. Extend its prop type with `onNew`, `onReset`, `onEnd`, and
> `resetMarker`, pass `onEnd` to the topbar "Leave" button (relabel to "End") and to
> the drawer, and pass `resetMarker` to `<Transcript resetAfter={resetMarker}/>`.

**Interfaces:**
- Consumes: `start()`, `setToken`, `setSessionConfig`, `DEFAULT_SESSION_CONFIG`.
- Produces: `onEnd`, `onNew`, `onReset` props threaded to the drawer.

- [ ] **Step 1: Add the lifecycle handlers in `VoiceRoom`**

```tsx
  // SESS-03 End: disconnect + clear ALL held ephemeral state. Unmounting <LiveKitRoom>
  // ends the agent job (its closure state + per-connection STT cache die); resetting
  // the config clears KB files, model, persona, avatarOn in the UI.
  function endSession() {
    setToken(null);
    setSessionConfig(DEFAULT_SESSION_CONFIG);
    setError(null);
  }
  // SESS-01 New: fresh room/token, keep the user's setup choices.
  function newSession() {
    setToken(null);
    // Re-Start on the next tick so <LiveKitRoom> fully unmounts first.
    setTimeout(() => { void start(); }, 0);
  }
  // SESS-02 Reset is a same-room RPC fired from the drawer (Task 3) + transcript clear.
```
Pass `onEnd={endSession}` and `onNew={newSession}` down to `<TalkingScreen>` →
`<SettingsDrawer>` (replace the current single `onLeave`). Keep `onLeave`/the topbar
"Leave" button mapped to `endSession`.

- [ ] **Step 2: Surface New / Reset / End in the drawer**

In `web/app/SettingsDrawer.tsx`, add a "Session" section with three actions:
- **New session** → `onNew` (confirm copy: "Start a fresh session? The current
  conversation clears.").
- **Reset** → fire `session.reset` RPC (the existing `performRpc` pattern) + a
  `onReset` callback that bumps a transcript reset marker (Step 3); copy: "Clear the
  conversation but keep your setup?".
- **End session** → the existing two-step destructive confirm, now calling `onEnd`
  (relabel "Leave session" → "End session"; keep the destructive styling + copy
  "End this conversation and return to setup? Your transcript will clear.").

- [ ] **Step 3: Transcript reset marker (so Reset visibly clears the view)**

Add a `resetMarker` number state in `VoiceRoom`, incremented by `onReset`, passed to
`<Transcript resetAfter={resetMarker}/>` (and the finalize-timestamp map). `Transcript`
hides segments whose first-final timestamp predates the latest reset. (Same-room
transcriptions accumulate in the hook; the marker is how the UI "forgets" them.)

- [ ] **Step 4: Teardown audit — confirm no residue**

Verify each ephemeral item is cleared on End (record in the plan):
| Item | Cleared by |
|---|---|
| KB brief | agent job ends on room unmount (closure `session_kb` dies) |
| Conversation history | agent job ends (or `session.reset` for SESS-02) |
| Transcript (UI) | `<LiveKitRoom>` unmount drops `useTranscriptions` state |
| Model choice | `setSessionConfig(DEFAULT_SESSION_CONFIG)` |
| Persona / KB files / avatarOn | `setSessionConfig(DEFAULT_SESSION_CONFIG)` |
| STT decoder cache | per-WS-connection in `stt/server.py`; closes with the job |
| Avatar GLB | `AvatarStage` unmounts (dynamic import torn down) on End |

- [ ] **Step 5: Typecheck + build + manual + commit**

Run: `cd web && npx tsc --noEmit && npm run build`
Manual: End returns to setup with defaults (re-open Customize → persona is the
default, KB empty, model Fast, Avatar off). New gives a clean room keeping your choices.
Reset clears the transcript + the agent forgets prior turns, same room.
```bash
cd .. && git add web/app/VoiceRoom.tsx web/app/SettingsDrawer.tsx web/app/Transcript.tsx
git commit -m "feat(14-06): new/reset/end session lifecycle + ephemeral teardown audit (SESS-01/02/03)"
```

---

## Task 6: Mic-permission-denied prompt (REL-01)

**Files:**
- Modify: `web/app/VoiceRoom.tsx` (pre-connect mic probe in `start()`)

**Interfaces:**
- Produces: an actionable error state on `NotAllowedError` instead of a silent room.

- [ ] **Step 1: Probe mic permission before connecting**

In `start()`, before the token fetch, add a guarded probe:
```tsx
    // REL-01: fail loudly + actionably if the mic is blocked, instead of connecting to
    // a dead room. The probe also primes the permission so LiveKit capture succeeds.
    try {
      const probe = await navigator.mediaDevices.getUserMedia({ audio: true });
      probe.getTracks().forEach((t) => t.stop());
    } catch (err) {
      setConnecting(false);
      setError(
        "Microphone access is blocked. Click the mic/camera icon in your browser's " +
        "address bar, choose Allow, then press Start again."
      );
      return;
    }
```
(The existing `error` render slot in `SetupScreen` shows it; ensure the mic-denied copy
is shown verbatim — not collapsed into the generic `CONNECT_ERROR` — by setting a
distinct error string and rendering `error` directly when present.)

- [ ] **Step 2: Typecheck + build + manual**

Run: `cd web && npx tsc --noEmit && npm run build`
Manual: deny mic permission in the browser, press Start. Expected: the actionable
prompt appears (not a hang, not a silent dead room); granting + retry connects.

- [ ] **Step 3: Commit**

```bash
cd .. && git add web/app/VoiceRoom.tsx
git commit -m "feat(14-06): actionable mic-permission-denied prompt at Start (REL-01)"
```

## Verification
**Self-checkable:**
- `python3 tests/test_transcript_gate.py` → `ok:`.
- `python3 -m py_compile agent/main.py agent/transcript_gate.py` → clean.
- `cd web && npx tsc --noEmit && npm run build` → green.

**Manual (UAT, also re-run in 14-09):**
- New / Reset / End all work; End leaves no ephemeral residue (audit table).
- Transcript exports txt + md with speaker labels + timestamps, no network request.
- Mic-denied shows the actionable prompt; garbled/empty speech makes the agent reprompt
  ("didn't catch that") instead of answering noise.

## Artifacts this plan produces
- **NEW** `agent/transcript_gate.py` (+ test) — garbled predicate.
- **NEW** `web/app/transcriptExport.ts` — txt/md formatter + download.
- **MODIFIED** `agent/main.py` — `session.reset` RPC + REL-02 reprompt hook.
- **MODIFIED** `web/app/VoiceRoom.tsx`, `SettingsDrawer.tsx`, `Transcript.tsx` —
  new/reset/end lifecycle, export buttons, mic-denied prompt, reset marker.
