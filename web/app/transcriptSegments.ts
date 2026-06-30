export const TRANSCRIPTION_FINAL_ATTRIBUTE = "lk.transcription_final";
export const TRANSCRIPTION_SEGMENT_ATTRIBUTE = "lk.segment_id";
export const TRANSCRIPTION_TOPIC = "lk.transcription";
export const TRANSCRIPT_CORRECTION_TOPIC = "rehearsal.transcript.correction";
export const USER_IDENTITY_PREFIX = "user-";

type AttrValue = string | boolean | undefined;

export type TranscriptSegmentLike = {
  text: string;
  participantInfo: { identity: string };
  streamInfo: {
    id: string;
    attributes?: Record<string, AttrValue>;
  };
};

export type TranscriptLine = {
  id: string;
  sourceId: string;
  speaker: "You" | "Agent";
  participantIdentity: string;
  text: string;
  isFinal: boolean;
};

export type TranscriptCorrectionResult = {
  segments: TranscriptSegmentLike[];
  pendingCorrection: string | null;
};

export function isFinalTranscript(segment: TranscriptSegmentLike): boolean {
  const value = segment.streamInfo.attributes?.[TRANSCRIPTION_FINAL_ATTRIBUTE];
  return value === "true" || value === true;
}

export function speakerFor(identity: string): "You" | "Agent" {
  return identity.startsWith(USER_IDENTITY_PREFIX) ? "You" : "Agent";
}

export function normalizeTranscriptSegments(segments: TranscriptSegmentLike[]): TranscriptLine[] {
  const lines: TranscriptLine[] = [];
  for (const segment of segments) {
    const line = toLine(segment);
    if (!line.isFinal) {
      lines.push(line);
      continue;
    }
    const index = lastInterimIndex(lines, line.participantIdentity);
    if (index === -1) {
      lines.push(line);
      continue;
    }
    lines[index] = { ...line, id: lines[index].id };
  }
  return lines;
}

export function mergeTranscriptSegment(
  segments: TranscriptSegmentLike[],
  segment: TranscriptSegmentLike,
): TranscriptSegmentLike[] {
  const index = matchingSegmentIndex(segments, segment);
  if (index === -1) return [...segments, segment];

  const next = [...segments];
  next[index] = {
    ...segment,
    streamInfo: { ...segment.streamInfo, id: segments[index].streamInfo.id },
  };
  return next;
}

export function applyTranscriptCorrection(
  segments: TranscriptSegmentLike[],
  text: string,
): TranscriptSegmentLike[] {
  const correction = text.trim();
  if (!correction) return segments;
  const index = latestFinalUserSegmentIndex(segments);
  if (index === -1) return segments;

  const next = [...segments];
  next[index] = { ...next[index], text: correction };
  return next;
}

export function applyTranscriptCorrectionOrDefer(
  segments: TranscriptSegmentLike[],
  text: string | null,
): TranscriptCorrectionResult {
  const correction = text?.trim();
  if (!correction) return { segments, pendingCorrection: null };
  const next = applyTranscriptCorrection(segments, correction);
  return next === segments
    ? { segments, pendingCorrection: correction }
    : { segments: next, pendingCorrection: null };
}

function toLine(segment: TranscriptSegmentLike): TranscriptLine {
  const identity = segment.participantInfo.identity;
  return {
    id: segment.streamInfo.id,
    sourceId: segment.streamInfo.id,
    speaker: speakerFor(identity),
    participantIdentity: identity,
    text: segment.text,
    isFinal: isFinalTranscript(segment),
  };
}

function matchingSegmentIndex(
  segments: TranscriptSegmentLike[],
  segment: TranscriptSegmentLike,
): number {
  const segmentId = segment.streamInfo.attributes?.[TRANSCRIPTION_SEGMENT_ATTRIBUTE];
  return segments.findIndex((existing) => {
    if (existing.streamInfo.id === segment.streamInfo.id) return true;
    return !!segmentId && existing.streamInfo.attributes?.[TRANSCRIPTION_SEGMENT_ATTRIBUTE] === segmentId;
  });
}

function lastInterimIndex(lines: TranscriptLine[], identity: string): number {
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    if (lines[index].participantIdentity === identity && !lines[index].isFinal) {
      return index;
    }
  }
  return -1;
}

function latestFinalUserSegmentIndex(segments: TranscriptSegmentLike[]): number {
  for (let index = segments.length - 1; index >= 0; index -= 1) {
    const segment = segments[index];
    if (speakerFor(segment.participantInfo.identity) === "You" && isFinalTranscript(segment)) {
      return index;
    }
  }
  return -1;
}
