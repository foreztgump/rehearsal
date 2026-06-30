// LiveKit token-mint endpoint (Plan 01-03). Signs a short-lived JWT from the
// self-host dev key (LIVEKIT_API_KEY / LIVEKIT_API_SECRET) so the Phase 2 voice
// loop has a token path. Phase 1 only proves the route returns a signed token —
// no room is actually joined yet. All key material stays server-side (gitignored
// .env); the secret is never sent to the browser.
import { randomUUID } from "crypto";

import { AccessToken } from "livekit-server-sdk";
import { NextResponse } from "next/server";

// Always run on demand (per-request signing) — never statically cached.
export const dynamic = "force-dynamic";

// A FRESH room name per token (not a fixed "rehearsal"). Automatic agent dispatch is a
// JT_ROOM job that fires only when a room is CREATED — never on a join into an
// existing room (livekit.yaml). With a fixed name, End → quick Start rejoins the
// still-alive room (inside empty_timeout/departure_timeout) and gets NO agent — a
// dead "Listening…" session. A unique room per connect makes every session a fresh
// room, so the agent always dispatches. The agent is room-name-agnostic (ctx.room).
const ROOM_PREFIX = "rehearsal";
const DEFAULT_IDENTITY_PREFIX = "user";
const TOKEN_TTL = "1h";

export async function GET(): Promise<NextResponse> {
  const apiKey = process.env.LIVEKIT_API_KEY;
  const apiSecret = process.env.LIVEKIT_API_SECRET;

  if (!apiKey || !apiSecret) {
    return NextResponse.json(
      { error: "LIVEKIT_API_KEY / LIVEKIT_API_SECRET not configured" },
      { status: 500 },
    );
  }

  // Use a UUID, not Date.now(): two requests in the same millisecond (multi-tab /
  // load) would otherwise collide on identity, and LiveKit evicts the older
  // participant when a duplicate identity joins. The `user-` prefix is the
  // cross-file contract Transcript.tsx uses to attribute local vs agent messages.
  const identity = `${DEFAULT_IDENTITY_PREFIX}-${randomUUID()}`;
  const room = `${ROOM_PREFIX}-${randomUUID()}`;
  const accessToken = new AccessToken(apiKey, apiSecret, {
    identity,
    ttl: TOKEN_TTL,
  });
  accessToken.addGrant({
    roomJoin: true,
    room,
    canPublish: true,
    canSubscribe: true,
  });

  const token = await accessToken.toJwt();
  return NextResponse.json({ token, identity, room });
}
