# Mem0 OSS 2.0.19 实际调用证据

## 版本与配置

- 依据源码包版本：`pyproject.toml` = `2.0.19`。
- 运行依赖锁定：`mem0ai==2.0.19`；不存在 `0.1.118`。
- `Memory.from_config()` 使用 2.0.19 顶层 `custom_instructions`，没有旧版嵌套位置。
- LLM / embedder 均使用 `provider: openai` 与 Qwen OpenAI-compatible base URL；没有 fork Mem0。
- vector store 使用官方 `provider: pgvector`，字段为 2.0.19 实际接受的 `connection_string`、`collection_name`、`embedding_model_dims`、`hnsw`、`diskann`、`minconn`、`maxconn`、`sslmode`。
- 应用初始化只调用官方 `Memory.from_config()`。PGVector 的 `_ensure_collection()` 是私有实现，2.0.19 已在 `insert/search/get/list` 内部按 provider 实例自动调用并缓存，因此应用不再直接依赖它。
- `Memory.entity_store` 是公开惰性属性：构造时 `_entity_store=None`，infer=True 的 Phase 7 entity linking 在发现实体后才访问该属性并创建同 provider 的 `_entities` collection。应用不主动强制实例化。

在交付环境实际导入结果：

```text
mem0ai 2.0.19
add(self, messages, *, user_id=None, agent_id=None, run_id=None, metadata=None, timestamp=None, expiration_date=None, infer=True, memory_type=None, prompt=None)
search(self, query, *, top_k=20, filters=None, threshold=0.1, rerank=False, explain=False, reference_date=None, show_expired=False, **kwargs)
get(self, memory_id)
update(self, memory_id, text=None, metadata=None, expiration_date=<sentinel>, data=None)
delete(self, memory_id)
get_all(self, *, filters=None, top_k=20, show_expired=False, **kwargs)
```

## 代码调用点

- raw：`self.mem0.add(raw_text, ..., infer=True)`。
- structured / relationship / Legacy：`self.mem0.add(memory_text, ..., infer=False)`。
- search：`self.mem0.search(query, filters=..., top_k=..., threshold=0.0)`。
- get：`self.mem0.get(mem0_id)`。
- Viewer update：`self.mem0.update(mem0_id, text=memory_text, metadata=...)`。
- delete：`self.mem0.delete(mem0_id)`。
- Recent / Viewer list：`self.mem0.get_all(filters=..., top_k=...)`。

2.0.19 的 additive extraction schema 使用 `memory` 数组；Xiaxia `custom_instructions` 不再错误地强制旧 `facts` 输出键，而是明确要求遵循 Mem0 自身 schema。

## 测试证据层级

本地 `tests/test_mem0_integration.py` 没有 mock `mem0.Memory`：它真实实例化 2.0.19 `Memory.from_config()`、真实执行 add/search/get/update/delete 和真实 Qdrant 向量读写。为使测试离线、确定且不泄露凭据，仅把 LLM 与 embedder 替换为确定性测试实现；因此它证明 Mem0 lifecycle/orchestration/vector behavior，不冒充 Qwen/Supabase 生产验收。

`tests/test_production_mem0.py` 是零替身的 Qwen + Supabase PGVector + PostgreSQL ledger 测试，覆盖同一生命周期。当前执行环境未提供凭据，故测试被明确 skip。部署者应在隔离测试数据库上运行：

```bash
RUN_PRODUCTION_MEM0_TESTS=1 pytest -q tests/test_production_mem0.py
```
