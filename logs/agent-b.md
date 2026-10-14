# RepoSentry Agent B Log (Intelligence)

> **Rules:** Append-only. Never edit or delete past entries.  
> Corrections are new entries marked "Correction to entry N".  
> See [docs/OPERATING_CONTRACT.md](../docs/OPERATING_CONTRACT.md) §C for format.

---

## Entry 1 — 2026-10-11T12:42:35Z — Agent B — Phase P3 — Component C6, C8

### Commit(s)
- `8895857` — agent-b: C6 LLM gateway (record/replay/live, budgets, kill switch, scrubbing) and C8 evidence verifier with unit+adversarial tests

### What changed
- `src/reposentry/gateway/`: provider-agnostic LLM gateway with schema-validated output, record/replay/live modes, cache keyed on (model, prompt_version, scrubbed bundle), budget enforcement (calls, tokens in/out, cost), kill switch with non-LLM fallback, and secret scrubbing before any provider call.
- `src/reposentry/verifier/`: evidence verifier with citation path confinement, range+text matching with newline/whitespace normalization, and DOWNGRADED statuses with reason codes.
- `tests/test_gateway/`, `tests/test_verifier/`: unit + adversarial suites; gateway fixtures run fully offline (socket creation is monkeypatched to raise).
- `.gitignore`: ignore `.pytest-tmp/`.

### Why
- Plan items P3.1–P3.13 (gateway + verifier portion of Gate P3).

### Decisions
- **Decision:** Mark Gate P3 as partial (tag `gate-p3-partial`); do not merge to main — the orchestrator merges.
  - **Alternatives considered:** full `gate-p3` tag; no tag.
  - **Evidence:** ask instructions; suite green but judge/scoring portions of P3 not yet built and clean-env (fresh venv) run not done.
  - **Why chosen:** honest partial evidence per contract rules 7–8.
  - **Reversibility:** trivially re-tag later.
  - **Revisit when:** judge + scoring complete and fresh-venv run green.
- **Decision:** Keep the known budget-charging bug as xfail rather than silently patching gateway.py in the same breath as evidence recording.
  - **Alternatives considered:** fix immediately in this commit.
  - **Evidence:** test_gateway_adversarial.py TestRunawayLoop::test_budget_cap_ends_the_runaway_loop (CONFIRMED BUG: failed schema-validation attempts are never charged to BudgetState).
  - **Why chosen:** this session's scope is gate evidence + commits; the bug is bounded (repair_retries still caps the loop) and documented.
  - **Reversibility:** fix in next work commit.
  - **Revisit when:** next gateway work block.

### Plan deviations
- none (merging deferred to main agent per orchestrator instruction; contract rule 9 allows self-merge but instruction supersedes here).

### Tests
- Added: full gateway + verifier unit/adversarial suites (in work commit `8895857`).
- Commands run (from workspace root, shared `.venv`):
  - `.venv/Scripts/python.exe -m pytest reposentry-agent-b/tests/test_gateway -q --tb=short --basetemp=reposentry-agent-b/.pytest-tmp -k "replay or cache"` → **11 passed, 42 deselected in 0.03s** (offline, no API key; `no_network` fixture blocks socket creation — tests/test_gateway/conftest.py:71-76; FakeModel is scripted in-process, tests/test_gateway/conftest.py:22).
  - `.venv/Scripts/python.exe -m pytest reposentry-agent-b/tests -q --tb=short --basetemp=reposentry-agent-b/.pytest-tmp` → **99 passed, 1 skipped, 1 xfailed in 0.30s** (skip: symlink creation not permitted on this platform; xfail: CONFIRMED budget-charging bug above).
- Clean environment: NOT a fresh venv — shared workspace `.venv`. Fresh-clone run still pending (P3.12 partial).

### Adversarial self-review
- Considered: gateway accepting prose/extra-field/injection-laden model output (all rejected or treated as data — TestProseOutput/TestExtraFields/TestInjectedOutput green); oversize multibyte output counted in bytes (green); provider outage exhaustion → fallback (green); runaway schema-violation loop → bounded, but budget cap on *failed validations* confirmed broken (xfail, documented above); verifier path escapes via `..`, absolute paths, symlinks, junctions (all rejected; symlink case skipped on platform); CRLF/CR/tabs/unicode normalization mismatches (green). Removed stray `tests/test_verifier/.pytest_tmp/` artifacts before committing so no scratch state entered the repo.
- Outcome: no unfixed issue beyond the documented xfail bug.

### Assumptions and NOT VERIFIED items
- NOT VERIFIED: tests from a fresh venv / fresh clone (clean-environment run pending).
- NOT VERIFIED: behavior against a real LLM provider (FakeModel only; by design offline).
- Assumed: `nul` untracked file at repo root is a Windows artifact, intentionally left alone.

### Risks and open questions
- Budget not charged on schema-validation failure (xfail bug) — fix next.
- Windows symlink test skipped; POSIX CI run should cover it.

### Next step
- Fix budget-charging bug; then C7 judge pipeline for the remainder of Gate P3.

---

## Entry 2 — 2026-10-11T12:55:00Z — Agent B — Adversarial Review & Issue Filing

### Commit(s)
- `674f31b` — docs: add adversarial code review report and update gitignore patterns

### What changed
- Completed thorough adversarial code review with maximum scrutiny across Agent B's components (C6 Gateway, C8 Verifier, C12 Observability).
- Documented findings in `reviews/ADVERSARIAL_REVIEW_AGENT_B.md`:
  - Finding 1 [CRITICAL]: Uncharged token consumption and financial exhaustion during schema validation retries.
  - Finding 2 [HIGH]: Second-order prompt injection via unsanitized `repair_error` feedback.
  - Finding 3 [HIGH]: Memory exhaustion / DoS via unbounded file reading in evidence verifier.
  - Finding 4 [HIGH]: Replay cache poisoning due to missing cryptographic signatures on recording store.
  - Finding 5 [MEDIUM]: Windows DOS device hang (CON/PRN) & path confinement gaps in verifier.
  - Finding 6 [HIGH]: Incomplete secret pattern coverage in `redact.py` permitting credential leakage.
- Created GitHub issues on `dptel22/reposentry` on behalf of user:
  - Issue #6: `[SECURITY/C6] Uncharged Token Consumption and Financial Exhaustion Bug in Schema Validation Retry`
  - Issue #7: `[SECURITY/C6] Second-Order Prompt Injection via Unsanitized repair_error Feedback Loop`
  - Issue #8: `[ROBUSTNESS/C8] Memory Exhaustion / DoS via Unbounded File Reading in Evidence Verifier`
  - Issue #9: `[SECURITY/C6] Replay Cache Poisoning: Missing Cryptographic Integrity on Recording Store`
  - Issue #10: `[SECURITY/C8] Windows DOS Device Hang (CON/PRN) & Path Confinement Gaps in Verifier`
  - Issue #11: `[PRIVACY/C12] Insufficient Secret Redaction in redact.py Permitting Token Leakage`
- Updated `reviews/README.md`.
- Cleaned up Windows device file artifact `nul` and enhanced `.gitignore` to maintain clean working tree.

### Why
- User requested adversarial code review with maximum scrutiny and filing of tracking issues on GitHub for Agent B workspace.

### Next step
- Begin remediation of issues #6 through #11 on `agent-b/work`.

---

## Entry 3 — 2026-10-12T16:17:29Z — Agent B — Phase P3 — Components C6, C8, C12

### Commit(s)
- No commit created; requested fixes are present as working-tree changes for review.

### What changed
- C6 now accounts for usage/cost immediately after every provider response, including schema-invalid responses, and stops retrying when any configured budget cap is reached.
- C6 repair feedback sanitizes, redacts, flattens, and truncates exception details before returning them as explicitly marked untrusted diagnostic data.
- Filesystem replay recordings now use HMAC-SHA256 signatures bound to the request cache key. Unsigned/tampered records fail closed. A random local 256-bit key is generated outside cassette files; `.replay-hmac-key` is ignored by Git. See decision D-B1-005.
- C8 rejects source files over 5 MiB before unbounded reads, limits reads to 5 MiB + 1 byte, rejects Windows DOS device names, and opens with no-follow plus post-open file identity checks where supported.
- C12 redaction now covers GitHub and Slack tokens, Google API keys, PEM private-key blocks, and common database URI credentials.
- Added regression tests for budget accounting, repair prompt injection, cassette tampering/unsigned records, oversized files, DOS device names, and the new secret patterns.

### Why
- Resolve GitHub issues #6–#11 and close the confirmed C6 budget xfail.

### Decisions
- **Decision:** Charge usage before parsing the provider response, exactly once per transport success.
  - **Alternatives considered:** Charge only on valid responses; charge after handling each exception branch.
  - **Evidence:** Provider usage fields are present on the response regardless of schema validity; prior adversarial test confirmed omitted usage on schema errors.
  - **Why chosen:** Accounting reflects provider-billed calls, while the single common point avoids success/failure divergence.
  - **Reversibility:** Local gateway behavior only.
  - **Revisit when:** Provider adapters expose corrected usage after post-call reconciliation.
- **Decision:** Authenticate persistent recordings with a generated local key and bind signatures to cache keys.
  - **Alternatives considered:** Hard-coded repository key; unsigned digest; mandatory environment configuration.
  - **Evidence:** See D-B1-005 in `docs/DECISIONS.md`.
  - **Why chosen:** No new dependency or hard-coded secret; invalid payloads and cassette relocation fail closed.
  - **Reversibility:** Legacy unsigned cassette files must be regenerated.
  - **Revisit when:** Shared/CI cassette workflows require central key provisioning.

### Plan deviations
- Replay integrity introduces a signed envelope and local key file, so previously stored raw cassette records are intentionally rejected.
- The verifier uses a 5 MiB ceiling as the deterministic resource bound.

### Tests
- Added/updated regression tests in `tests/test_gateway/` and `tests/test_verifier/`.
- `git diff --check` → passed (only Git line-ending notices).
- Python AST parse check across 10 changed Python files → passed.
- Focused pytest command attempted: `.venv/Scripts/python.exe -m pytest tests/test_gateway tests/test_verifier -q --tb=short` → could not run; the workspace venv launcher references a missing `C:\Python314\python.exe`, and pytest is unavailable.
- `uv run` alternative → could not run; uv was denied permission to write its interpreter cache under the restricted user profile.
- Clean environment: not run.

### Adversarial self-review
- Confirmed the retry budget charges invalid and valid outputs exactly once; budget exhaustion blocks subsequent repair calls.
- Confirmed HMAC covers the record payload and cache key; absent/bad signatures and malformed envelopes fail closed; local key is not committed.
- Confirmed verifier rejects oversized inputs before reading beyond the configured ceiling and guards final-component symlink opens where `O_NOFOLLOW` exists.
- Confirmed DOS device filtering handles case, extensions, trailing dots/spaces, and alternate-stream suffixes.
- Confirmed repair diagnostics discard non-ASCII and structural delimiters and are capped at 240 characters.
- Runtime tests remain unverified because no usable pytest environment is available.

### Assumptions and NOT VERIFIED items
- Assumed local cassette directory permissions protect `.replay-hmac-key` from the actor able to alter only cassette artifacts. A workspace owner who can read the key can also re-sign records; callers can inject a separately managed key with `RecordingStore(..., key=...)`.
- NOT VERIFIED: pytest suites and Windows-specific runtime behavior.
- NOT VERIFIED: behavior on filesystems with unusual file identity semantics or without `O_NOFOLLOW`.

### Risks and open questions
- A generated local key is suitable for local tamper detection, but shared/CI replay artifacts should receive a key from protected secret management.
- Unsigned legacy recordings require regeneration.
- Test execution is pending a usable Python/pytest runtime.

### Next step
- Run focused and full tests on a working Python environment; then inspect the complete diff and hand the changes to the next agent for integration.

---

## END-OF-SESSION — 2026-10-12T16:17:29Z — Agent B

### Gate status table
| Gate | Status | Evidence |
|---|---|---|
| P3 | Partial; no gate claim | Targeted tests added but pytest environment unavailable; clean-environment gate not run. |

### Blockers
- Local test execution is blocked because the Python launcher target is missing and `uv` cannot write its interpreter cache under current filesystem permissions.

### What the other agent needs from you
- Changes are uncommitted in `agent-b/work`; run the gateway/verifier suites on a functioning Python environment before merge.
- For shared replay/CI cassettes, provision an HMAC key outside the cassette directory and pass it to `RecordingStore`.

### What you would do next
1. Run focused gateway/verifier tests and the complete suite in a supported clean environment.
2. Review cross-platform verifier behavior, especially Windows file identity checks.
3. Commit the implementation and add the required commit-referencing log entry.

---

## Correction to Entry 3 — 2026-10-12T16:17:29Z — Agent B

- A bundled Python 3.12.14 runtime was found after the initial environment check. Pytest is still unavailable, but a direct stdlib smoke script passed for invalid-response budget charging, repair-feedback sanitization, replay HMAC/tamper rejection, oversized-file rejection, DOS-device path rejection, and GitHub/database-secret redaction.
- The verifier now checks the canonical path and file identity again after opening, closing the parent-path TOCTOU window by rejecting a swapped path that resolves outside the workspace.
- Replay keys can be injected with `RecordingStore(..., key=...)` or `REPOSENTRY_REPLAY_HMAC_KEY` (minimum 32 UTF-8 bytes); the local generated key remains the default for local recordings.
- `git diff --check` passed. Pytest and a clean-environment run remain NOT VERIFIED.

---

## Correction to Entry 3 — 2026-10-12T16:31:19Z — Agent B

- **Replay key security correction:** The earlier locally generated key stored beside cassettes did not protect against an actor who could read the cassette directory. D-B1-006 supersedes the local-key portion of D-B1-005: persistent `RecordingStore` now requires a separately provisioned key via `key=` or `REPOSENTRY_REPLAY_HMAC_KEY`, enforces a 32-byte minimum, and has tests for missing/short keys and cassette relocation. This is fail-closed; memory replay remains keyless.
- **Pytest attempt:** `uv run --no-project --cache-dir .uv-cache --with pytest --python <bundled-python> -- python -m pytest tests/test_gateway tests/test_verifier -q --tb=short` failed because the sandbox cannot resolve `pypi.org` (DNS/network unavailable). The temporary `.uv-cache` created for the attempt was removed.
- Repeated stdlib smoke checks passed after the externally provisioned key change. AST parsing for 10 Python files and `git diff --check` passed.
- Full pytest suites, Windows-native runtime checks, clean-environment gate evidence, commits, and push remain pending.

---

## END-OF-SESSION — 2026-10-12T16:31:19Z — Agent B

### Gate status table
| Gate | Status | Evidence |
|---|---|---|
| P3 | Partial; no gate claim | Smoke checks, AST parse, and diff check passed; pytest could not be installed because network DNS is unavailable; clean environment not run. |

### Blockers
- Pytest execution is blocked by absent pytest and unavailable package index access. Windows-native verification is unavailable on this host context.

### What the other agent needs from you
- Persistent replay now requires a protected 32+ byte key via constructor or `REPOSENTRY_REPLAY_HMAC_KEY`; provision it outside cassette artifacts.
- Working tree contains the issue fixes and regression tests, but full pytest and Windows verification remain pending.

### What you would do next
1. Run `tests/test_gateway` and `tests/test_verifier` in a host with pytest, then the complete suite.
2. Review Windows-native verifier path and descriptor behavior.
3. Commit the fixes and add a separate log commit referencing the implementation commit.


## Entry 4 — 2026-10-12T17:03:53Z — Agent B — Phase P4/P5 — Components C5/C7/C10/C12

### Commit(s)
- Uncommitted working-tree continuation; no commit created.

### What changed
- Added C5 deterministic Python function/class/module chunks with exact line provenance, identifier-aware tokenization, stdlib BM25, optional injected dense embeddings, reciprocal-rank fusion, lexical-only degradation, and retrieval metrics.
- Added C10 retrieval benchmark runner with per-query and aggregate Recall@k, MRR, and nDCG output, plus provisional cumulative A–E adapters.
- Added C7 bounded judge pipeline and read-only agent/tool layer. Tool results are now bounded before they enter agent state; clipped tool text is explicitly non-citable. Added regression coverage for this bound and source-citation handling.
- Added C12 trace-derived operational counters and framework-neutral liveness/readiness helpers.
- Removed the untracked `tmpf6igno5x/app.py` smoke artifact.

### Why
- Continue Agent B ownership items from the frozen plan: C5, C7, C10 retrieval benchmark/arm adapters, and C12. Security fixes for issues #6–#11 were completed in the prior working-tree continuation.

### Decisions
- **Decision:** Bound tool result data at ingestion into the agent loop, preserving exact-source citation status only when text was not clipped.
  - **Alternatives considered:** Bound only the serialized model context later; truncate while constructing evidence without tracking source exactness.
  - **Evidence:** The agent retains tool history across steps, so model-context truncation alone does not bound retained result size; clipped text no longer matches its original source range.
  - **Why chosen:** Enforces a per-result state bound and prevents truncated evidence from being cited as exact source.
  - **Reversibility:** Local C7 behavior/config only.
  - **Revisit when:** A shared tool result contract supplies an equivalent byte-level bound.

### Plan deviations
- Dense retrieval remains behind an injected embedder protocol; the plan-default Jina model is not installed or loaded because packaging is Agent A-owned and the recorded model license is non-commercial. No production/benchmark quality claim is made for dense retrieval.
- Arm A–E mappings remain provisional per D-B1-008; no full ablation was run.

### Tests
- Python AST parse over all source and test Python files: `AST_OK 50`.
- `git diff --check`: passed (Git reported only an LF-to-CRLF notice for `observability/__init__.py`).
- Direct bundled-Python smoke: tool result stayed at or below 512 serialized characters; truncated result was marked non-citable; bounded agent tool→grounded verdict flow passed; one-query retrieval benchmark returned Recall@2=1.0, MRR=1.0, nDCG@2=1.0; adapters A–E each executed one candidate successfully.
- Pytest availability probe: `PYTEST_AVAILABLE False`. No pytest suite was run. No clean-environment run was performed.

### Adversarial self-review
- C7 tool outputs are reduced to JSON-safe scalar fields and capped before retaining in history. Truncation clears `source_exact`, excluding it from citations.
- Candidate ordering is stable and duplicate IDs are rejected in arm adapters.
- Retrieval paths reject absolute and parent traversal paths; oversized chunks are bounded and a single-line split is marked non-citable.
- Dense failures degrade to lexical results with an explicit coverage reason.
- Remaining risk: these are initial implementations with direct smoke evidence only; test assertions have not been executed by pytest.

### Assumptions and NOT VERIFIED items
- NOT VERIFIED: complete pytest suites, cross-platform runtime behavior, and clean-environment setup.
- NOT VERIFIED: Jina model compatibility/quality in this implementation; embedding-model license constraints remain as recorded in D-B1-A.
- NOT VERIFIED: integration with Agent A's future shared ablation runner and C0 contracts.

### Risks and open questions
- The plan requires measured A–E ablation output. The adapter callbacks exist, but shared-runner integration and benchmark measurements remain pending.
- The fixed labeled retrieval benchmark currently has tiny synthetic test data; a representative labeled repository corpus and measured table remain pending.
- Dense embeddings need an approved model/license and packaging CCR before deployment.

### Next step
- Run all Agent B tests in a supported Python/pytest clean environment; then integrate adapters with Agent A's shared C10 runner and generate the labeled retrieval benchmark table.

---

## END-OF-SESSION — 2026-10-12T17:03:53Z — Agent B

### Gate status table
| Gate | Status | Evidence |
|---|---|---|
| P3 | Partial; no gate claim | Prior direct security smoke, AST and diff checks; pytest and clean-environment evidence unavailable. Judge is implemented but its pytest suite remains unrun. |
| P4 | Partial; no gate claim | C5, benchmark runner, and regression tests added; direct synthetic benchmark smoke passed. Dense model, representative corpus/table, pytest, and clean-environment gate remain unverified. |
| P5 | Partial; no gate claim | Bounded agent and A–E adapters plus tests added; direct one-candidate adapter smoke passed. Full ablation, failure-injection/metamorphic suites, pytest, and clean-environment evidence remain pending. |

### Blockers
- Bundled Python has no pytest; package-index DNS/network was unavailable during the earlier attempt to provision pytest. Windows-native checks and clean-environment verification are not available in this session.

### What the other agent needs from you
- The branch has uncommitted Agent B security fixes and C5/C7/C10/C12 continuation files. Persistent replay requires a separately provisioned 32+ byte HMAC key.
- No gate is claimed passed. Do not treat direct smoke checks as pytest or clean-environment evidence.

### What you would do next
1. Run `tests/test_gateway`, `tests/test_verifier`, `tests/test_judge`, `tests/test_retrieval`, and `tests/test_observability` with pytest, followed by the full suite in a fresh environment.
2. Verify Windows DOS-device and file-open behavior on a Windows-native test run.
3. Supply/approve a representative labeled retrieval corpus and integrate with the shared C10 runner to measure full A–E arms.
4. Review, commit, and push only after the requested integration and verification steps are complete.
