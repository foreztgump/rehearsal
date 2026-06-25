// LiveKit token-mint endpoint (Plan 01-03). Signs a short-lived JWT from the
// self-host dev key (LIVEKIT_API_KEY / LIVEKIT_API_SECRET) so the Phase 2 voice
// loop has a token path. Phase 1 only proves the route returns a signed token —
// no room is actually joined yet. All key material stays server-side (gitignored
// .env); the secret is never sent to the browser.
import { AccessToken } from "livekit-server-sdk";
import { NextResponse } from "next/server";

// Always run on demand (per-request signing) — never statically cached.
export const dynamic = "force-dynamic";

const DEFAULT_ROOM = "adept";
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

  const identity = `${DEFAULT_IDENTITY_PREFIX}-${Date.now()}`;
  const accessToken = new AccessToken(apiKey, apiSecret, {
    identity,
    ttl: TOKEN_TTL,
  });
  accessToken.addGrant({
    roomJoin: true,
    room: DEFAULT_ROOM,
    canPublish: true,
    canSubscribe: true,
  });

  const token = await accessToken.toJwt();
  return NextResponse.json({ token, identity, room: DEFAULT_ROOM });
}
