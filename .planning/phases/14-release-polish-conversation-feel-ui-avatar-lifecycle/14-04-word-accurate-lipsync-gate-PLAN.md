---
phase: 14
plan: 14-04
slug: word-accurate-lipsync-gate
depends_on: [14-03]
status: ready
files_modified:
  - agent/captioned_gate.py     # NEW — pure request-body + words gating
  - agent/captioned_tts.py      # gate on avatar_enabled (default OFF)
  - agent/main.py               # avatar.update RPC → set_avatar_enabled
  - web/app/ApplyAvatarMode.tsx # NEW — sends avatar.update (initial + on toggle)
  - web/app/VoiceRoom.tsx       # mount ApplyAvatarMode inside <LiveKitRoom>
  - tests/test_captioned_gate.py # NEW — gate truth table
requirements: [AVTR-12]
---

# Plan 14-04 — Word-Accurate Lip-Sync: the Avatar-ON Gate

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.
> Read `14-00-STATE-AND-SEQUENCING.md` first. **This is the inverse of the PRD's
> framing.** The captioned-TTS path is already wired and *always on*; the work here is
> to **gate it OFF for voice-only** so Avatar-OFF emits no `lk.avatar.*` traffic and
> reuses identical Kokoro audio. This plan owns the `avatar.update` seam (14-00 §4).

**Goal:** Word-accurate Path-B lip-sync runs **only when Avatar is ON**; with Avatar
OFF, the agent requests no word timestamps and publishes no lip-sync schedule (the
voice-only auditable invariant), while the synthesized audio is the same Kokoro
inference. Path-A energy remains the per-utterance fallback when timestamps are absent.

**Architecture:** `CaptionedTTS` gains an `_avatar_enabled` flag (default **False** —
matches `SessionConfig.avatarOn=false`). A pure `agent/captioned_gate.py` builds the
request body (`return_timestamps = avatar_enabled`) and extracts the word list — both
sandbox-testable. `_run` uses them and gates the data-channel publish on the flag. A
new `avatar.update` RPC (`{on: bool}`) flips the flag; the frontend
`ApplyAvatarMode` component sends it after connect and whenever the Voice/Avatar
toggle changes. Endpoint reconciliation: Avatar-OFF stays on `/dev/captioned_speech`
with `return_timestamps=False` (the audio is the same inference per PRD §D — the only
things captioned-TTS *adds* are the timestamp request and the publish, both now
gated), so the auditable difference is exactly "no `lk.avatar.lipsync` frames + no
timestamp work" — which is what 14-09 verifies.

**Tech Stack:** Python `livekit-agents` TTS plugin, httpx, Kokoro-FastAPI
`/dev/captioned_speech`; React/livekit-client RPC.

**Current state (vs PRD §2/§D):** `agent/captioned_tts.py` exists and is the session
TTS (`main.py:233-236`), `attach_room`'d (`386-387`); it **always** requests
timestamps and **always** publishes `lk.avatar.lipsync` — so today voice-only is NOT
isolated. The Path-B scheduler + Path-A fallback already live in `AvatarStage.tsx`.

## Global Constraints
Inherit `14-00 §5`. Plan-specific: **Voice-only isolation is the auditable invariant**
— Avatar OFF ⇒ zero `lk.avatar.*` data-channel publishes and identical audio. Avatar
ON *may* touch the server pipeline (captioned TTS) — document this as the intentional,
avatar-on-only retirement of the Phase-12 frontend-only gate. Zero added server VRAM.

---

## Task 1: Pure gate module (`agent/captioned_gate.py`) + test

**Files:**
- Create: `agent/captioned_gate.py`
- Test: `tests/test_captioned_gate.py`

**Interfaces:**
- Produces:
  - `captioned_request_body(text, voice, speed, avatar_enabled) -> dict` —
    `return_timestamps` mirrors `avatar_enabled`.
  - `lipsync_words(timestamps) -> list[dict]` — `[{"w","s","e"}]` from Kokoro's
    `[{word,start_time,end_time}]`, dropping empty words.
- Consumes: nothing (pure stdlib — no httpx/livekit import, so the test runs in the sandbox).

- [ ] **Step 1: Write the failing test**

Create `tests/test_captioned_gate.py`:

```python
"""Avatar-ON gate truth table for captioned TTS (AVTR-12). Pure stdlib, no LiveKit."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

import captioned_gate  # noqa: E402


def test_avatar_on_requests_timestamps():
    body = captioned_gate.captioned_request_body("hi", "af_bella", 1.0, avatar_enabled=True)
    assert body["return_timestamps"] is True
    assert body["input"] == "hi" and body["voice"] == "af_bella"


def test_avatar_off_suppresses_timestamps():
    body = captioned_gate.captioned_request_body("hi", "af_bella", 1.0, avatar_enabled=False)
    assert body["return_timestamps"] is False


def test_words_drop_empty_and_map_fields():
    raw = [
        {"word": "hello", "start_time": 0.0, "end_time": 0.4},
        {"word": "", "start_time": 0.4, "end_time": 0.5},
    ]
    words = captioned_gate.lipsync_words(raw)
    assert words == [{"w": "hello", "s": 0.0, "e": 0.4}]


if __name__ == "__main__":
    test_avatar_on_requests_timestamps()
    test_avatar_off_suppresses_timestamps()
    test_words_drop_empty_and_map_fields()
    print("ok: captioned gate truth table")
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python3 tests/test_captioned_gate.py`
Expected: `ModuleNotFoundError: No module named 'captioned_gate'`.

- [ ] **Step 3: Write the minimal implementation**

Create `agent/captioned_gate.py`:

```python
"""Pure gate logic for captioned TTS (AVTR-12) — no httpx/livekit import.

Kept separate from captioned_tts.py so the gate decision (request timestamps? build a
publishable word list?) is unit-testable in the GPU-less sandbox, mirroring how
agent/endpointing.py isolates the mode→endpointing decision.
"""
from __future__ import annotations

KOKORO_MODEL = "kokoro"
RESPONSE_FORMAT = "wav"


def captioned_request_body(
    text: str, voice: str, speed: float, *, avatar_enabled: bool
) -> dict:
    """Kokoro /dev/captioned_speech body. Avatar OFF ⇒ no timestamps requested (the
    audio inference is identical either way; only this flag + the publish differ)."""
    return {
        "model": KOKORO_MODEL,
        "input": text,
        "voice": voice,
        "response_format": RESPONSE_FORMAT,
        "speed": speed,
        "stream": False,
        "return_timestamps": avatar_enabled,
    }


def lipsync_words(timestamps: list[dict]) -> list[dict]:
    """Sentence-relative [{w,s,e}] for the data channel; drop empty words."""
    return [
        {"w": t.get("word", ""), "s": t.get("start_time", 0.0), "e": t.get("end_time", 0.0)}
        for t in timestamps
        if t.get("word")
    ]
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `python3 tests/test_captioned_gate.py`
Expected: `ok: captioned gate truth table`

- [ ] **Step 5: Commit**

```bash
git add agent/captioned_gate.py tests/test_captioned_gate.py
git commit -m "feat(14-04): pure captioned-TTS avatar-on gate + truth table"
```

---

## Task 2: Gate `CaptionedTTS` on `_avatar_enabled` (default OFF)

**Files:**
- Modify: `agent/captioned_tts.py` (`__init__`; new `set_avatar_enabled`;
  `_CaptionedStream.__init__` snapshot; `_run` body + publish gate)

**Interfaces:**
- Consumes: `captioned_gate.captioned_request_body`, `captioned_gate.lipsync_words`.
- Produces: `CaptionedTTS.set_avatar_enabled(on: bool)`; OFF ⇒ no publish, no timestamps.

- [ ] **Step 1: Add the flag + setter**

In `agent/captioned_tts.py`, import the gate at top:
```python
import captioned_gate
```
In `CaptionedTTS.__init__`, after `self._seq = 0`, add (default OFF = voice-only):
```python
        # Avatar-ON gate (AVTR-12). Default OFF so voice-only is isolated out of the
        # box: no word-timestamp request, no lk.avatar.lipsync publish. Flipped by the
        # avatar.update RPC (agent/main.py) — same runtime-mutation pattern as voice.
        self._avatar_enabled = False
```
Add the setter next to `update_options`:
```python
    def set_avatar_enabled(self, on: bool) -> None:
        """Enable/disable captioned word-timestamp publishing for avatar lip-sync."""
        self._avatar_enabled = bool(on)
```

- [ ] **Step 2: Snapshot the flag per utterance in the stream**

In `_CaptionedStream.__init__`, after `self._opts = replace(tts._opts)`, capture the
flag so a mid-utterance toggle doesn't split one clip's behaviour:
```python
        self._avatar_enabled = tts._avatar_enabled
```

- [ ] **Step 3: Build the body via the gate + gate the publish in `_run`**

In `_CaptionedStream._run`, replace the inline `body = {…}` with the pure builder:
```python
        body = captioned_gate.captioned_request_body(
            self.input_text, self._opts.voice, self._opts.speed,
            avatar_enabled=self._avatar_enabled,
        )
```
Keep the existing POST to `/dev/captioned_speech`, `raise_for_status`, base64 decode,
`output_emitter.initialize/push/flush` exactly as-is (audio path unchanged). Then
replace the inline word-list comprehension + unconditional publish with the gated form:
```python
        # Voice-only isolation (AVTR-12): publish the word schedule ONLY when the
        # avatar is on. OFF ⇒ no return_timestamps was requested, words is empty, and
        # we never touch the lk.avatar.lipsync channel.
        if self._avatar_enabled:
            words = captioned_gate.lipsync_words(data.get("timestamps", []))
            if words:
                await self._tts._publish_schedule(request_id, words)
```

- [ ] **Step 4: Byte-compile + re-run the gate test**

Run:
```bash
python3 -m py_compile agent/captioned_tts.py agent/captioned_gate.py
python3 tests/test_captioned_gate.py
```
Expected: clean compile; `ok:` line.

- [ ] **Step 5: Commit**

```bash
git add agent/captioned_tts.py
git commit -m "feat(14-04): gate captioned TTS on avatar_enabled (default OFF = voice-only isolated)"
```

---

## Task 3: `avatar.update` RPC → `set_avatar_enabled`

**Files:**
- Modify: `agent/main.py` (new `handle_avatar_update`; register alongside the other RPCs)

**Interfaces:**
- Produces: RPC method `"avatar.update"`, payload `{"on": bool}`, returns
  `"applied"`/`"error"` (mirrors `model.update`).

- [ ] **Step 1: Add the handler**

In `agent/main.py`, near `handle_model_update`, add:
```python
    async def handle_avatar_update(data):
        # avatar.update is the UNTRUSTED RPC boundary — validate the type before
        # touching the live TTS. Mirrors handle_model_update's shape.
        try:
            snapshot = json.loads(data.payload)
        except json.JSONDecodeError as exc:
            logger.warning("avatar.update rejected: malformed payload (%s)", exc)
            return "error"
        on = snapshot.get("on")
        if not isinstance(on, bool):
            logger.warning("avatar.update rejected: 'on' not a bool: %r", on)
            return "error"
        if isinstance(session.tts, CaptionedTTS):
            session.tts.set_avatar_enabled(on)
        return "applied"
```

- [ ] **Step 2: Register the RPC**

Where the other `register_rpc_method` calls live (~495-571), add:
```python
    ctx.room.local_participant.register_rpc_method("avatar.update", handle_avatar_update)
```

- [ ] **Step 3: Byte-compile**

Run: `python3 -m py_compile agent/main.py`
Expected: no output (success).

- [ ] **Step 4: Commit**

```bash
git add agent/main.py
git commit -m "feat(14-04): avatar.update RPC flips captioned-TTS gate live"
```

---

## Task 4: Frontend — send `avatar.update` (initial + on toggle)

**Files:**
- Create: `web/app/ApplyAvatarMode.tsx`
- Modify: `web/app/VoiceRoom.tsx` (mount it inside `<LiveKitRoom>`)

**Interfaces:**
- Consumes: `SessionConfig.avatarOn` (already in `VoiceRoom`), the agent identity from
  `useVoiceAssistant()`, `room.localParticipant.performRpc` (the pattern in
  `ApplySetupOnConnect.tsx`).
- Produces: an `avatar.update` RPC on connect and on every avatar-toggle change.

- [ ] **Step 1: Create `ApplyAvatarMode.tsx`**

Model it on `ApplySetupOnConnect.tsx` (same agent-readiness gate + `performRpc` shape):
```tsx
"use client";

import { useEffect, useRef } from "react";
import { useRoomContext, useVoiceAssistant } from "@livekit/components-react";

// Owns ALL avatar.update sends (initial state after connect + every toggle change),
// so the gate's source of truth is SessionConfig.avatarOn and nothing double-sends.
export default function ApplyAvatarMode({ avatarOn }: { avatarOn: boolean }) {
  const room = useRoomContext();
  const { agent } = useVoiceAssistant();
  const lastSent = useRef<boolean | null>(null);
  const agentIdentity = agent?.identity;

  useEffect(() => {
    if (!agentIdentity) return;            // wait for the agent to join
    if (lastSent.current === avatarOn) return;
    lastSent.current = avatarOn;
    room.localParticipant
      .performRpc({
        destinationIdentity: agentIdentity,
        method: "avatar.update",
        payload: JSON.stringify({ on: avatarOn }),
      })
      .catch((err) => {
        // Non-fatal: lip-sync degrades to Path-A / no-publish; never break the room.
        console.warn("avatar.update failed", err);
        lastSent.current = null;           // allow a retry on the next change
      });
  }, [agentIdentity, avatarOn, room]);

  return null;
}
```

- [ ] **Step 2: Mount it in `VoiceRoom.tsx`**

Import and render it inside `<LiveKitRoom>`, next to `<ApplySetupOnConnect …/>`:
```tsx
import ApplyAvatarMode from "./ApplyAvatarMode";
// …
      <ApplySetupOnConnect config={sessionConfig} />
      <ApplyAvatarMode avatarOn={sessionConfig.avatarOn} />
```
(The existing `onToggleAvatar` already updates `sessionConfig.avatarOn`, so the in-room
Voice/Avatar toggle drives the RPC through this effect — no change to `TalkingScreen`.)

- [ ] **Step 3: Typecheck + build**

Run: `cd web && npx tsc --noEmit && npm run build`
Expected: green.

- [ ] **Step 4: Commit**

```bash
cd .. && git add web/app/ApplyAvatarMode.tsx web/app/VoiceRoom.tsx
git commit -m "feat(14-04): send avatar.update on connect + toggle (drives the lip-sync gate)"
```

---

## Task 5: Isolation-gate retirement note + fallback/isolation verification

**Files:**
- Modify: `agent/captioned_tts.py` (module docstring — note the intentional retirement)
- Modify: `CLAUDE.md` (`## CODE_PRINCIPLES Exceptions` or a short note) — record the
  avatar-on-only relaxation as the new auditable invariant.

- [ ] **Step 1: Document the retirement in code**

Append to the `agent/captioned_tts.py` module docstring:
```
ISOLATION (Phase 14, AVTR-12): the Phase-12 "avatar never touches the server pipeline"
gate is intentionally RETIRED for avatar-ON only. When the avatar is OFF this plugin
requests no timestamps and publishes nothing (voice-only is byte-for-byte the same
Kokoro audio with zero lk.avatar.* traffic — the new auditable invariant). When ON it
publishes word schedules over lk.avatar.lipsync; that server-side addition is the
documented, deliberate relaxation.
```

- [ ] **Step 2: Record the invariant in `CLAUDE.md`**

Add one line under `## CODE_PRINCIPLES Exceptions` (or the local-first section) of
`CLAUDE.md`: voice-only isolation (no `lk.avatar.*` when Avatar OFF) replaces the
Phase-12 frontend-only gate; avatar-on captioned TTS is an allowed server-pipeline touch.

- [ ] **Step 3: Manual — voice-only emits no lip-sync channel**

Start a session **Avatar OFF**. In DevTools, observe the LiveKit data channel (or add a
temporary log in `AvatarStage`'s `onLipsync` — but the avatar isn't mounted in
voice-only, so check at the room level via `room.on(RoomEvent.DataReceived)` in the
console). Expected: the agent speaks, and **no** `lk.avatar.lipsync` frames are
received. Toggle Avatar ON: frames now arrive and the mouth tracks words (Path-B);
kill the data channel for one utterance → mouth falls back to Path-A energy without
breaking.

- [ ] **Step 4: Commit**

```bash
git add agent/captioned_tts.py CLAUDE.md
git commit -m "docs(14-04): record avatar-on-only isolation retirement + voice-only invariant"
```

## Verification
**Self-checkable:**
- `python3 tests/test_captioned_gate.py` → `ok:`.
- `python3 -m py_compile agent/captioned_tts.py agent/captioned_gate.py agent/main.py` → clean.
- `cd web && npx tsc --noEmit && npm run build` → green.
- Code audit: with `_avatar_enabled=False`, `_run` requests `return_timestamps:false`
  and never calls `_publish_schedule`.

**OPERATOR (rolled into 14-09):**
- Avatar OFF: zero `lk.avatar.lipsync` frames over a full conversation; audio identical
  to the pre-gate build; zero added server VRAM.
- Avatar ON: lip-sync visibly tracks consonants/vowels (Path-B); missing-timestamp
  utterance degrades to Path-A without breakage.

## Artifacts this plan produces
- **NEW** `agent/captioned_gate.py` (+ `tests/test_captioned_gate.py`) — pure gate.
- **MODIFIED** `agent/captioned_tts.py` — `_avatar_enabled` flag + gated publish.
- **MODIFIED** `agent/main.py` — `avatar.update` RPC.
- **NEW** `web/app/ApplyAvatarMode.tsx` + **MODIFIED** `web/app/VoiceRoom.tsx` — sends
  the gate state on connect + toggle.
- Documented isolation-gate retirement (`captioned_tts.py`, `CLAUDE.md`).
