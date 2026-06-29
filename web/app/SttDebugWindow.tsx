"use client";

import { useEffect, useState } from "react";

import { font, palette, radius, space } from "./ui/tokens";

type DebugSample = {
  seq: number;
  stream_transcript: string;
  parakeet_transcript: string;
  audio_wav_b64: string;
  audio_ms: number;
  audio_peak?: number;
  audio_rms?: number;
  audio_clip_pct?: number;
  leading_silence_ms?: number;
  trailing_silence_ms?: number;
  pcm_bytes: number;
  dur_ms: number;
  at_ms: number;
};

type DebugPayload = {
  enabled: boolean;
  engine?: string;
  runtime?: string;
  samples?: DebugSample[];
  error?: string;
};

const POLL_MS = 1000;

export default function SttDebugWindow() {
  const [data, setData] = useState<DebugPayload>({ enabled: false, samples: [] });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const res = await fetch("/api/stt-debug", { cache: "no-store" });
        const next = await res.json();
        if (!cancelled) setData(next);
      } catch (error) {
        if (!cancelled) {
          setData({
            enabled: false,
            samples: [],
            error: error instanceof Error ? error.message : "debug fetch failed",
          });
        }
      }
    }

    load();
    const id = window.setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const samples = [...(data.samples ?? [])].reverse();

  return (
    <aside
      style={{
        position: "fixed",
        right: space.md,
        bottom: space.md,
        zIndex: 50,
        width: "min(460px, calc(100vw - 32px))",
        maxHeight: "56dvh",
        overflow: "auto",
        border: `1px solid ${palette.border}`,
        borderRadius: radius.control,
        background: palette.panel,
        color: palette.textBody,
        boxShadow: "0 16px 40px rgba(0,0,0,0.35)",
        fontSize: font.size.label,
      }}
    >
      <details open>
        <summary style={{ cursor: "pointer", padding: space.md, fontWeight: font.weight.semibold }}>
          STT debug {data.engine ? `(${data.engine}/${data.runtime ?? "?"})` : ""}
        </summary>
        <div style={{ display: "flex", flexDirection: "column", gap: space.md, padding: `0 ${space.md} ${space.md}` }}>
          {data.error && <div style={{ color: palette.destructive }}>{data.error}</div>}
          {!data.enabled && !data.error && <div>Set STT_DEBUG_HYBRID=1 to capture samples.</div>}
          {data.enabled && samples.length === 0 && <div>Waiting for finalized STT turns.</div>}
          {samples.map((sample) => (
            <section
              key={sample.seq}
              style={{
                display: "flex",
                flexDirection: "column",
                gap: space.sm,
                borderTop: `1px solid ${palette.border}`,
                paddingTop: space.md,
              }}
            >
              <div style={{ color: palette.textMuted }}>
                #{sample.seq} · {new Date(sample.at_ms).toLocaleTimeString()} · {sample.audio_ms}ms ·{" "}
                {sample.pcm_bytes} bytes · final {sample.dur_ms}ms
              </div>
              <DebugStats sample={sample} />
              <DebugText label="Stream transcript" value={sample.stream_transcript} />
              <DebugText label="Parakeet transcript" value={sample.parakeet_transcript} />
              <div style={{ display: "flex", flexDirection: "column", gap: space.xs }}>
                <strong>Original audio submitted to Parakeet</strong>
                <audio controls src={`data:audio/wav;base64,${sample.audio_wav_b64}`} style={{ width: "100%" }} />
              </div>
            </section>
          ))}
        </div>
      </details>
    </aside>
  );
}

function DebugStats({ sample }: { sample: DebugSample }) {
  if (sample.audio_peak === undefined || sample.audio_rms === undefined) return null;
  return (
    <div style={{ color: palette.textMuted }}>
      peak {sample.audio_peak} · rms {sample.audio_rms} · clip {sample.audio_clip_pct ?? 0}% · lead{" "}
      {sample.leading_silence_ms ?? 0}ms · tail {sample.trailing_silence_ms ?? 0}ms
    </div>
  );
}

function DebugText({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.xs }}>
      <strong>{label}</strong>
      <div style={{ whiteSpace: "pre-wrap", color: value ? palette.textBody : palette.textMuted }}>
        {value || "(empty)"}
      </div>
    </div>
  );
}
