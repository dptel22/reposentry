# RepoSentry P0 Adversarial Code Review & Security Audit

> **Reviewer:** RepoSentry Security Architecture Team (adversarial audit on behalf of @dptel22)  
> **Date:** 2026-10-11  
> **Target:** Milestone A1 & A2 (C0 Contracts, Config, CLI, Test Harness)  
> **Scope:** `src/reposentry/contracts/models.py`, `src/reposentry/config/settings.py`, `src/reposentry/cli/main.py`  
> **Severity Scale:** CRITICAL | HIGH | MEDIUM | LOW

---

## Executive Summary

An adversarial audit was conducted against the initial foundational codebase (Phase P0, Milestones A1 & A2). The codebase establishes typed, versioned data contracts (Pydantic V2), layered configuration, and a single CLI entry point. 

While the baseline introduces strict validation (`extra="forbid"`, `frozen=True`, and basic path checking), rigorous adversarial analysis revealed **5 critical/high-severity vulnerabilities and attack vectors** that an attacker controlling an untrusted repository could exploit to escape sandboxes, cause denial-of-service, leak secrets in trace logs, or corrupt deterministic verification.

---

## Detailed Vulnerability Analysis

### 1. [HIGH] Windows Namespace & Path Traversal Bypasses in `normalize_and_validate_path`
- **Location:** `src/reposentry/contracts/models.py` (`normalize_and_validate_path`)
- **Attack Vectors:**
  1. **Windows DOS Device Names:** Paths like `NUL`, `CON`, `PRN`, `AUX`, `COM1-9`, `LPT1-9`, or `NUL.py` bypass standard checks and can hang or crash the Windows file system driver during stat/read operations.
  2. **Alternate Data Streams (ADS):** Paths containing `:` (e.g., `app/main.py:hidden_stream`) are not checked, allowing file creation/reading outside regular workspace paths.
  3. **Drive-Relative Paths on Windows:** `PureWindowsPath("/etc/passwd").is_absolute()` evaluates to `False` on Windows because it is considered drive-relative (e.g. `C:\etc\passwd`), completely bypassing `is_absolute()`.
  4. **UNC Network Paths:** Paths starting with `//attacker.com/share` or `\\attacker.com\share` can trigger external SMB authentication attempts, leaking NTLM hashes.
  5. **Trailing Dots & Spaces:** Windows strips trailing dots and spaces (`file.py. ` -> `file.py`), enabling collision and bypass attacks.
- **Remediation:** Implement strict POSIX-only relative path sanitization, explicitly reject `:`, `//`, leading `/` or `\`, Windows reserved device names, and non-printable characters.

---

### 2. [HIGH] Secret Leakage via Plaintext `str` in `RepoSentryConfig`
- **Location:** `src/reposentry/config/settings.py` (`llm_api_key`)
- **Attack Vectors:**
  1. `llm_api_key` is typed as `str | None`. If `config.model_dump()` or `str(config)` is called in telemetry, debugging, or exception handlers, the secret token is emitted in plaintext into logs or `TraceEvent` attributes.
  2. The configuration allows arbitrary environment variable injection without validation of unexpected sensitive tokens.
- **Remediation:**
  - Wrap all secrets in Pydantic's `SecretStr` (`Field(exclude=True)`).
  - Add explicit custom serialization that masks secrets (`********`).
  - Provide strict redaction middleware for any config dumping or logging.

---

### 3. [MEDIUM] Denial of Service via Unbounded Collections and `NaN`/`Infinity` Floats
- **Location:** `src/reposentry/contracts/models.py`
- **Attack Vectors:**
  1. **Unbounded Lists:** `Symbol.parameters`, `Symbol.decorators`, `Route.guards`, `Finding.evidence`, `Coverage.parse_errors`, and `RunManifest.files` do not specify `max_length`. An adversarial AST could extract a Python file with 500,000 generated decorators or parameters, causing memory exhaustion and quadratic slowdowns during `canonical_json` serialization.
  2. **Floats `NaN` / `Infinity`:** Python's standard `float` allows `float('nan')` and `float('inf')`. In `json.dumps`, these produce non-standard JSON literals (`NaN`, `Infinity`) which break strict JSON parsers and violate RFC 8259.
  3. **Non-deterministic Float Hashing:** Floating-point representations can vary across Python builds and platforms, breaking deterministic hashing for `Score` and `Verdict`.
- **Remediation:**
  - Enforce `max_length` constraints on all list and dictionary fields.
  - Forbid `allow_inf_nan=False` in Pydantic float fields.
  - Normalize floating-point numbers to fixed decimal precision (e.g., rounded to 4 decimal places) prior to canonical serialization.

---

### 4. [HIGH] Hostile Code Injection & Unicode Smuggling in AST Symbols
- **Location:** `src/reposentry/contracts/models.py` (`Symbol`, `Route`, `Evidence`)
- **Attack Vectors:**
  1. **Bidirectional (Bidi) Unicode Smuggling:** Unicode control characters like `\u202E` (Right-to-Left Override) can disguise malicious code snippets or route names in UI and reports, leading security analysts or LLM judges to misinterpret hostile logic.
  2. **Zero-Width & Homoglyph Characters:** Invisible characters (`\u200B`, `\uFEFF`) in identifier names can cause collisions in symbol tables and retrieval indexes.
- **Remediation:**
  - Strip or reject all Unicode bidirectional format characters (`Cf` category in `unicodedata`).
  - Enforce strict identifier normalization (`unicodedata.normalize('NFKC', ...)`).

---

### 5. [MEDIUM] CLI Unvalidated Input Handling & Exception Leakage
- **Location:** `src/reposentry/cli/main.py`
- **Attack Vectors:**
  1. The CLI accepts raw `target` and `workspace` paths without verifying permissions, device files, or canonical workspace confinement.
  2. Unhandled exceptions from subprocesses or parsing will dump full filesystem paths into stdout/stderr.
- **Remediation:**
  - Add pre-flight workspace validation for all CLI input paths.
  - Implement a top-level error handler that catches exceptions, logs structured error details, and outputs clean user-facing error messages without disclosing local host paths.

---

## Action Items & Tracking Issues

The findings from this review will be tracked via dedicated GitHub issues:
- **Issue 1:** `[SECURITY/C0] Windows Namespace & Path Traversal Bypasses in Path Normalization (ADS, DOS Devices, UNC)`
- **Issue 2:** `[SECURITY/C0] Insecure Secret Handling: Plaintext SecretStr Leakage in Config Dumps and Logs`
- **Issue 3:** `[ROBUSTNESS/C0] Unbounded Collections and Floats (NaN/Inf) Causing DoS & Non-Deterministic Hashing`
- **Issue 4:** `[SECURITY/C0] Hostile AST / Unicode Smuggling (Bidi RTL, Homoglyphs, Zero-Width) in Extracted Symbols`
- **Issue 5:** `[RELIABILITY/CLI] Unsanitized CLI Path Inputs and Exception Handlers Echoing Hostile Payloads`
