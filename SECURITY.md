# Security policy

## Supported versions

| Version | Supported |
| --- | --- |
| `0.1.x` | Yes |

## Reporting a vulnerability

If this repository has GitHub private vulnerability reporting enabled, use that
path first. Otherwise, open an issue asking for a private contact method. Do not
post secrets, exploit payloads, private transcripts, or model files in a public
issue.

## Local checks

Run the baseline before release-sensitive changes:

```bash
./scripts/security-check.sh
```

This writes reports to `security/reports/`, which is ignored by git. The baseline
uses npm audit, npm signature checks, pip-audit, OSV-Scanner, Syft, Grype,
Gitleaks, optional ShellCheck, and a small suspicious-pattern scan.

Run the slower package-behavior scan when dependencies change:

```bash
./scripts/guarddog-check.sh
```

See `SECURITY_PROVENANCE.md` for image, model, and vendored asset provenance.
