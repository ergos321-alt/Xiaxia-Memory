# 从旧双引擎 V1 迁移到 Mem0 2.0.19

## 目标

新代码只认 Mem0 UUID。旧 `memories` / `xiaxia_mem0_engine` 不再参与 save、search、recent、Viewer 或 delete。Migration 会把旧 `memories` 隔离重命名为 `legacy_v1_memories`，但不会在未验证前破坏性删除历史。

## 顺序

1. 备份 Supabase，并记录当前 Render release。
2. 停止旧服务写入。
3. 运行 `migrations/001_init.sql`，确认 `xiaxia_mem0_memories`、`memory_domain`、`memory_audit_events` 和索引存在。
4. 部署新代码与 `mem0ai==2.0.19`，检查 `/health`。
5. 从旧表或旧窗口按时期整理结构化 Memory，通过 `archiveWindowPeriod` 导入。每条会调用 `Mem0.add(infer=False)`；重复重试返回同一权威 Mem0 ID。
6. 在 Viewer 抽查正文、category/subtype、时间、source、status；再用 `searchMemories` 查到同一 Mem0 ID。
7. 完成真实新窗口验收后，保留一段观察期。
8. 只有在备份、数量核对、抽查和新窗口验收全部通过后，才手工删除隔离表和旧 shadow collection。

建议核对 SQL：

```sql
select count(*) from xiaxia_mem0_memories;
select count(*) from memory_domain where deleted_at is null;
select count(*) from memory_domain d
left join xiaxia_mem0_memories m on m.id=d.mem0_id
where d.deleted_at is null and m.id is null;
```

最后一项必须为 0。清理是不可逆操作，不包含在自动部署 migration 中：

```sql
-- 仅在验证并备份后手工执行；表名先在 Supabase 中再次确认。
drop table if exists xiaxia_mem0_engine;
drop table if exists legacy_v1_memories;
```

## 回滚边界

新旧表隔离，因此观察期内可回滚旧 Render release；但新架构创建的 Memory 只在 Mem0 collection 中，回滚前必须停止写入并导出观察期新增记录。不得重新启用双写来“保险”，否则会再次产生两个权威来源。
