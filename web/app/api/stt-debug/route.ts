import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const STT_DEBUG_URL = process.env.STT_DEBUG_URL ?? "http://nemo-stt:8000/debug/hybrid";

export async function GET(): Promise<NextResponse> {
  try {
    const res = await fetch(STT_DEBUG_URL, { cache: "no-store" });
    const body = await res.text();
    return new NextResponse(body, {
      status: res.status,
      headers: {
        "content-type": res.headers.get("content-type") ?? "application/json",
        "cache-control": "no-store",
      },
    });
  } catch (error) {
    return NextResponse.json(
      {
        enabled: false,
        samples: [],
        error: error instanceof Error ? error.message : "STT debug endpoint unreachable",
      },
      { status: 502 },
    );
  }
}
