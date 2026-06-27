"use client";

import { useRoomContext, useParticipantAttributes, useVoiceAssistant } from "@livekit/components-react";
import { useEffect, useState } from "react";

import { font, inputStyle, palette, panelStyle, space } from "./ui/tokens";

// Browser → agent transport contract (Plan 04-01): each picked file uploads as
// its own byte stream on this topic; the agent publishes ingest status back on
// the `kb.state` participant attribute (the read pattern AgentStatePill uses for
// `lk.agent.state`). Mirrors agent/main.py KB_UPLOAD_TOPIC / KB_STATE_ATTRIBUTE.
export const KB_UPLOAD_TOPIC = "kb.upload";
const KB_STATE_ATTRIBUTE = "kb.state";

// Client-side upload ceiling (M5). Mirrors the agent's KB_MAX_RAW_BYTES (25 MB):
// reject oversize files with a friendly message BEFORE streaming them, so a user
// doesn't wait on a large transfer the agent will only reject after extraction.
export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
export const MAX_UPLOAD_LABEL = "25 MB";

// `distilling` is included now so 04-02 (distill → inject) needs no signature
// change — the agent will set it between `parsing` and `ready` there.
type KbStatus = "idle" | "uploading" | "parsing" | "distilling" | "ready" | "error";

// Mirror PersonaPanel's STATUS_LABEL/STATUS_COLOR convention (inline-styled, no
// CSS framework). The label for `ready` is computed with the doc count below.
const STATUS_LABEL: Record<KbStatus, string> = {
  idle: "no documents loaded",
  uploading: "uploading…",
  parsing: "parsing…",
  distilling: "distilling…",
  ready: "ready",
  error: "error",
};

const STATUS_COLOR: Record<KbStatus, string> = {
  idle: "#8b949e",
  uploading: "#58a6ff",
  parsing: "#d29922",
  distilling: "#d29922",
  ready: "#3fb950",
  error: "#f85149",
};

// Shared size pre-check (M5): returns an error message for the first oversize
// file, or "" when all files are within the ceiling. Used by both the live
// sendFile path and the controlled queue path so the gate stays byte-identical.
function oversizeError(files: File[]): string {
  const tooBig = files.find((f) => f.size > MAX_UPLOAD_BYTES);
  return tooBig ? `"${tooBig.name}" is over ${MAX_UPLOAD_LABEL} — upload a smaller file` : "";
}

/**
 * Controlled KB picker — the setup-screen path. Instead of streaming files to an
 * agent (no room yet), it QUEUES picked files into lifted state via
 * `onFilesChange`, applying the SAME MAX_UPLOAD_BYTES pre-check so an oversize
 * file is rejected before connect. ApplySetupOnConnect drains the queue with
 * `sendFile` once the agent joins. NO room context, NO RPC.
 */
function KbQueueFields({
  files,
  onFilesChange,
}: {
  files: File[];
  onFilesChange: (files: File[]) => void;
}) {
  const [error, setError] = useState("");

  function queue(picked: FileList) {
    const next = Array.from(picked);
    const err = oversizeError(next);
    if (err) {
      setError(err);
      return;
    }
    setError("");
    // Append to any already-queued files (dedupe by name+size so re-picking the
    // same file doesn't double-queue it).
    const merged = [...files];
    for (const f of next) {
      if (!merged.some((m) => m.name === f.name && m.size === f.size)) merged.push(f);
    }
    onFilesChange(merged);
  }

  function remove(target: File) {
    onFilesChange(files.filter((f) => f !== target));
  }

  return (
    <div style={panelStyle}>
      <strong style={{ fontSize: font.size.heading }}>Knowledge Base</strong>

      <label style={{ display: "flex", flexDirection: "column", gap: space.xs, fontWeight: font.weight.semibold }}>
        Upload material
        <input
          style={inputStyle}
          type="file"
          accept=".pdf,.txt,.md,.docx"
          multiple
          onChange={(e) => {
            if (e.target.files && e.target.files.length > 0) queue(e.target.files);
          }}
        />
      </label>

      {files.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: "1.2rem", color: palette.textMuted, fontWeight: font.weight.regular }}>
          {files.map((f) => (
            <li key={`${f.name}-${f.size}`} style={{ display: "flex", justifyContent: "space-between", gap: space.sm }}>
              <span>{f.name}</span>
              <button
                type="button"
                onClick={() => remove(f)}
                style={{
                  background: "none",
                  border: "none",
                  color: palette.textMuted,
                  cursor: "pointer",
                  padding: 0,
                  fontWeight: font.weight.semibold,
                }}
              >
                remove
              </button>
            </li>
          ))}
        </ul>
      )}

      {error && (
        <span style={{ color: STATUS_COLOR.error, fontWeight: font.weight.regular }}>{error}</span>
      )}

      <p style={{ color: palette.textMuted, margin: 0, fontWeight: font.weight.regular }}>
        PDF, TXT, MD, or DOCX. Files stay on your LAN — they ride the existing room
        connection, nothing is uploaded to the cloud. They upload when your session starts.
      </p>
    </div>
  );
}

/**
 * Live (uncontrolled) KB upload panel + active indicator (KB-01 / KB-07 /
 * REL-03). The file picker uploads each selected file as its own LiveKit byte
 * stream via `sendFile(file, { topic: "kb.upload" })` — no file leaves the LAN
 * (PERF-03). The indicator reads the agent's `kb.state` participant attribute and
 * renders idle→uploading→parsing→distilling→ready (n docs) | error. Must render
 * inside <LiveKitRoom> for room context.
 */
function KbPanelLive() {
  const room = useRoomContext();
  const { agent } = useVoiceAssistant();
  const [status, setStatus] = useState<KbStatus>("idle");
  const [docs, setDocs] = useState(0);
  const [error, setError] = useState("");

  // Read the agent participant's attributes — the same attribute channel
  // AgentStatePill reads for `lk.agent.state`. When `kb.state` appears, parse its
  // JSON {status, docs, error} and reflect it locally.
  const { attributes } = useParticipantAttributes({ participant: agent });

  useEffect(() => {
    const raw = attributes?.[KB_STATE_ATTRIBUTE];
    if (!raw) return;
    try {
      const parsed = JSON.parse(raw) as { status?: KbStatus; docs?: number; error?: string };
      if (parsed.status) setStatus(parsed.status);
      setDocs(parsed.docs ?? 0);
      setError(parsed.error ?? "");
    } catch {
      // Malformed attribute — ignore (the agent always writes valid JSON).
    }
  }, [attributes]);

  async function upload(files: FileList) {
    // Pre-upload size check (M5): bail with a clear message before any transfer.
    const list = Array.from(files);
    const err = oversizeError(list);
    if (err) {
      setStatus("error");
      setError(err);
      return;
    }
    setStatus("uploading");
    setError("");
    // Per-file byte stream: a multi-file pick becomes N streams (KB-01 / §1.3).
    try {
      for (const file of list) {
        await room.localParticipant.sendFile(file, { topic: KB_UPLOAD_TOPIC });
      }
    } catch (err) {
      // A failed send (disconnect / transport error) never reaches the agent, so
      // the kb.state channel can't report it — surface it here instead of leaving
      // the panel stuck on "uploading".
      setStatus("error");
      setError(err instanceof Error ? `Upload failed: ${err.message}` : "Upload failed");
    }
  }

  const label =
    status === "ready" ? `ready (${docs} ${docs === 1 ? "doc" : "docs"})` : STATUS_LABEL[status];

  return (
    <div style={panelStyle}>
      <strong style={{ fontSize: font.size.heading }}>Knowledge Base</strong>

      <label style={{ display: "flex", flexDirection: "column", gap: space.xs, fontWeight: font.weight.semibold }}>
        Upload material
        <input
          style={inputStyle}
          type="file"
          accept=".pdf,.txt,.md,.docx"
          multiple
          onChange={(e) => {
            if (e.target.files && e.target.files.length > 0) upload(e.target.files);
          }}
        />
      </label>

      <span
        className="transition-status"
        style={{ minHeight: "1.2rem", color: STATUS_COLOR[status], fontWeight: font.weight.semibold }}
      >
        {label}
      </span>

      {status === "error" && error && (
        <span style={{ color: STATUS_COLOR.error, fontWeight: font.weight.regular }}>{error}</span>
      )}

      <p style={{ color: palette.textMuted, margin: 0, fontWeight: font.weight.regular }}>
        PDF, TXT, MD, or DOCX. Files stay on your LAN — they ride the existing room
        connection, nothing is uploaded to the cloud.
      </p>
    </div>
  );
}

/**
 * KB upload panel (KB-01 / KB-07 / REL-03). Two modes:
 * - Controlled (setup path): pass `files` + `onFilesChange` → QUEUES picked files
 *   into lifted state (same size pre-check) with NO room context / NO sendFile.
 * - Uncontrolled (live path): omit props → immediate per-file `sendFile` + the
 *   agent `kb.state` indicator, exactly as today.
 */
export default function KbPanel({
  files,
  onFilesChange,
}: {
  files?: File[];
  onFilesChange?: (files: File[]) => void;
}) {
  if (onFilesChange) {
    return <KbQueueFields files={files ?? []} onFilesChange={onFilesChange} />;
  }
  return <KbPanelLive />;
}
