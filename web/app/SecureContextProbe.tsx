"use client";

import { useEffect, useState } from "react";

type ProbeState = "checking" | "defined" | "undefined";

/**
 * Reads whether `navigator.mediaDevices` exists in the current context and
 * renders a visible PASS/FAIL line. Does NOT request the mic — Phase 1 only
 * proves the secure-context API surface is present (no mic prompt yet).
 */
export default function SecureContextProbe() {
  const [state, setState] = useState<ProbeState>("checking");

  useEffect(() => {
    const hasMediaDevices =
      typeof navigator !== "undefined" && !!navigator.mediaDevices;
    setState(hasMediaDevices ? "defined" : "undefined");
  }, []);

  if (state === "checking") {
    return <p>secure context: checking…</p>;
  }

  const passed = state === "defined";
  return (
    <p style={{ color: passed ? "#3fb950" : "#f85149", fontWeight: 600 }}>
      secure context: mediaDevices {state}
    </p>
  );
}
