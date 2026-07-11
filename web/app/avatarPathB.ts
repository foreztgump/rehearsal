import { AGENT_MOODS } from "./avatarConfig.ts";

export type ScheduleWord = { w: string; s: number; e: number };
export type LipsyncSchedule = {
  seq: number;
  request_id?: string;
  words: ScheduleWord[];
  mood?: string;
};
export type VisemeSpan = { m: string; s: number; e: number };
// `mood` is non-optional on the internal types: queueSchedule always resolves it to
// a valid AGENT_MOODS value, so downstream code never re-validates.
export type QueuedSchedule = LipsyncSchedule & {
  timeline: VisemeSpan[];
  mood: string;
};
export type ActiveSchedule = {
  seq: number;
  timeline: VisemeSpan[];
  anchor: number;
  mood: string;
};

// Fallback when a schedule arrives with no `mood` or an unknown one (setMood throws
// on unknown, so the default MUST be a valid AGENT_MOODS member).
export const DEFAULT_MOOD = "neutral";
export type PathBInput = {
  active: ActiveSchedule | null;
  queue: QueuedSchedule[];
};
export type PathBStep = { now: number; audible: boolean };
export type PathBResult = PathBInput & { anchoredSeq: number | null };
export type SequenceGate = { requestId: string | null; lastSeq: number };

export const PATH_B_END_GRACE_SECONDS = 0.15;

const DIGRAPH_VISEMES: Record<string, string[]> = {
  th: ["viseme_TH"],
  sh: ["viseme_CH"],
  ch: ["viseme_CH"],
  ph: ["viseme_FF"],
  ck: ["viseme_kk"],
  qu: ["viseme_kk", "viseme_U"],
  wh: ["viseme_U"],
};

const LETTER_VISEMES: Record<string, string> = {
  a: "viseme_aa",
  e: "viseme_E",
  i: "viseme_I",
  y: "viseme_I",
  o: "viseme_O",
  u: "viseme_U",
  w: "viseme_U",
  m: "viseme_PP",
  b: "viseme_PP",
  p: "viseme_PP",
  f: "viseme_FF",
  v: "viseme_FF",
  t: "viseme_DD",
  d: "viseme_DD",
  n: "viseme_nn",
  l: "viseme_nn",
  k: "viseme_kk",
  g: "viseme_kk",
  c: "viseme_kk",
  q: "viseme_kk",
  x: "viseme_kk",
  j: "viseme_CH",
  s: "viseme_SS",
  z: "viseme_SS",
  r: "viseme_RR",
};

export function wordToVisemes(word: string): string[] {
  const w = word.toLowerCase().replace(/[^a-z]/g, "");
  const out: string[] = [];
  const push = (visemes: string[]) => {
    for (const m of visemes) {
      if (out.length === 0 || out[out.length - 1] !== m) out.push(m);
    }
  };

  let i = 0;
  while (i < w.length) {
    const two = w.slice(i, i + 2);
    if (DIGRAPH_VISEMES[two]) {
      push(DIGRAPH_VISEMES[two]);
      i += 2;
      continue;
    }

    const viseme = LETTER_VISEMES[w[i]];
    if (viseme) push([viseme]);
    i += 1;
  }

  return out.length === 0 ? ["viseme_aa"] : out;
}

function isScheduleWord(
  word: Partial<ScheduleWord> | null | undefined,
): word is ScheduleWord {
  return (
    !!word &&
    typeof word.w === "string" &&
    Number.isFinite(word.s) &&
    Number.isFinite(word.e)
  );
}

export function scheduleToTimeline(words: ScheduleWord[]): VisemeSpan[] {
  const spans: VisemeSpan[] = [];
  for (const word of words) {
    if (!isScheduleWord(word)) continue;
    const dur = Math.max(0, word.e - word.s);
    if (dur <= 0 || !word.w) continue;
    const visemes = wordToVisemes(word.w);
    const step = dur / visemes.length;
    for (let i = 0; i < visemes.length; i++) {
      spans.push({
        m: visemes[i],
        s: word.s + i * step,
        e: word.s + (i + 1) * step,
      });
    }
  }
  return spans;
}

export function queueSchedule(
  schedule: Partial<LipsyncSchedule> | null | undefined,
): QueuedSchedule | null {
  const seq = schedule?.seq;
  if (
    typeof seq !== "number" ||
    !Number.isFinite(seq) ||
    !Array.isArray(schedule?.words)
  ) {
    return null;
  }
  const words = schedule.words.filter(isScheduleWord);
  const timeline = scheduleToTimeline(words);
  if (timeline.length === 0) return null;
  const request_id =
    typeof schedule.request_id === "string" ? schedule.request_id : undefined;
  const mood =
    typeof schedule.mood === "string" && AGENT_MOODS.has(schedule.mood)
      ? schedule.mood
      : DEFAULT_MOOD;
  return { seq, request_id, words, timeline, mood };
}

export function acceptScheduleSequence(
  gate: SequenceGate,
  schedule: QueuedSchedule,
  accepting: boolean,
): SequenceGate | null {
  if (!accepting) return null;
  const requestId = schedule.request_id ?? null;
  if (requestId === gate.requestId && schedule.seq <= gate.lastSeq) {
    return null;
  }
  return { requestId, lastSeq: schedule.seq };
}

export function advancePathB(
  input: PathBInput,
  step: PathBStep,
): PathBResult {
  let active = input.active;
  let anchor = step.now;

  if (active) {
    const end = scheduleEnd(active);
    if (step.now <= end + PATH_B_END_GRACE_SECONDS) {
      return { active, queue: input.queue, anchoredSeq: null };
    }
    active = null;
    anchor = end;
  }

  if (!step.audible || input.queue.length === 0) {
    return { active, queue: input.queue, anchoredSeq: null };
  }

  const next = input.queue[0];
  return {
    active: { seq: next.seq, timeline: next.timeline, anchor, mood: next.mood },
    queue: input.queue.slice(1),
    anchoredSeq: next.seq,
  };
}

export function activeVisemeAt(
  active: ActiveSchedule | null,
  now: number,
): string | null {
  if (!active || now > scheduleEnd(active) + PATH_B_END_GRACE_SECONDS) {
    return null;
  }

  const t = now - active.anchor;
  return active.timeline.find((span) => t >= span.s && t < span.e)?.m ?? null;
}

function scheduleEnd(active: ActiveSchedule): number {
  return active.anchor + active.timeline[active.timeline.length - 1].e;
}
