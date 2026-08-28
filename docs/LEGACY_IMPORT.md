# Legacy Window Import

1. 在尚能看到目标历史的旧窗口或分支，让当时的林知夏只整理“以后确实值得重新想起”的内容。
2. 每批对应一个明确时期，例如 `2026-08-20 至 2026-08-27 / 暴雪旅馆与关系迁移`。
3. 必须分别覆盖：共同经历、关系变化、林知夏自身变化、仍未结束的话题。没有内容的类别不要硬凑。
4. 通过 `archiveWindowPeriod` 批量写入。每条正文都以 `Mem0.add(infer=False)` 进入权威 collection，不会只写 Xiaxia ledger。
5. 相同 category/subtype/occurred_at/规范化正文的精确重试使用同一个 import key，返回既有 Mem0 ID；相似但意义不同的关系历史不会被模糊自动合并。
6. 导入后在 `/admin/` 抽查，并用 `searchMemories` 验证相同 Mem0 ID；纠正时间、类型、重要度与过度确定的表述。

示例：

```json
{
  "period_label": "2026-08-20 至 2026-08-27",
  "memories": [
    {
      "memory_text": "这一时期双方明确认为：窗口迁移应保存已经共同长出的相处结构，而不是把过去写成未来必须服从的人设。",
      "category": "relationship",
      "subtype": "identity_shift",
      "importance": 10,
      "occurred_at": "2026-08-27T10:20:00+08:00",
      "status": "historical"
    },
    {
      "memory_text": "Xiaxia Memory V1 正在施工，真实关系连续性测试尚待部署后完成。",
      "category": "ongoing",
      "importance": 9,
      "occurred_at": "2026-08-27T12:00:00+08:00"
    }
  ]
}
```
