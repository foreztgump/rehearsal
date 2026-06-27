"use client";

import { useEffect, useState } from "react";

// UI-SPEC Copywriting table (Mic group helper). Shown when labels are still
// empty (no permission grant yet) so the user knows selection is optional.
const HELPER_COPY = "Allow microphone access to choose a device. Optional — we'll use your default otherwise.";

/**
 * Controlled microphone picker for the setup screen. Lists `audioinput` devices
 * from `navigator.mediaDevices.enumerateDevices()` into a <select>; the chosen
 * `deviceId` is plumbed into LiveKit `audioCaptureDefaults.deviceId` on connect
 * (selection is OPTIONAL — the browser default is used otherwise).
 *
 * Device labels are empty before a permission grant, so a one-time "Allow
 * microphone access" button calls `getUserMedia({audio:true})` to unlock labels
 * then re-enumerates. NO room context, NO server call. Enumerate/permission
 * failures degrade to an inline muted note — never a thrown/uncaught error.
 */
export default function MicPicker({
  value,
  onChange,
  className,
}: {
  value?: string;
  onChange: (deviceId: string) => void;
  className?: string;
}) {
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [labelsUnlocked, setLabelsUnlocked] = useState(false);
  const [note, setNote] = useState("");

  async function enumerate() {
    // Boundary handling (CODE_PRINCIPLES): mediaDevices may be absent in an
    // insecure context — degrade to an inline note, never throw.
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.enumerateDevices) {
      setNote("Microphone selection isn't available in this browser context.");
      return;
    }
    try {
      const all = await navigator.mediaDevices.enumerateDevices();
      const inputs = all.filter((d) => d.kind === "audioinput");
      setDevices(inputs);
      // Labels are non-empty only after a permission grant.
      setLabelsUnlocked(inputs.some((d) => d.label !== ""));
    } catch {
      setNote("Couldn't list microphones — your default will be used.");
    }
  }

  useEffect(() => {
    enumerate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function unlockLabels() {
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setNote("Microphone access isn't available in this browser context.");
      return;
    }
    try {
      // One-shot permission grant to populate device labels. Stop the tracks
      // immediately — we only needed the grant, not a live capture.
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((t) => t.stop());
      setNote("");
      await enumerate();
    } catch {
      // Denied/dismissed — selection stays optional, default mic is used.
      setNote("Microphone access denied — your default will be used.");
    }
  }

  return (
    <div className={className ? `field ${className}` : "field"}>
      <label className="field-label" htmlFor="mic-select">
        Microphone
      </label>
      <select
        id="mic-select"
        className="control"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">System default</option>
        {devices.map((d, i) => (
          <option key={d.deviceId || i} value={d.deviceId}>
            {d.label || `Microphone ${i + 1}`}
          </option>
        ))}
      </select>

      {!labelsUnlocked && (
        <button type="button" className="btn-ghost" style={{ alignSelf: "flex-start" }} onClick={unlockLabels}>
          Allow microphone access
        </button>
      )}

      <span style={{ color: "var(--text-muted)", fontWeight: 400, fontSize: "12.5px" }}>
        {note || HELPER_COPY}
      </span>
    </div>
  );
}
