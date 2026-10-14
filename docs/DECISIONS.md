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

### D-B1-001 — Embedding model (plan default, not installed in P3)

- **Decision:** Keep plan default `jinaai/jina-code-embeddings-0.5b` for C5. Do **not** install or call it in P3. Do **not** silently switch despite a license concern (see Architecture D-B1-A).
- **Documented usage (Hugging Face model card, fetched 2026-10-11):**
  - Tasks: `nl2code`, `code2code`, `code2nl`, `code2completion`, `qa`.
  - Sentence-Transformers `prompt_name` values: `nl2code_query` (queries) and `nl2code_document` (passages). Confirms the plan's 1.5B-card note for the 0.5B card.
  - Transformers `encode` (when using `trust_remote_code`): `task="nl2code"` with `prompt_name="query"` / `prompt_name="passage"` (older card snippet). Instruction prefixes for nl2code: query `"Find the most relevant code snippet given the following query:\n"`; passage `"Candidate code snippet:\n"`.
  - Pooling: last-token. Compare with cosine similarity after L2 normalize (`F.normalize(..., p=2, dim=1)` in the card's transformers example). Sentence-Transformers `encode(..., normalize_embeddings=False)` by default ([sbert.net encode docs](https://sbert.net/docs/package_reference/sentence_transformer/model.html)); C5 must pass `normalize_embeddings=True` **or** normalize like the card when using transformers, so query/passage comparisons are cosine-ready.
  - Required libraries from the card: `transformers>=4.53.0`, `torch>=2.7.1`; optional Sentence-Transformers interface needs `sentence_transformers>=5.0.0`. FlashAttention2 optional.
- **License:** Hugging Face YAML `license: cc-by-nc-4.0`. CC BY-NC 4.0 allows reproduce/share/adapt for **NonCommercial** purposes only ([legal code](https://creativecommons.org/licenses/by-nc/4.0/legalcode.en) §2(a)(1); NonCommercial = not primarily for commercial advantage or monetary compensation, §1(i)). Jina/Elastic note: CC-BY-NC-4.0 models need a commercial license for commercial use ([jina.ai/models/llms.txt](https://jina.ai/models/llms.txt)). Base model `Qwen/Qwen2.5-Coder-0.5B` is Apache-2.0; that does **not** relicense the Jina weights.
- **Verified package names (PyPI, not installed):** `transformers` (card floor 4.53.0), `torch` (card floor 2.7.1), `sentence-transformers` latest observed `6.1.0` Apache-2.0. Installation deferred to C5 / a CCR because `pyproject.toml` is Agent A owned.
- **Sources:** https://huggingface.co/jinaai/jina-code-embeddings-0.5b ; https://creativecommons.org/licenses/by-nc/4.0/legalcode.en ; https://jina.ai/models/llms.txt ; https://pypi.org/pypi/sentence-transformers/json
- **Date:** 2026-10-11
- **Agent:** B

### D-B1-002 — Lexical retrieval library (C5, not installed in P3)

- **Decision:** Prefer **`bm25s`** (PyPI name `bm25s`, latest observed **0.3.13**, GitHub https://github.com/xhluca/bm25s, author Xing Han Lü) over `rank-bm25` for C5. Identifier-aware tokenization is **ours**, not the library's default splitter.
- **Why:** Plan default is “BM25 with identifier-aware tokens”. `rank-bm25` 0.2.2 (PyPI `rank-bm25`, import `rank_bm25`, Apache-2.0) requires a pre-tokenized `list[list[str]]` and does no analyzer — last release 2022-02-16. `bm25s` is maintained, SciPy-sparse, exposes `bm25s.tokenization.Tokenizer` with a custom `splitter` callable ([tokenizer example](https://github.com/xhluca/bm25s/blob/main/examples/tokenizer_class.py)).
- **Identifier tokenization (to implement in C5, not a third-party tokenizer):** lowercase; split on non-alphanumerics; split `snake_case`; split `CamelCase`/`PascalCase`; keep both the original identifier and subtokens so `getUserId` matches `user` and `id`. Do not use English stopword lists on code. Do not stem.
- **Not installed** until C5 / CCR (packaging owned by Agent A).
- **Sources:** https://pypi.org/pypi/bm25s/json ; https://pypi.org/pypi/rank-bm25/json (0.2.2); https://huggingface.co/blog/xhluca/bm25s
- **Date:** 2026-10-11
- **Agent:** B

### D-B1-003 — Record/replay (C6)

- **Decision:** **Thin in-house replay inside the LLM gateway**, keyed by `(model, prompt_version, input_hash)` plus ordered provider-call slots. Modes: `live`, `record`, `replay`, `strict_replay` (unrecorded call = failure).
- **Alternatives:** (1) VCR.py + `pytest-recording` 0.14.0 (HTTP cassettes; mature; network-block in `none` mode) — https://pypi.org/project/pytest-recording/ ; (2) `pytest-llm-vcr` 0.6.0 (LLM-aware, httpx/SSE; young) — https://pypi.org/project/pytest-llm-vcr .
- **Why in-house:** Plan default; gateway is the only model path including **scripted FakeModel** that never uses HTTP; STRICT semantics are call-level not HTTP-level; cache keys must include prompt version. HTTP VCR would miss fake providers and would record secrets unless carefully filtered. Revisit if a live HTTP provider is added and cassette redaction is proven.
- **Date:** 2026-10-11
- **Agent:** B

### D-B1-004 — Structured output and retries (C6)

- **Decision:** Provider-agnostic gateway: extract a JSON object, validate a **stdlib JSON-Schema subset** (`type`, `properties`, `required`, `additionalProperties: false`, `enum`, `maxLength`, nested object/array), **bounded repair-retry** (default 2) on schema failure, **bounded exponential backoff** on classified transient errors (timeout, 429, 5xx), no retry on permanent 4xx (except 429). No `instructor` / Pydantic / Tenacity dependency for P3.
- **Alternatives:** `instructor` (MIT; patches provider SDKs; Pydantic + Tenacity retries) — https://pypi.org/project/instructor/ — rejected for P3 because it couples to vendor clients and needs CCR deps; schema validation belongs in the gateway so FakeModel and replay share one path.
- **Date:** 2026-10-11
- **Agent:** B

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

### D-B1-A — Embedding license concern (do not silent-switch)

- **Decision:** Keep `jina-code-embeddings-0.5b` as the recorded C5 default. **Do not use it for commercial/production claims** until a commercial waiver exists or a decision records a switch. Competition/research use may be NonCommercial — **NOT VERIFIED** for Avishkar FET.
- **Alternatives (not adopted):** `Qwen/Qwen3-Embedding-0.6B` Apache-2.0, instruction-aware, code-retrieval listed on the model card (https://huggingface.co/Qwen/Qwen3-Embedding-0.6B); Jina commercial license via Elastic sales ([llms.txt](https://jina.ai/models/llms.txt)).
- **Revisit when:** legal/competition guidance arrives; retrieval benchmark exists; C5 implementation starts (after `gate-p1`).
- **Date:** 2026-10-11
- **Agent:** B

### D-B1-B — C6/C8/C12 local types until contracts-v0

- **Decision:** Implement C6/C8/C12 with **local dataclasses** in Agent B paths. Do not edit `src/reposentry/contracts/`. Map onto C0 after Agent A tags `contracts-v0`.
- **Date:** 2026-10-11
- **Agent:** B

---

## Contract Changes

_Contract change decisions will be referenced here._

### D-B1-005 — Replay recording integrity and local signing key

- **Decision:** Authenticate each filesystem replay record with HMAC-SHA256 over both its cache key and canonical record payload. Accept a protected `REPOSENTRY_REPLAY_HMAC_KEY` (minimum 32 bytes) or a programmatic key; otherwise use a randomly generated local key in `.replay-hmac-key`. Reject unsigned, malformed, or invalidly signed recordings. Ignore the local key file.
- **Alternatives considered:** Hard-coded repository key (not secret and trivially forgeable); unsigned hash (attacker can recompute); environment-only key (breaks default persistent replay unless every caller configures it).
- **Evidence:** Issue #9's tampering scenario; Python stdlib `hmac` and `secrets` avoid new dependencies. Key binding prevents moving a valid recording to another cache-key filename.
- **Why chosen:** Keeps local replay usable by default while allowing deployments and shared CI to provide a protected key. With the generated local key, a workspace owner who can read both cassettes and key can forge cassettes; callers requiring separation must provide `RecordingStore(..., key=...)` or configure the environment variable from protected secret storage.
- **Reversibility:** Local recording format changes from a raw record to a signed envelope; unsigned legacy records are rejected and can be regenerated.
- **Revisit when:** Replay artifacts are shared across hosts/CI or their signing key can be provisioned through the application secret-management path.
- **Date:** 2026-10-12
- **Agent:** B

### D-B1-006 — Replay signing secret must be provisioned outside the cassette store

- **Decision:** Correct D-B1-005: filesystem `RecordingStore` requires a key passed with `key=` or a `REPOSENTRY_REPLAY_HMAC_KEY` environment variable (minimum 32 UTF-8 bytes). Do not generate/store a key beside cassettes. MemoryStore remains keyless because it does not persist or load filesystem artifacts.
- **Alternatives considered:** Keep the generated local key beside cassettes; store an automatic key in a user-profile directory; require protected external provisioning.
- **Evidence:** Adversarial threat model in issue #9: an actor who can read/modify local cassette files can read a sibling key and recompute a valid HMAC. A key must be provisioned outside the artifact trust boundary to provide authenticity.
- **Why chosen:** The HMAC provides no authenticity if its key is available to the cassette editor. Explicit external key provisioning is fail-closed and supports protected CI secret stores.
- **Reversibility:** Callers can add `key=` or configure the environment. Existing unsigned records remain rejected; prior auto-key local recordings are no longer verifiable and must be regenerated using a provisioned key.
- **Revisit when:** A dedicated application secret-management/config layer provides a stable key-loading contract.
- **Date:** 2026-10-12
- **Agent:** B

### D-B1-007 — C5 lexical BM25 implementation without a packaging dependency

- **Decision:** Implement the C5 lexical scorer and identifier tokenizer with the Python standard library behind a small index interface. Keep dense retrieval behind an injected embedder protocol; if embeddings are unavailable or fail, return lexical results and mark dense retrieval degraded. This supersedes the `bm25s` implementation preference in D-B1-002 for this branch.
- **Alternatives considered:** Add `bm25s` to shared `pyproject.toml` via a CCR; use `rank-bm25`; block C5 until packaging ownership is available.
- **Evidence:** `docs/OPERATING_CONTRACT.md` assigns `pyproject.toml` to Agent A and requires a CCR for shared dependency changes; the workspace has no dependency installed for C5, and the package index was unreachable during the current session.
- **Why chosen:** The plan requires deterministic BM25 ranking and lexical-only degradation; an in-house implementation allows offline C5 tests without modifying Agent A's owned packaging configuration.
- **Reversibility:** The lexical index interface is independent of the scoring backend and can adopt `bm25s` later without changing indexed chunk/result types.
- **Revisit when:** Agent A accepts a dependency CCR or the retrieval benchmark measures a clear gain from `bm25s`.
- **Date:** 2026-10-12
- **Agent:** B

### D-B1-008 — Provisional cumulative definitions for C10 arms A–E

- **Decision:** Until the shared ablation runner provides a contract, define Agent B's standalone adapter configs cumulatively: A deterministic candidates only; B adds the judge; C adds retrieval to the judge; D adds C8 verification of the judge's cited output; E adds the bounded C7 agent and preserves its separately labeled hypothesis channel. This is a provisional adapter mapping, not a claim that the full benchmark arms have run.
- **Alternatives considered:** Leave Agent B's arm adapters absent; create five independent non-cumulative configs; treat E as an agent replacing the judge/verifier path.
- **Evidence:** P4 explicitly calls C the “+retrieval” arm; the plan says verification only matters when the LLM authors citations, and recall can exceed B only when the agent proposes candidates. The plan contains no detailed A–E table or runner interface in this checkout.
- **Why chosen:** This mapping satisfies the explicit plan constraints and exposes the missing runner contract; no arm silently gains retrieval, verification, or new candidates.
- **Reversibility:** Arm config values and the adapter's callback protocol are local to Agent B and can be mapped to Agent A's eventual runner contract.
- **Revisit when:** The shared C10 ablation runner and exact arm definitions are available.
- **Date:** 2026-10-12
- **Agent:** B
