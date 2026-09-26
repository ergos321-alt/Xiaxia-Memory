# Xiaxia Memory V1 · Mem0 2.0.19 Architecture

独立于聊天窗口的长期关系记忆服务。最高原则：Memory 保存历史，不规定未来。

## 权威边界

- Mem0 OSS 2.0.19 是唯一 Memory Engine，拥有正文、Memory ID、embedding、向量存储和语义检索。
- Xiaxia Domain Layer 只保存 category/subtype/importance/time/source/status、relationship lifecycle、supersede 链、Legacy Import 幂等键和审计；不保存正文或向量。
- 普通 conversation 走 `Mem0.add(..., infer=True)`；明确结构化 relationship Memory 走 `Mem0.add(..., infer=False)`。
- 搜索走 `Mem0.search()`；Viewer 正文编辑走 `Mem0.update()`；删除先建立 ledger pending 状态，再删除 Mem0，失败会回滚 ledger。
- 不部署 Mem0 Server/Dashboard，不 fork Mem0，也没有旧 `xiaxia_mem0_engine` 双写运行路径。

完整职责和数据流见 `docs/ARCHITECTURE.md`，调用证据见 `docs/MEM0_2_0_19_EVIDENCE.md`。

## 部署

1. 在 Supabase SQL Editor 一次性运行 `migrations/001_init.sql`。默认 Qwen embedding 为 1024 维；改变维度前必须同步修改 SQL 与 `EMBEDDING_DIMENSIONS`。
2. 复制 `.env.example` 到 Render 环境变量。`DATABASE_URL` 使用 Supabase Session Pooler 或兼容直连串；所有 Token/Key/密码只放服务端。
3. Render 使用 `render.yaml`。Uvicorn 保持 `--workers 1`，`a2wsgi` bridge 保持 4 个 WSGI 线程，避免多个进程争用 Mem0 本地 history SQLite；Domain pool 1、Mem0 主 collection pool 1–2、Mem0 entity collection pool 1–2，单实例最大 5 条 PostgreSQL 连接。
4. 访问 `/health` 和 `/admin/login`。将 `openapi.yaml` 的固定 server URL 改为真实 Render URL 后导入 Custom GPT Actions，并配置 Bearer Token。
5. 将 `docs/CUSTOM_GPT_INSTRUCTIONS.md` 追加到 Custom GPT Instructions。
6. 若从旧 V1 升级，按 `docs/MIGRATION_V1_TO_MEM0.md` 先导入并验证，再清理隔离的旧表。

## API

- `POST /api/v1/memories/save`：`raw_text` 由 Mem0 提取；`memories` 逐条以原义直接进入 Mem0。
- `POST /api/v1/memories/search`：Mem0 语义检索，top-k 强制 1–20；Domain Layer 追加 subtype/importance/time 筛选。
- `GET /api/v1/context/recent`：以一次有界 `Mem0.get_all()` 加一次 ledger 批量查询编排五个紧凑分区，不逐条 SELECT。
- `POST /api/v1/windows/archive`：结构化旧窗口 Memory 真正进入 Mem0；精确重试由 ledger import key 幂等化。

## MCP

`/mcp` 提供与 OpenAPI operationId 同名的四个 MCP tools。每个 tool 只把参数转交给原 `/api/v1/*` HTTP route，并复用 `MEMORY_API_TOKEN`；Mem0、Domain Layer、Supersede 和 archive 幂等行为均由现有 API 负责。公网 `/mcp` 入站认证暂缓至统一 MCP Security Pass。

## 数据库与 Egress

- `xiaxia_mem0_memories` / `_entities`：Mem0 官方 PGVector provider 使用，HNSW 索引；正文在 payload 中，ID 为权威 Mem0 UUID。
- `memory_domain`：无正文、无 embedding。recent/category/status/subtype 和 Legacy import key 有索引。
- `memory_audit_events`：修订、supersede、删除和补偿事件。
- `memory_import_batches`：旧窗口导入批次。

Mem0 PGVector 第一次操作会用一次 collection existence 查询；表已由 migration 预建，因此不会进入 DDL。之后 `search()` 为一次 embedding 调用和一次带 HNSW、过滤、LIMIT 的向量 SQL；ledger 用一次 `WHERE mem0_id = ANY(...)` 批量 join。Recent 和 Viewer list 都使用 Mem0 有界批量读取，不做 N+1。没有 polling，也没有请求级建表或建索引。

## 测试

```bash
pip install -r requirements.txt
pytest -q
```

本地套件会真实实例化 Mem0 2.0.19 和真实向量库，验证 add/search/get/update/delete、Legacy Import、supersede、Viewer 编辑及 Recent 编排。生产 Qwen + Supabase 测试默认跳过；准备隔离环境并应用 migration 后运行：

```bash
RUN_PRODUCTION_MEM0_TESTS=1 pytest -q tests/test_production_mem0.py
```

当前结果与未伪装的环境限制见 `TEST_RESULTS.md`。真实旧窗口 → 全新 Custom 对话验收按 `docs/REAL_ACCEPTANCE.md` 执行。
