# RepoSentry Decision Log

> **Rule:** Decisions are not locked, but never swap one silently.  
> State the new evidence (source or measurement) in the log BEFORE changing a recorded decision.

---

## Dependencies

### Core & CLI
- **click (`>=8.5.0,<9`)**: Standard composable CLI interface builder. Pinned to major version 8. Verified safe, widely audited, zero unexpected runtime hooks.
- **pydantic (`>=2.14.0,<3`)**: Pydantic V2 for typed, schema-validated contracts (C0), strict mode serialization/deserialization, and validation error reporting.
- **rich (`>=15.0.0,<16`)**: Terminal rendering for CLI outputs, progress, formatted reports and diffs.

### Dev & Test Tooling
- **hatchling (`>=1.27.0`)**: Modern PEP 517/621 build backend with explicit package directory discovery (`src/reposentry`).
- **pytest (`>=9.1.1,<10`)**: Standard test framework with strict marker enforcement (`--strict-markers`).
- **pytest-cov (`>=6.1.0,<7`)**: Test coverage measurement and branch coverage reporting.
- **ruff (`>=0.17.0,<1`)**: High-performance linter and code formatter. Configured with rules `E`, `W`, `F`, `I`, `N`, `UP`, `B`, `S`, `A`, `C4`, `DTZ`, `T20`, `SIM`, `RUF`.
- **mypy (`>=2.4.0,<3`)**: Static type checker configured in strict mode (`strict = true`, `disallow_untyped_defs = true`).

### Security Analysis Tooling
- **bandit[toml] (`>=1.9.4,<2`)**: AST-based static security analyzer for Python, baseline check.
- **semgrep (`>=1.180.0,<2`)**: Fast static analysis for pattern search and regression detection.

---

## Architecture Decisions

- **2026-10-11 — D1: Python version baseline set to >=3.11**
  - **Context:** Requires modern typing features, `typing.Self`, exception groups, and stdlib AST performance improvements.
- **2026-10-11 — D2: CLI Structure (Single Entry Point with Subcommands)**
  - **Context:** Plan §1 review corrections requirement: "One CLI entry point".
  - **Decision:** Command group `reposentry` with subcommands `scan`, `ingest`, `parse`, `version`.
  - **Evidence:** Follows UNIX philosophy while presenting an integrated tool surface.

- **2026-10-12 — D3: Ingest Sandbox Archive & Directory Security Policy (C1)**
  - **Context:** Scanned repositories must be treated as untrusted data input.
  - **Decision:** Materialize repositories into isolated workspaces as pure data. Strip VCS metadata (`.git`, `.svn`) and hooks. Filter vendor (`node_modules`, `vendor`, `.venv`) and binary files. Enforce zip-slip detection, zip bomb compression ratio limits (max 100.0), total size bounds, and deterministic alphabetical file ordering for reproducible `RunManifest` hashing.
  - **Evidence:** Git advisory on untrusted repository execution and OWASP 2025 LLM Security Top 10 recommendations.


---

## Contract Changes

_No contract changes yet. Contracts v0 baseline in progress._


