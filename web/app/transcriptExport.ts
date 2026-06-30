// SESS-04: client-side transcript export (txt/md). Pure — no room, no network.
export type TranscriptEntry = { speaker: "You" | "Agent"; text: string; at: number };

function stamp(at: number): string {
  // Local HH:MM:SS — no date (a single session never spans days).
  return new Date(at).toLocaleTimeString([], { hour12: false });
}

export function formatTranscript(entries: TranscriptEntry[], format: "txt" | "md"): string {
  if (format === "md") {
    const head = "# Rehearsal session transcript\n\n";
    return head + entries.map((e) => `- **${e.speaker}** _(${stamp(e.at)})_: ${e.text}`).join("\n") + "\n";
  }
  return entries.map((e) => `[${stamp(e.at)}] ${e.speaker}: ${e.text}`).join("\n") + "\n";
}

// Defer the object-URL release so browsers that fetch the download asynchronously
// (Firefox/Safari) finish reading the blob before it's revoked — revoking on the
// same tick as click() can race the download to an empty file.
const REVOKE_DELAY_MS = 1000;

export function downloadTranscript(text: string, filename: string): void {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS);
  } catch (err) {
    URL.revokeObjectURL(url); // boundary: release immediately if the click never fired
    throw err;
  }
}
