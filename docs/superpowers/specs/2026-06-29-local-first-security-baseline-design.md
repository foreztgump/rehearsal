---
title: Local-First Security Baseline Design
date: 2026-06-29
status: draft for user review
scope: public source access readiness
research: verified 2026-06-29 against current OSV-Scanner, Grype, npm, and pip-audit docs plus the live repo
---

# Local-First Security Baseline Design

## Summary

Adept will be public as source code, not as downloadable binaries or published Docker images.
The trust baseline should therefore prove three things locally:

1. Source is clean enough to publish.
2. Dependencies are known and scanned for current public vulnerabilities.
3. Non-source artifacts are traceable to upstream sources.

Chosen path: **one local security script plus one provenance document**.

- Add `scripts/security-check.sh`.
- Add `SECURITY_PROVENANCE.md`.
- Keep CI, release signing, Cosign, SLSA, VirusTotal, and published image scanning out of scope.

This is intentionally local-first: a reviewer can clone the repo and run the same checks before trusting it.

## Goals

- Provide one command for pre-publication security checks.
- Scan npm and Python dependencies with multiple advisory sources.
- Generate a source SBOM and scan it.
- Make OSV-Scanner, Syft, and Grype part of the required dependency evidence.
- Record provenance for vendored JS/WASM, model artifacts, Docker images, and downloaded tarballs.
- Avoid uploading private/local artifacts to third-party malware services.
- Keep the result understandable for users who are not supply-chain specialists.

## Non-Goals

- No public downloadable release workflow.
- No published Docker image signing.
- No GitHub Actions implementation yet.
- No VirusTotal automation.
- No full SLSA compliance program.
- No attempt to prove that all dependencies are non-malicious.

## Meaning of "Clean"

"Clean" means:

- No known high or critical vulnerabilities in production dependencies at scan time.
- No detected secrets in tracked source.
- No suspicious source patterns that match the project-owned denylist.
- Non-source artifacts have a documented upstream and checksum or digest where practical.

It does **not** mean scanners proved the absence of malicious code. The honest claim is:

> This repo has reproducible dependency inputs, current vulnerability scans, and traceable non-source artifacts.

## Tool Roles

| Tool | Required | Purpose |
| --- | --- | --- |
| `npm ci` | yes | Clean install from `web/package-lock.json`. |
| `npm audit --omit=dev` | yes | npm advisory scan for production web dependencies. |
| `npm audit signatures` | yes | Verify npm registry signatures and provenance attestations. |
| `uvx pip-audit` | yes | Python advisory scan against resolved project requirements. |
| `osv-scanner -r .` | yes | OSV source and lockfile vulnerability scan. |
| `syft .` | yes | Generate a source SBOM. |
| `grype sbom:<sbom>` | yes | Scan the generated SBOM for vulnerabilities. |
| `gitleaks` | yes | Secret scan for tracked source. |
| `shellcheck` | optional | Shell quality/security lint for scripts when installed. |

Required tools fail the script if missing. Optional tools warn and continue.

## Dependency Input Reality

The web app already has `web/package-lock.json`, so the npm side can be checked against exact
resolved packages and registry integrity metadata.

Python currently uses human-authored requirement ranges:

- `agent/requirements.txt`
- `stt/requirements.txt`
- `stt/requirements-cpu.txt`
- `requirements-dev.txt`

The first local baseline audits the Python versions resolved at scan time. That is useful
vulnerability evidence, but it is not the same as hash-locked Python installs. The provenance
document must call this out as a known pinning gap.

If exact Python artifact traceability becomes required, the next smallest step is per-runtime
hash lockfiles generated from the current requirement files with `uv pip compile --generate-hashes`.
Do not add that until the local baseline exists and the remaining gap matters.

## Local Script

`scripts/security-check.sh` is the local orchestrator.

Default command:

```bash
./scripts/security-check.sh
```

Behavior:

1. Run from repo root.
2. Create `security/reports/` if missing.
3. Verify required commands exist: `npm`, `uvx`, `osv-scanner`, `syft`, `grype`, `gitleaks`.
4. Run npm checks in `web/`.
5. Run Python dependency audit with Python 3.12 through `uvx`.
6. Run OSV-Scanner recursively on the repo.
7. Generate `security/reports/source.cdx.json` with Syft.
8. Scan that SBOM with Grype.
9. Run Gitleaks against the repo.
10. Run ShellCheck if installed.
11. Run a small project-owned suspicious-pattern scan.
12. Print a compact pass/fail summary.

The script should be boring Bash: `set -euo pipefail`, small helper functions, no framework.

## Dependency Policy

The script fails on:

- Any high or critical production npm vulnerability.
- Any high or critical Python vulnerability.
- Any high or critical OSV finding.
- Any high or critical Grype finding.
- Any verified secret finding.
- Missing required scanners.

Moderate findings do not block publication by default, but they must be listed in the final summary.
The current known example is the moderate `postcss` advisory surfaced through `next`; it should be fixed when a safe `next` update is available.

## Provenance Document

`SECURITY_PROVENANCE.md` is committed source evidence, not generated output.

It tracks:

| Artifact class | Examples |
| --- | --- |
| Docker images | `livekit/livekit-server:v1.10.1`, `ollama/ollama:0.30.10`, `node:24-bookworm-slim`, `nvcr.io/nvidia/nemo:25.11`, Kokoro images. |
| Vendored browser assets | `web/public/vendor/three/*`, `web/public/vendor/talkinghead/*`, Draco WASM. |
| Model downloads | Hugging Face STT models, Ollama model ladders. |
| Tarballs | Parakeet sherpa-onnx bundle. |
| Local scripts | Installer and model-fetch scripts that download artifacts. |

Each row records:

- Artifact path or name.
- Upstream URL.
- Version, tag, revision, or commit.
- Checksum or digest status.
- License/status if known.
- Notes for anything not fully pinned.

The Parakeet bundle already has a sha256 in `stt/fetch_parakeet_onnx.sh`; the doc should cite it rather than duplicate logic.

## Generated Outputs

Generated reports live under `security/reports/`.

Expected files:

- `source.cdx.json`
- `npm-audit.json`
- `pip-audit.json`
- `osv-scanner.json`
- `grype-source.json`
- `gitleaks.json`

These files are local evidence and should not be committed by default.

## Exclusions

The local scanner should not scan:

- `.env`
- local cert/key material
- `web/node_modules`
- `web/.next`
- Python caches
- generated `security/reports`
- `.planning` historical artifacts unless explicitly requested

The repo already ignores `.env`, cert PEMs, `node_modules`, and `.next`; the script should still exclude them defensively.

## Future Work

Only add these when the distribution model changes:

- GitHub Actions required checks.
- Signed git tags.
- GitHub artifact attestations.
- Cosign for published images.
- VirusTotal checks for public release artifacts.
- Full SLSA mapping.

## Acceptance Criteria

- `./scripts/security-check.sh` exists and runs locally from repo root.
- Missing required scanners produce clear install guidance.
- npm, Python, OSV, Syft, Grype, and Gitleaks checks all run.
- `security/reports/source.cdx.json` is generated.
- High and critical dependency findings fail the script.
- Moderate findings are summarized without blocking.
- `SECURITY_PROVENANCE.md` documents current non-source artifacts and known pinning gaps.
- README has a short public-trust section pointing to the script and provenance doc.
