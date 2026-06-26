"use client";

import { useRoomContext, useParticipantAttributes, useVoiceAssistant } from "@livekit/components-react";
import { useEffect, useState } from "react";

// Browser → agent transport contract (Plan 04-01): each picked file uploads as
// its own byte stream on this topic; the agent publishes ingest status back on
// the `kb.state` participant attribute (the read pattern AgentStatePill uses for
// `lk.agent.state`). Mirrors agent/main.py KB_UPLOAD_TOPIC / KB_STATE_ATTRIBUTE.
const KB_UPLOAD_TOPIC = "kb.upload";
const KB_STATE_ATTRIBUTE = "kb.state";

// Client-side upload ceiling (M5). Mirrors the agent's KB_MAX_RAW_BYTES (25 MB):
// reject oversize files with a friendly message BEFORE streaming them, so a user
// doesn't wait on a large transfer the agent will only reject after extraction.
const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
const MAX_UPLOAD_LABEL = "25 MB";

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

const panelStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "0.6rem",
  width: "20rem",
  padding: "1rem",
  border: "1px solid #30363d",
  borderRadius: "0.5rem",
  background: "#0d1117",
  color: "#c9d1d9",
  fontSize: "0.9rem",
};

const inputStyle: React.CSSProperties = {
  padding: "0.4rem 0.5rem",
  borderRadius: "0.35rem",
  border: "1px solid #30363d",
  background: "#161b22",
  color: "#c9d1d9",
  fontWeight: 400,
};

/**
 * KB upload panel + active indicator (KB-01 / KB-07 / REL-03). The file picker
 * uploads each selected file as its own LiveKit byte stream via
 * `sendFile(file, { topic: "kb.upload" })` — no file leaves the LAN (PERF-03), it
 * rides the existing room connection. The indicator reads the agent's `kb.state`
 * participant attribute and renders idle→uploading→parsing→distilling→ready (n
 * docs) | error, showing any error string verbatim (clear error). Must render
 * inside <LiveKitRoom> for room context.
 */
export default function KbPanel() {
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
    const tooBig = Array.from(files).find((f) => f.size > MAX_UPLOAD_BYTES);
    if (tooBig) {
      setStatus("error");
      setError(`"${tooBig.name}" is over ${MAX_UPLOAD_LABEL} — upload a smaller file`);
      return;
    }
    setStatus("uploading");
    setError("");
    // Per-file byte stream: a multi-file pick becomes N streams (KB-01 / §1.3).
    try {
      for (const file of Array.from(files)) {
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
      <strong style={{ fontSize: "1rem" }}>Knowledge Base</strong>

      <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem", fontWeight: 600 }}>
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

      <span style={{ minHeight: "1.2rem", color: STATUS_COLOR[status], fontWeight: 600 }}>
        {label}
      </span>

      {status === "error" && error && (
        <span style={{ color: STATUS_COLOR.error, fontWeight: 400 }}>{error}</span>
      )}

      <p style={{ color: "#8b949e", margin: 0, fontWeight: 400 }}>
        PDF, TXT, MD, or DOCX. Files stay on your LAN — they ride the existing room
        connection, nothing is uploaded to the cloud.
      </p>
    </div>
  );
}
