# RepoSentry — Agent Instructions

> Every agent working on this repository MUST read the following documents
> before starting any work:

1. **[docs/OPERATING_CONTRACT.md](docs/OPERATING_CONTRACT.md)** — Ownership map,
   shared rules, log format, contract-change process, and gate checklist process.
   This is the binding operating agreement between agents.

2. **[docs/INITIAL_PLAN.md](docs/INITIAL_PLAN.md)** — The frozen design plan.
   This file is never edited. Plan changes are recorded only in
   [docs/DECISIONS.md](docs/DECISIONS.md).

3. **[docs/GATES.md](docs/GATES.md)** — Phase gate checklists with verification
   methods. No gate may be claimed passed without recorded evidence.

4. **[docs/DECISIONS.md](docs/DECISIONS.md)** — Decision log. Every dependency,
   architecture, and contract decision is recorded here with evidence.

## Agent Assignments

- **Agent A ("Spine"):** Deterministic analysis — contracts, ingest, parse,
  guards, detectors, scoring, mutation engine, CLI, packaging.
  Log: [logs/agent-a.md](logs/agent-a.md)

- **Agent B ("Intelligence"):** Model-facing layers — retrieval, gateway, judge,
  verifier, observability, retrieval benchmarks, arm adapters.
  Log: [logs/agent-b.md](logs/agent-b.md)

## Critical Rules (summary; full rules in the operating contract)

- Never execute scanned code. Analysis is static only.
- No secrets in repo, logs, prompts, or traces.
- No destructive git. Never modify `docs/INITIAL_PLAN.md`.
- Verify every dependency. Pin versions.
- Log all decisions with evidence.
- Gates require recorded evidence from clean environments.
