// Pure retry-budget decision for ApplyAvatarMode (F32), extracted so the
// desync-after-exhaustion behavior is unit-testable without a React renderer.
//
// The avatar.update RPC is registered late by the agent, so an initial send can
// reject; ApplyAvatarMode retries a bounded number of times. The bug (F32): the
// retry counter only re-armed on a SUCCESS, so once the budget was exhausted
// without one, a LATER toggle got a single attempt and could permanently desync
// avatarOn from the agent's lip-sync gate. The fix is to treat each new toggle
// (a change of the target value) as a fresh budget.

export const AVATAR_UPDATE_MAX_RETRIES = 5;
export const AVATAR_UPDATE_RETRY_MS = 500;

// Given the current retry tick and whether this send is for a NEW target value
// (a toggle) vs. a retry of the same value, return the tick to use for THIS send.
// A new toggle always resets the budget to 0; a retry keeps the running tick.
export function retryTickForSend(currentTick: number, isNewTarget: boolean): number {
  return isNewTarget ? 0 : currentTick;
}

// Should we schedule another retry after a failed send at `tick`?
export function shouldScheduleRetry(tick: number, max: number = AVATAR_UPDATE_MAX_RETRIES): boolean {
  return tick < max;
}
