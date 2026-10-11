# RepoSentry Operating Contract

> **Effective:** 2026-10-11  
> **Owner:** Agent A (Spine) maintains this document.  
> **Reference:** See [docs/INITIAL_PLAN.md](./INITIAL_PLAN.md) for the frozen design plan.

---

## A. Ownership Map

### Agent A — "Spine" (Deterministic Analysis)

| Component | Description | Paths Owned |
|---|---|---|
| C0 | Contracts and config (owner) | `src/reposentry/contracts/`, `src/reposentry/config/` |
| C1 | Ingest and workspace sandbox | `src/reposentry/ingest/` |
| C2 | Parse | `src/reposentry/parse/` |
| C3 | Guard resolver | `src/reposentry/guards/` |
| C4 | Detectors | `src/reposentry/detectors/` |
| C9 | Scoring | `src/reposentry/scoring/` |
| C10 (parts) | Mutation engine, metrics, ablation runner | `src/reposentry/benchmark/mutations/`, `src/reposentry/benchmark/metrics/`, `src/reposentry/benchmark/ablation/` |
| CLI | CLI entry point | `src/reposentry/cli/`, `src/reposentry/__main__.py` |
| Packaging | Build config, tooling | `pyproject.toml`, `Makefile`, `.flake8`, `mypy.ini` or equivalent |
| Tests (own) | Tests for all owned components | `tests/test_contracts/`, `tests/test_ingest/`, `tests/test_parse/`, `tests/test_guards/`, `tests/test_detectors/`, `tests/test_scoring/`, `tests/test_benchmark/mutations/`, `tests/test_benchmark/metrics/`, `tests/test_benchmark/ablation/`, `tests/test_cli/` |
| Fixtures | Fixture apps for parse/guard/detector testing | `fixtures/` |
| Golden files | Golden test outputs | `tests/golden/` |

### Agent B — "Intelligence" (Model-Facing)

| Component | Description | Paths Owned |
|---|---|---|
| C5 | Index and retrieval | `src/reposentry/retrieval/` |
| C6 | LLM gateway | `src/reposentry/gateway/` |
| C7 | Judge pipeline and agent | `src/reposentry/judge/` |
| C8 | Evidence verifier | `src/reposentry/verifier/` |
| C12 | Observability and operations | `src/reposentry/observability/` |
| C10 (parts) | Retrieval benchmark generation, arm adapters | `src/reposentry/benchmark/retrieval/`, `src/reposentry/benchmark/arms/` |
| Tests (own) | Tests for all owned components | `tests/test_retrieval/`, `tests/test_gateway/`, `tests/test_judge/`, `tests/test_verifier/`, `tests/test_observability/`, `tests/test_benchmark/retrieval/`, `tests/test_benchmark/arms/` |
| Recordings | LLM replay recordings | `tests/recordings/` |

### Shared Resources (change only via Contract Change Request)

| Resource | Description | Change Process |
|---|---|---|
| `src/reposentry/contracts/` | Typed data definitions (C0) | CCR required; Agent A decides |
| `docs/` | Documentation and decisions | Append-only logs; contract changes via CCR |
| `pyproject.toml` | Build/dependency config | CCR if Agent B needs a new dependency |
| Config schema | Layered config definitions | CCR required |

---

## B. Shared Rules

1. **Never execute scanned or fixture code.** Analysis is static only.
2. **No secrets in the repo, logs, prompts, or traces.** Secrets come from environment variables only.
3. **No destructive git operations.** No `reset --hard`, `force-push`, `checkout` of uncommitted work, or `stash`. Normal commits only. Do not modify `docs/INITIAL_PLAN.md`.
4. **Verify every dependency** exists and is the intended package (typosquatting and hallucinated package names are a known risk). Pin versions. Record each verified version and its source in `docs/DECISIONS.md`.
5. **Research online** where the plan says "verify" or where a fact may have changed. Cite sources in the log. Mark anything not verified as "NOT VERIFIED".
6. **Decisions are not locked**, but never swap one silently. State the new evidence (source or measurement) in the log BEFORE changing a recorded decision.
7. **Each phase gate requires:** tests green from a CLEAN environment, adversarial self-review done and logged, evidence recorded in `docs/GATES.md`.
8. **Do not claim a gate passed** without recorded evidence. Unknown or untested means "not done".
9. **Merging to main:** each agent may merge its own gated work into `main`, touching only paths it owns, after logging the gate evidence. Tag each gate (e.g., `gate-p0`). Pull `main` before starting each work block.
10. **Blocker rule:** stop and write a blocker note (in your log) only for: missing credentials, a destructive or irreversible action, a license problem, a contradiction inside the plan, or a gate you cannot verify. Everything else: decide, log, continue.

---

## C. Agent Log Format and Rules

Each agent keeps an append-only log in its own file:
- Agent A: `logs/agent-a.md`
- Agent B: `logs/agent-b.md`

### Commit discipline

After EVERY work commit, make a separate small commit that adds one log entry citing the work commit's hash. Never edit or delete past entries; corrections are new entries marked "Correction to entry N". At the end of every work session add an END-OF-SESSION entry.

### Entry format

Each entry MUST contain these fields:

```
## Entry N — YYYY-MM-DDTHH:MM:SSZ — Agent [A|B] — Phase P[N] — Component C[N]

### Commit(s)
- `<hash>` — <commit message>

### What changed
- Files and behaviors, in plain language.

### Why
- Which plan item or gate this serves.

### Decisions
For EACH decision:
- **Decision:** <what was decided>
- **Alternatives considered:** <list>
- **Evidence:** <source link or measurement>
- **Why chosen:** <reasoning>
- **Reversibility:** <how reversible>
- **Revisit when:** <trigger>

### Plan deviations
- Explicit list, or "none".

### Tests
- What was added or changed
- Exact commands run
- Results
- Whether the run was from a clean environment

### Adversarial self-review
- Attacks and failure cases considered
- Outcomes

### Assumptions and NOT VERIFIED items
- List all.

### Risks and open questions
- List all.

### Next step
- What comes next.
```

### END-OF-SESSION entries additionally include:

```
### Gate status table
| Gate | Status | Evidence |
|---|---|---|

### Blockers
- List all, or "none".

### What the other agent needs from you
- List all, or "nothing pending".

### What you would do next
- Ordered list.
```

---

## D. Contract Change Process

Changes to shared files (contracts, config schema, tooling config) are made ONLY via a Contract Change Request (CCR).

### Process:

1. The requesting agent writes `docs/contract-changes/CCR-NNN.md` with:
   - **Requestor:** Agent A or B
   - **Date:** UTC timestamp
   - **Affected files:** list of paths
   - **Current behavior:** what exists now
   - **Proposed change:** what should change
   - **Rationale:** why, with evidence
   - **Impact:** what breaks or needs updating
   - **Tests affected:** list

2. **Agent A decides** (as contract owner) and records the decision in the CCR file with:
   - **Decision:** accepted / rejected / modified
   - **Reasoning:** why
   - **Effective from commit:** hash

3. The decision is logged in `docs/DECISIONS.md` and the acting agent's log.

4. The change is implemented and tests are updated in the same commit or commit sequence.

---

## E. Gate Checklist Process

Gates are defined in `docs/GATES.md`. A gate is "passed" only when:

1. All checklist items have recorded evidence (test output, commit hash, screenshot, or measurement).
2. Tests are green from a CLEAN environment (fresh venv, no cached state).
3. Adversarial self-review is done and logged in the agent's log.
4. Evidence is recorded in `docs/GATES.md` under the specific gate.
5. The gate commit is tagged (e.g., `gate-p0`).
6. The gated work is merged to `main`.

No agent may claim a gate passed without completing ALL of the above.
