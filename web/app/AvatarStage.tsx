"use client";

import { useEffect, useRef, useState } from "react";
import { CAMERA_VIEW, TALKINGHEAD_SPECIFIER } from "./avatarConfig";

// Minimal shape of the TalkingHead instance we touch in 12-01. The full surface
// (showAvatar, speakAudio, setMood, …) is wired in 12-02.
type TalkingHeadInstance = {
  dispose: () => void;
};
type TalkingHeadModule = {
  TalkingHead: new (
    node: HTMLElement,
    opt: Record<string, unknown>,
  ) => TalkingHeadInstance;
};

/**
 * Dynamic-imported (ssr:false) WebGL avatar stage for the OPTIONAL 3D talking head
 * (Phase 12, AVTR-01/05/08). This plan (12-01) only owns the mount/unmount lifecycle
 * and the interview framing — NO lip-sync, NO audio tap, NO persona wiring, NO GLB load
 * (those are 12-02). The library resolves at runtime via the same-origin importmap in
 * layout.tsx, so it stays out of the voice-only webpack bundle.
 */
export default function AvatarStage() {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const headRef = useRef<TalkingHeadInstance | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );

  useEffect(() => {
    let cancelled = false;

    (async () => {
      const host = hostRef.current;
      if (!host) return;

      try {
        // Variable specifier + webpackIgnore so webpack does NOT try to bundle the
        // library — it is resolved at runtime by the importmap (AVTR-01).
        const mod: TalkingHeadModule = await import(
          /* webpackIgnore: true */ TALKINGHEAD_SPECIFIER
        );

        if (cancelled) return;

        // Construct with interview framing (AVTR-05), no lip-sync modules and no TTS
        // path: empty ttsEndpoint => TalkingHead never builds the Google-TTS audio
        // pipeline or calls out; lipsyncModules:[] => no dynamic lipsync-*.mjs imports.
        // The scene renders empty here; showAvatar() is added in 12-02.
        const head = new mod.TalkingHead(host, {
          cameraView: CAMERA_VIEW,
          lipsyncModules: [],
          ttsEndpoint: "",
          jwtGet: null,
          // TODO(12-02): await head.showAvatar({ url: <persona GLB> }) once the
          // default GLB + persona→GLB map land (AVTR-06/07). Do NOT fetch here.
        });

        if (cancelled) {
          // Mounted then immediately unmounted before init resolved — tear down now
          // so we never leak a running renderer/AudioContext.
          head.dispose();
          return;
        }

        headRef.current = head;
        setStatus("ready");
      } catch {
        // WebGL-unavailable or import failure: degrade gracefully (AVTR-08). The
        // toggle is the escape hatch — render an inline message, never throw, no retry.
        if (!cancelled) setStatus("error");
      }
    })();

    // Full teardown on unmount / Avatar-toggle-OFF (AVTR-01/AVTR-08): dispose() stops
    // the rAF loop, suspends/disconnects the AudioContext nodes, disposes the three.js
    // scene + renderer (loses the WebGL context) and removes the canvas from the DOM.
    return () => {
      cancelled = true;
      const head = headRef.current;
      if (head) {
        try {
          head.dispose();
        } catch {
          // dispose is best-effort during teardown; never throw out of cleanup.
        }
        headRef.current = null;
      }
    };
  }, []);

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <div
        ref={hostRef}
        aria-label="3D avatar"
        style={{ width: "100%", height: "100%" }}
      />
      {status === "loading" && (
        <p style={{ color: "#8b949e", fontSize: "0.9rem" }}>loading avatar…</p>
      )}
      {status === "error" && (
        <p style={{ color: "#d29922", fontSize: "0.9rem" }}>
          3D avatar unavailable on this device — use Voice only.
        </p>
      )}
    </div>
  );
}
