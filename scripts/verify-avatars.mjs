#!/usr/bin/env node
// Verify every vendored avatar GLB is TalkingHead-compatible.
//
// The web avatar (web/app/AvatarStage.tsx, TalkingHead 1.7) drives the mouth via the
// 15 Oculus visemes and expression via ARKit-52 blendshapes. A GLB missing those
// renders but lip-sync/mood silently break. This checks every file listed in
// AVATAR_CATALOG (web/app/avatarConfig.ts) so an incompatible face can't ship
// unnoticed. Run it after adding a face:
//
//   node scripts/verify-avatars.mjs
//
// Sourcing faces (Ready Player Me shut down its public API on 2026-01-31): the
// vendored faces come from the met4citizen/TalkingHead example set (brunette,
// avaturn, avatarsdk) plus the seed cyber-trainer. To add more, drop a
// TalkingHead-compatible GLB (Mixamo rig + ARKit-52 + Oculus-15 visemes) into
// web/public/avatars/, list it in AVATAR_CATALOG, and re-run this check.

import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const AVATAR_DIR = join(HERE, "..", "web", "public", "avatars");
const CATALOG_FILE = join(HERE, "..", "web", "app", "avatarConfig.ts");

// The 15 Oculus visemes AvatarStage drives every frame (viseme_sil is the rest
// shape). A face missing any cannot lip-sync.
const REQUIRED_VISEMES = [
  "viseme_sil", "viseme_PP", "viseme_FF", "viseme_TH", "viseme_DD",
  "viseme_kk", "viseme_CH", "viseme_SS", "viseme_nn", "viseme_RR",
  "viseme_aa", "viseme_E", "viseme_I", "viseme_O", "viseme_U",
];

// A sample of the ARKit-52 blendshapes TalkingHead needs for mood/brows/blink.
const REQUIRED_ARKIT = [
  "jawOpen", "mouthSmileLeft", "mouthSmileRight",
  "browInnerUp", "browOuterUpLeft", "browOuterUpRight", "eyeBlinkLeft",
];

const GLB_MAGIC = 0x46546c67; // "glTF" little-endian
const GLB_JSON_HEADER_BYTES = 20; // 12-byte GLB header + 8-byte chunk header

// AvatarStage wires only the Draco decoder (dracoEnabled + dracoDecoderPath). A GLB
// compressed with meshopt (EXT_meshopt_compression) needs setMeshoptDecoder, which
// is NOT wired, so TalkingHead throws "setMeshoptDecoder must be called before
// loading compressed files" at load. Reject it here rather than let it 500 in the UI.
const UNSUPPORTED_EXTENSIONS = ["EXT_meshopt_compression"];

// Parse the embedded JSON chunk of a GLB. Throws on a non-GLB / truncated file so a
// corrupt asset is caught, not passed as compatible.
function parseGlbJson(buf) {
  if (buf.length < GLB_JSON_HEADER_BYTES || buf.readUInt32LE(0) !== GLB_MAGIC) {
    throw new Error("not a GLB file (bad magic)");
  }
  const jsonLength = buf.readUInt32LE(12);
  return JSON.parse(buf.slice(GLB_JSON_HEADER_BYTES, GLB_JSON_HEADER_BYTES + jsonLength).toString("utf8"));
}

// The morph-target names the mesh carries (drives lip-sync + expression).
function morphNames(json) {
  const names = new Set();
  for (const mesh of json.meshes ?? []) {
    for (const name of mesh.extras?.targetNames ?? []) names.add(name);
  }
  return names;
}

// Pull the "/avatars/<file>.glb" paths straight out of AVATAR_CATALOG so this check
// stays in lockstep with what the app actually loads (no second list to drift).
async function catalogGlbFiles() {
  const src = await readFile(CATALOG_FILE, "utf8");
  const start = src.indexOf("AVATAR_CATALOG");
  const body = start === -1 ? src : src.slice(start);
  return [...body.matchAll(/glb:\s*"\/avatars\/([^"]+)"/g)].map((m) => m[1]);
}

async function verifyFile(file) {
  const path = join(AVATAR_DIR, file);
  if (!existsSync(path)) return { file, ok: false, detail: "missing from web/public/avatars/" };
  try {
    const json = parseGlbJson(await readFile(path));
    const badExt = (json.extensionsRequired ?? []).filter((e) => UNSUPPORTED_EXTENSIONS.includes(e));
    if (badExt.length > 0) return { file, ok: false, detail: `unsupported compression: ${badExt.join(", ")}` };
    const names = morphNames(json);
    const missing = [...REQUIRED_VISEMES, ...REQUIRED_ARKIT].filter((n) => !names.has(n));
    if (missing.length > 0) return { file, ok: false, detail: `missing ${missing.join(", ")}` };
    return { file, ok: true, detail: `${names.size} morphs` };
  } catch (err) {
    return { file, ok: false, detail: err.message };
  }
}

async function main() {
  const files = await catalogGlbFiles();
  if (files.length === 0) {
    console.error("No GLB paths found in AVATAR_CATALOG — nothing to verify.");
    process.exitCode = 1;
    return;
  }
  const results = await Promise.all(files.map(verifyFile));
  for (const r of results) {
    console.log(`[${r.ok ? "OK" : "FAIL"}] ${r.file} — ${r.detail}`);
  }
  const failed = results.filter((r) => !r.ok);
  if (failed.length > 0) {
    console.error(`\n${failed.length} avatar(s) failed the TalkingHead compatibility check.`);
    process.exitCode = 1;
  }
}

main().catch((err) => {
  console.error("verify-avatars failed:", err);
  process.exitCode = 1;
});
