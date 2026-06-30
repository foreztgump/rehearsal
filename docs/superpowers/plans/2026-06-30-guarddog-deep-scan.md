# GuardDog Deep Scan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional local GuardDog supply-chain scan for malicious-package signals without slowing the default security gate.

**Architecture:** Create a standalone `scripts/guarddog-check.sh` that scans known Python manifests and selected npm direct dependencies, writes JSON reports under `security/reports/guarddog/`, and applies a tiny fail/warn policy. Keep `scripts/security-check.sh` unchanged.

**Tech Stack:** Bash, `uvx --from guarddog guarddog`, existing shell test harness style.

---

### Task 1: GuardDog Harness

**Files:**
- Create: `scripts/test_guarddog_check.sh`

- [ ] **Step 1: Write tests for missing tool, malicious finding, and clean report**

Create a shell harness with path shims for `uvx`, `timeout`, and `python3`. The malicious fixture must include a fail-rule finding such as `threat-network-exfiltration`. The clean fixture must exit 0 and write report files.

- [ ] **Step 2: Run test to verify it fails**

Run: `./scripts/test_guarddog_check.sh`

Expected: fails because `scripts/guarddog-check.sh` does not exist.

### Task 2: GuardDog Script

**Files:**
- Create: `scripts/guarddog-check.sh`

- [ ] **Step 1: Implement minimal script**

The script must:
- require `uvx`, `timeout`, and `python3`
- scan `agent/requirements.txt`, `stt/requirements.txt`, and `stt/requirements-cpu.txt`
- scan direct npm dependencies from `web/package.json`
- write JSON reports to `security/reports/guarddog/`
- fail on high-confidence malicious rule findings
- warn on capability/noisy findings, scanner errors, and timeouts

- [ ] **Step 2: Run harness**

Run: `./scripts/test_guarddog_check.sh`

Expected: all harness checks pass.

### Task 3: Docs

**Files:**
- Modify: `README.md`
- Modify: `SECURITY_PROVENANCE.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Document optional GuardDog usage**

Mention `./scripts/guarddog-check.sh` as the optional deep supply-chain scan and state that it can be slow/noisy.

- [ ] **Step 2: Verify**

Run:
- `./scripts/test_guarddog_check.sh`
- `./scripts/test_security_check.sh`

Expected: both pass.
