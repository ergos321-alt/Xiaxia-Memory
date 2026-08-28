# Test Results

Execution date: 2026-08-27 UTC

## Completed in this environment

- Python syntax compilation: passed.
- Automated suite: **22 passed, 1 skipped**.
- Dependency consistency (`pip check`): passed.
- Imported package version: **mem0ai 2.0.19**.
- Actual Mem0 integration (no mocked `Memory` object): passed for `add(infer=True)`, `add(infer=False)`, `search()`, `get()`, `update()` followed by changed-text retrieval, `delete()` followed by absence, Legacy Import → Mem0 → search, relationship ledger linkage, supersede filtering, Viewer route edit and Recent Context composition.
- Contract tests: application has no runtime DDL, no self embedding call, no `xiaxia_mem0_engine`, ledger has no body/vector column, OpenAPI keeps conservative schema.

The local integration uses a real Mem0 2.0.19 instance and a real local Qdrant vector store. LLM and embedding components are deterministic test implementations so the suite is repeatable and credential-free; this is not presented as a Qwen/Supabase production pass.

## Explicitly pending

- `tests/test_production_mem0.py`: **1 skipped**, because this workspace has neither `DATABASE_URL` nor `QWEN_API_KEY`. It contains a non-mocked Qwen + official PGVector/Supabase + DomainRepository full-lifecycle test and must run in an isolated deployed test environment.
- Real old-window → brand-new Custom GPT window continuity test: pending a deployed Action and a user-selected real historical branch.

No “remembered strawberry preference” demo is used as relationship-continuity evidence, and no skipped production check is reported as passed.
