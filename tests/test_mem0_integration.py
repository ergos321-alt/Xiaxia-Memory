import hashlib
import json
import os
os.environ.setdefault("MEM0_TELEMETRY", "false")
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone

import pytest
from mem0 import Memory
from app import create_app
from app.memory_engine import MemoryEngine


class DeterministicEmbedding:
    def embed(self, text, memory_action=None):
        # Real vector-store integration with a deterministic, character-aware
        # embedding so related Chinese phrases have a measurable cosine score.
        vector = [0.0] * 32
        for char in str(text):
            digest = hashlib.sha256(char.encode()).digest()
            vector[int.from_bytes(digest[:2], "big") % 32] += 1.0
        norm = sum(value * value for value in vector) ** 0.5 or 1.0
        return [value / norm for value in vector]
    def embed_batch(self, texts, memory_action="add"): return [self.embed(text, memory_action) for text in texts]


class ExtractionLLM:
    def generate_response(self, messages, **kwargs):
        return json.dumps({"memory": [{"text": "两人决定把共同历史交给长期 Memory 保存"}]}, ensure_ascii=False)


class Classifier:
    def classify(self, facts):
        return [{"category": "relationship", "subtype": "milestone", "importance": 10, "metadata": {"subject": "shared"}} for _ in facts]


class InMemoryRepository:
    def __init__(self): self.rows = {}; self.audit = []; self.batches = []
    def create(self, record, event_type="created"):
        row = {"created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc), "deleted_at": None, **deepcopy(record)}
        self.rows[str(row["mem0_id"])] = row
        self.audit.append({"mem0_id": str(row["mem0_id"]), "event_type": event_type, "actor": row["source"], "created_at": datetime.now(timezone.utc), "before_state": None, "after_state": deepcopy(row)})
        return row
    def get(self, mem0_id, include_deleted=False):
        row = self.rows.get(str(mem0_id)); return row if row and (include_deleted or row["deleted_at"] is None) else None
    def get_many(self, ids, include_deleted=False): return {str(i): self.get(i, include_deleted) for i in ids if self.get(i, include_deleted)}
    def find_by_import_key(self, import_key):
        return next((row for row in self.rows.values() if row["deleted_at"] is None and row.get("metadata", {}).get("legacy_import_key") == import_key), None)
    def update(self, mem0_id, changes, before_memory=None, after_memory=None, actor="viewer"):
        row = self.rows[str(mem0_id)]; before = deepcopy(row); row.update(deepcopy(changes)); row["updated_at"] = datetime.now(timezone.utc)
        self.audit.append({"mem0_id": str(mem0_id), "event_type": "updated", "actor": actor, "created_at": datetime.now(timezone.utc), "before_state": {"domain": before, "memory": before_memory}, "after_state": {"domain": deepcopy(row), "memory": after_memory}}); return row
    def supersede(self, old_id, new_id, actor="custom_gpt"):
        old, new = self.rows[str(old_id)], self.rows[str(new_id)]; old.update(status="superseded", superseded_by=str(new_id)); new["supersedes"] = str(old_id)
        self.audit.append({"mem0_id": str(old_id), "event_type": "superseded", "actor": actor, "created_at": datetime.now(timezone.utc), "before_state": None, "after_state": deepcopy(old)}); return old, new
    def mark_deleted(self, mem0_id, actor="viewer"):
        row = self.rows[str(mem0_id)]; before = deepcopy(row); row.update(status="archived", deleted_at=datetime.now(timezone.utc)); return before, row
    def rollback_delete(self, before, actor="system"): self.rows[str(before["mem0_id"])] = before
    def confirm_deleted(self, mem0_id, snapshot, actor="viewer"): self.audit.append({"mem0_id": str(mem0_id), "event_type": "deleted", "actor": actor, "created_at": datetime.now(timezone.utc), "before_state": snapshot, "after_state": deepcopy(self.rows[str(mem0_id)])})
    def compensate_failed_create(self, mem0_id, actor="system"):
        row = self.rows.get(str(mem0_id))
        if row: row.update(status="archived", deleted_at=datetime.now(timezone.utc))
        return row
    def recent(self, days=14, limit=20): return [row for row in self.rows.values() if row["deleted_at"] is None and row["status"] in {"active","historical"}][:limit]
    def list(self, filters, limit=100): return list(self.rows.values())[:limit]
    def history(self, mem0_id): return [event for event in self.audit if event["mem0_id"] == str(mem0_id)]
    def create_import_batch(self, label, count, metadata): self.batches.append((label,count,metadata))


@contextmanager
def without_proxy():
    keys = [key for key in os.environ if key.lower() in {"all_proxy","http_proxy","https_proxy"}]
    saved = {key: os.environ.pop(key) for key in keys}
    try: yield
    finally: os.environ.update(saved)


@pytest.fixture()
def service(tmp_path):
    with without_proxy():
        memory = Memory.from_config({
            "llm": {"provider": "openai", "config": {"api_key": "test", "model": "qwen-flash", "openai_base_url": "http://127.0.0.1:9/v1"}},
            "embedder": {"provider": "openai", "config": {"api_key": "test", "model": "test", "openai_base_url": "http://127.0.0.1:9/v1", "embedding_dims": 32}},
            "vector_store": {"provider": "qdrant", "config": {"path": str(tmp_path / "qdrant"), "collection_name": "xiaxia_test", "embedding_model_dims": 32}},
            "history_db_path": str(tmp_path / "history.db"), "custom_instructions": "Store durable history only.",
        })
    memory.embedding_model = DeterministicEmbedding(); memory.llm = ExtractionLLM()
    repo = InMemoryRepository(); svc = MemoryEngine(repo, {"MEM0_USER_ID": "shared_test"}, mem0=memory, classifier=Classifier())
    yield svc
    memory.close(); memory.vector_store.client.close()
    if memory._entity_store is not None: memory._entity_store.client.close()


def structured(text, **extra):
    return {"memory_text": text, "category": "relationship", "subtype": "milestone", "importance": 9, "occurred_at": "2026-08-27T12:00:00+00:00", **extra}


def test_real_mem0_infer_true_add_search_get(service):
    rows = service.add_inferred("我们决定建设不会随窗口消失的长期记忆。")
    assert len(rows) == 1 and rows[0]["category"] == "relationship"
    found = service.search("共同历史", {}, 5)
    assert found and service.get(rows[0]["id"])["memory_text"] == "两人决定把共同历史交给长期 Memory 保存"


def test_real_mem0_infer_false_update_reembedding_and_delete(service):
    row = service.add_structured(structured("旧的正文：记忆系统开始施工"))
    assert service.mem0.get(row["id"])["memory"] == "旧的正文：记忆系统开始施工"
    changes = {"category": "relationship", "subtype": "identity_shift", "importance": 10, "occurred_at": "2026-08-27T13:00:00+00:00", "source": "viewer"}
    updated = service.update(row["id"], "新的正文：Mem0 成为权威引擎", changes)
    assert updated["memory_text"] == "新的正文：Mem0 成为权威引擎"
    exact = service.search("新的正文：Mem0 成为权威引擎", {}, 5)
    assert exact and exact[0]["id"] == row["id"]
    service.delete(row["id"])
    assert service.search("新的正文：Mem0 成为权威引擎", {}, 5) == []
    try:
        deleted = service.mem0.get(row["id"])
    except Exception:
        deleted = None
    assert deleted is None
    assert service.repository.get(row["id"], include_deleted=True)["status"] == "archived"


def test_viewer_edit_route_updates_mem0_embedding(service):
    row = service.add_structured(structured("Viewer 修改前的正文"))
    app = create_app({"TESTING": True, "OPEN_DB_ON_START": False, "DB_INSTANCE": object(),
        "ENGINE_INSTANCE": service, "SECRET_KEY": "test-secret", "ADMIN_PASSWORD": "test"})
    client = app.test_client()
    with client.session_transaction() as session:
        session["memory_admin"] = True
    response = client.post(f"/admin/memory/{row['id']}/edit", data={
        "memory_text": "Viewer 修改后的权威正文", "category": "relationship",
        "subtype": "milestone", "importance": "9", "occurred_at": "2026-08-27T12:00:00+00:00",
        "status": "active", "source": "viewer",
    })
    assert response.status_code == 302
    assert service.mem0.get(row["id"])["memory"] == "Viewer 修改后的权威正文"
    found = service.search("Viewer 修改后的权威正文", {}, 5)
    assert found and found[0]["id"] == row["id"]


def test_legacy_import_enters_mem0_and_recent_context(service):
    saved = service.archive_period("旧窗口", [structured("旧窗口里，两人正式确认关系连续性")], {"branch": "real"})
    assert service.mem0.get(saved[0]["id"])["memory"] == "旧窗口里，两人正式确认关系连续性"
    assert service.search("关系连续性", {}, 5)
    recent = service.recent_context(14, 20)
    assert recent["recent_relationship"][0]["id"] == saved[0]["id"]
    assert service.repository.batches == [("旧窗口", 1, {"branch": "real"})]
    repeated = service.archive_period("旧窗口重试", [structured("旧窗口里，两人正式确认关系连续性")], {"retry": True})
    assert repeated[0]["id"] == saved[0]["id"]


def test_superseded_memory_remains_history_but_is_not_current(service):
    old = service.add_structured(structured("当时喜欢某种关系语言"))
    new = service.add_structured(structured("后来这种关系语言自然淡化", subtype="relationship_dynamic", supersedes=old["id"]))
    assert service.mem0.get(old["id"])["memory"] == "当时喜欢某种关系语言"
    assert service.repository.get(old["id"])["status"] == "superseded"
    current = service.search("关系语言", {}, 10)
    ids = [item["id"] for item in current]
    assert new["id"] in ids and old["id"] not in ids
    assert any(event["event_type"] == "superseded" for event in service.history(old["id"]))


def test_mem0_search_top_k_metadata_and_time_filters(service):
    service.add_structured(structured("过滤测试：较早且低重要度", importance=3, occurred_at="2025-01-01T00:00:00+00:00"))
    recent = service.add_structured(structured("过滤测试：近期且高重要度", importance=10, occurred_at="2026-08-27T12:00:00+00:00"))
    found = service.search("过滤测试", {"category": "relationship", "subtype": "milestone",
        "min_importance": 9, "from": "2026-01-01T00:00:00+00:00", "to": "2026-12-31T23:59:59+00:00"}, 1)
    assert len(found) == 1 and found[0]["id"] == recent["id"]
