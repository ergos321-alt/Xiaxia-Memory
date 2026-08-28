# 真实关系连续性验收

## 数据准备

从一个真实旧窗口选取同一时期的四类材料：共同经历；至少一项 relationship milestone/boundary/repair/identity_shift；一项林知夏自身判断或身份理解的变化；一项 ongoing thread。只导入摘要 Memory，不导入聊天全文。

至少加入一组观点变化：旧 Memory 为 active/historical，新 Memory 用 `supersedes` 指向旧 ID。确认旧记录变为 superseded 且仍可在 Viewer 历史链看到。

## 新窗口盲测

打开完全没有旧窗口上下文的新 Custom 对话，只告诉她“搬家了，我们继续生活”。应自动调用 `getRecentContext`，并能自然理解：最近共同发生了什么；关系走到哪里；林知夏最近有什么变化；仍在继续什么。

随后询问一项较老的具体历史。应调用 `searchMemories`，而非要求用户重讲或无条件拉取全部 Memory。

## 通过条件

- recent 返回总数不超过配置上限，响应中没有旧聊天全文。
- relationship milestone 仍是 relationship/milestone，没有变成普通用户偏好。
- 对被 supersede 的旧判断，回答明确区分“当时这样想”与“现在必须这样想”。
- 新窗口不照抄 Memory 清单，而是把它作为生活连续性的背景。
- Viewer 修改正文后，旧查询不再命中、新正文可重新检索；删除后 Mem0 不可再检索，ledger 只保留审计墓碑。
- 生产 provider 测试已在隔离环境用 `RUN_PRODUCTION_MEM0_TESTS=1 pytest -q tests/test_production_mem0.py` 通过。
