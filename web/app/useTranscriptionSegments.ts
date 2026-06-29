"use client";

import { useRoomContext } from "@livekit/components-react";
import { RoomEvent, type Room } from "livekit-client";
import { useSyncExternalStore } from "react";

import {
  applyTranscriptCorrectionOrDefer,
  mergeTranscriptSegment,
  TRANSCRIPT_CORRECTION_TOPIC,
  TRANSCRIPTION_TOPIC,
  type TranscriptSegmentLike,
} from "./transcriptSegments";

type TranscriptionStore = {
  getSnapshot: () => TranscriptSegmentLike[];
  subscribe: (listener: () => void) => () => void;
};

type StoreState = {
  listeners: Set<() => void>;
  pendingCorrection: string | null;
  snapshot: TranscriptSegmentLike[];
};

type TextStreamHandler = Parameters<Room["registerTextStreamHandler"]>[1];

const stores = new WeakMap<Room, TranscriptionStore>();

export function useTranscriptionSegments(): TranscriptSegmentLike[] {
  const room = useRoomContext();
  const store = getTranscriptionStore(room);
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
}

function getTranscriptionStore(room: Room): TranscriptionStore {
  const existing = stores.get(room);
  if (existing) return existing;

  const store = createTranscriptionStore(room);
  stores.set(room, store);
  return store;
}

function createTranscriptionStore(room: Room): TranscriptionStore {
  const state: StoreState = { listeners: new Set(), pendingCorrection: null, snapshot: [] };
  const reset = () => {
    state.pendingCorrection = null;
    emit(state, []);
  };
  const handler = createStreamHandler(state);
  const correctionHandler = createCorrectionHandler(state);
  const registration = createRegistration(room, handler, correctionHandler, reset);

  function subscribe(listener: () => void) {
    state.listeners.add(listener);
    registration.register();
    return () => {
      state.listeners.delete(listener);
      if (state.listeners.size === 0) registration.unregister();
    };
  }

  return { getSnapshot: () => state.snapshot, subscribe };
}

function emit(state: StoreState, next: TranscriptSegmentLike[]) {
  state.snapshot = next;
  state.listeners.forEach((listener) => listener());
}

function createStreamHandler(state: StoreState): TextStreamHandler {
  return async (reader, participantInfo) => {
    let text = "";
    try {
      for await (const chunk of reader) {
        text += chunk;
        const merged = mergeTranscriptSegment(state.snapshot, { text, participantInfo, streamInfo: reader.info });
        emitCorrected(state, merged, state.pendingCorrection);
      }
    } catch (error) {
      console.error("Transcription stream failed", error);
    }
  };
}

function createCorrectionHandler(state: StoreState) {
  const decoder = new TextDecoder();
  return (payload: Uint8Array, _participant?: unknown, _kind?: unknown, topic?: string) => {
    if (topic !== TRANSCRIPT_CORRECTION_TOPIC) return;
    const text = correctionText(payload, decoder);
    if (text) emitCorrected(state, state.snapshot, text);
  };
}

function emitCorrected(state: StoreState, segments: TranscriptSegmentLike[], correction: string | null) {
  const result = applyTranscriptCorrectionOrDefer(segments, correction);
  state.pendingCorrection = result.pendingCorrection;
  emit(state, result.segments);
}

function correctionText(payload: Uint8Array, decoder: TextDecoder): string | null {
  try {
    const parsed = JSON.parse(decoder.decode(payload));
    return typeof parsed.text === "string" ? parsed.text : null;
  } catch {
    return null;
  }
}

function createRegistration(
  room: Room,
  handler: TextStreamHandler,
  correctionHandler: ReturnType<typeof createCorrectionHandler>,
  reset: () => void,
) {
  let registered = false;
  return {
    register() {
      if (registered) return;
      room.registerTextStreamHandler(TRANSCRIPTION_TOPIC, handler);
      room.on(RoomEvent.DataReceived, correctionHandler);
      room.on(RoomEvent.Disconnected, reset);
      registered = true;
    },
    unregister() {
      if (!registered) return;
      room.unregisterTextStreamHandler(TRANSCRIPTION_TOPIC);
      room.off(RoomEvent.DataReceived, correctionHandler);
      room.off(RoomEvent.Disconnected, reset);
      registered = false;
    },
  };
}
