// Pure readiness/ack helpers for ApplySetupOnConnect (F13), extracted so the
// gate + ack logic is unit-testable without a React renderer.
//
// The agent participant is visible from ctx.connect(), but its RPC methods
// (persona/mode/model.update) and the kb.upload byte-stream handler only
// register AFTER session.start() — which is also when it begins publishing the
// lk.agent.state attribute (surfaced as useVoiceAssistant().state). So a live
// state is a safe proxy for "handlers registered": gating on it avoids firing an
// early performRpc (rejects UNSUPPORTED_METHOD) or, worse, an early sendFile
// (LiveKit silently drops a stream with no registered handler → a setup-queued
// KB upload vanishes with no kb.state error).

// The post-start states the agent publishes once it is actually running a turn
// loop. Pre-start / transport states ("initializing", "connecting",
// "disconnected", empty) mean the handlers may not exist yet.
const READY_STATES = new Set(["listening", "thinking", "speaking"]);

export function agentReadyForApply(state: string | undefined | null): boolean {
  return state != null && READY_STATES.has(state);
}

// The agent RPC handlers resolve the performRpc promise with a STRING ack
// ("applied" on success, "error" on a validation rejection) — they do not throw.
// So a transport-only try/catch treats an agent rejection as success; the live
// panels (ModelPanel/PersonaPanel) check the ack string, and so must this.
export function ackApplied(ack: string): boolean {
  return ack === "applied";
}
