# Product pool retrieval implementation plan

> Execution: use the executing-plans skill, task by task. The user approved the preceding assessment with “动手补”; continue without another approval gate.

**Goal:** Make repeated Codex-driven product search complete enough to expose its gaps, preserve quote meaning, and reuse verified metadata.

**Architecture:** Keep immutable source records and SQLite. Add evidence-backed search metadata, explicit source/offer lifecycle, and a bounded multi-query retrieval tool. Codex interprets language; local code validates facts, filters, merges and reports missing coverage.

**Tech stack:** Existing Python, SQLite FTS5 and standard library. No new model service or vector dependency.

**Spec:** The approved assessment and `docs/PRODUCT_POOL.md`; contracts below refine those requirements.

## Global constraints

- Original records, file hashes and product IDs remain stable. No filename/brand-specific parser branches or inferred prices.
- Semantic enrichment never overwrites source facts. Every change has product-owned evidence, revision checking and an audit record.
- Price roles, currency, sale unit and trade terms remain distinct; unknown values are visible and never satisfy numeric constraints.
- Date/series/product identity must be explicitly recorded; upload time and similar names do not establish the latest quote or the same SKU.
- Main Codex alone writes the production pool. Normal-speed GPT-6 Sol may review bounded inputs; no Astra or fast mode.
- User files, evaluation inputs/results and databases remain ignored and local. Customer PPT and saved choices remain intact.

## Review focus

1. Empty tags or missing metadata must not become a claim that no suitable products exist.
2. Shared hard conditions must survive every expanded query and merge; negative categories and unit conversions need tests.
3. New uploads, partial imports and equal/unknown dates must not silently supersede quotes.
4. Conflicting identities, stale edits and source quotes borrowed from another product must fail atomically.
5. Existing pools and frozen selection sessions must continue working; changed/withdrawn selected facts must block export.

## Task 1: Search metadata and quality

Files: add `catalog_tool/pool_metadata.py`, update `pool_store.py` and `pool.py`; tests in `test_pool_metadata.py`.

Interfaces: `enrich(records)`, `derive(ids=None)`, `quality(price_field=None)`, `review_queue(...)`, vocabulary registration. Metadata entries contain product ID, expected revision, field, typed value, origin, product-owned quote and reason. Text core fields are brand/category/supplier; numeric attributes carry explicit convertible units. Keep historical changes. Deterministic derivation only accepts explicit labeled facts; model classification is a separate evidence-backed operation.

- [x] Write meaningful tests for evidence, conflicts, transactions, conversion and migration; observe failures.
- [x] Implement metadata storage, bounded review queues and quality counts; expose CLI contracts.
- [x] Run the metadata tests and the existing pool tests.

## Task 2: Sources, quotes and product identity

Files: add `catalog_tool/pool_lifecycle.py`; update pool store/CLI/selection; tests in `test_pool_lifecycle.py`.

Interfaces: `update_sources(records)`, `link_products(records)`, offer terms in metadata, `selection_context(id)`. Source metadata records series, issue date and active/withdrawn/superseded state with revision/reason/evidence. Explicit same-product links group offers without deleting original rows. Corrections retain history. Latest-only search excludes unknown/ambiguous lineage instead of choosing by import time.

- [x] Test source revisions, partial supersession, date ties, identity conflicts, quote terms and selected-context changes.
- [x] Implement additive schema migration and lifecycle commands, preserving old session compatibility.
- [x] Run lifecycle and selection tests.

## Task 3: Bounded retrieval

Files: add `catalog_tool/pool_retrieval.py`; extend pool search hooks/CLI; tests in `test_pool_retrieval.py`.

Interface: `retrieve(plan)` with version 1, shared `hard` filters, explicit `lanes`, bounded `limit`/`per_lane`, optional diversity and reviewed entity grouping. Expand registered equivalent query terms, execute bounded searches, fuse ranks, return evidence and per-lane totals. Shared budget/price role, negative categories and typed attributes cannot be overridden by lanes. Report clipped candidate sets, partial sources, unknown prices/attributes and unresolved versions. Reuse freshness checks within one retrieval call only.

- [x] Test synonym recall, sparse tags with explicit alternate lanes, hard constraints, bounded output, diversity and grouping.
- [x] Implement retrieval with existing factual search; no second extraction engine or natural-language rule pile.
- [x] Run retrieval tests and regressions.

## Task 4: Apply and verify

Files: update `POOL_WORKFLOW.md`, `docs/POOL_IMPORT.md`, `docs/PRODUCT_POOL.md`, and on-demand retrieval contract; add a reusable synthetic retrieval evaluation.

- [x] Backfill only justified metadata in the local pool, using bounded grouped evidence and validated writes. Leave unknowns explicit.
- [x] Repeat real oral requests, budget/brand/category controls and source integrity checks. Independently review the diff with ordinary-speed Sol.
- [x] Run root/capability tests and public audit; prepare code-only synchronization and measured results with remaining evidence gaps.

## Progress

- Plan written against the existing pool and previous live assessment. No production mutation yet.
- Ruling: split the extractor's old broad price aliases into distinct commercial roles. Tests revealed that a literal retail label was stored as reference_price_b, and supply/cost labels shared agent_price. Existing pool payloads stay immutable; search reports and excludes clear role/label conflicts unless an explicit verified label is selected. Risk if wrong: callers relying on the old conflation must inspect labels instead of silently receiving a different price basis.
- Tasks 1–3 implemented; isolated pool tests cover evidence/revisions, unit conversion, explicit lineage, frozen context and bounded multi-lane retrieval. Real-data classification is running as two read-only ordinary-speed Sol jobs; production data not yet mutated.
- Final data pass: production now contains validated overlays; 4 mismatched citations and 6 ambiguous single-brand bundle claims were excluded. Raw rows, prices, source records, saved choices and customer PPT hashes remain unchanged. Unknown dates/suppliers and two partial sources remain visible.
- Model experiment found that candidate snippets omitted unmapped original columns; fixed the shared factual projection. Sol passed 8/8; Terra 5/8 before one actual-validation recovery and 8/8 after. Contract clarification covers orthogonal packaging/category dimensions and the meaning of has_image; no per-case parser or expected candidate ID was added.
- Independent Sol review: fixed explicit MOQ wording and paginated access to folded source offers. Two reports were rejected after checking current code: old sessions already call source-status validation unconditionally; source() hashes files and does not invoke the evidence cache transaction. Tests cover old-session withdrawal and atomic metadata failure.
- Added audited overlay removal and explicit group invalidation when identity facts change. Root 7 + capability 49 tests pass with UTF-8 subprocess environment; CLI quality works on the migrated production database. Real three-plan benchmark: 30 trials, median 261 ms, max 471 ms, excluding model time.
- Release gates: CLI retrieval returned the bounded two-item projection from ten valid real-pool candidates; staged public audit passed with no findings (133 prior reachable history objects). All private inputs, decisions, databases and reports stay outside the tracked file set.
