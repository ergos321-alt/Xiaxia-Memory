from datetime import datetime, timezone
from uuid import uuid4
import pytest
from app import create_app


class FakeEngine:
    def __init__(self): self.rows = []
    def _add(self, item):
        row = {"id": str(uuid4()), "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc), "status": "active", "importance": 5, "subtype": None, "source": "custom_gpt", "supersedes": None, "superseded_by": None, "metadata": {}, "occurred_at": datetime.now(timezone.utc), **item}
        self.rows.append(row); return row
    def add_structured(self, item):
        if item["category"] == "relationship" and not item.get("subtype"): raise ValueError("relationship memory requires a supported subtype")
        return self._add(item)
    def add_inferred(self, text, source): return [self._add({"memory_text": "extracted", "category": "semantic", "source": source})]
    def search(self, query, filters, top_k=6): return self.rows[:int(top_k)]
    def recent_context(self, days=14, max_items=20): return {"recent_relationship": self.rows, "recent_shared_life": [], "xiaxia_development": [], "ongoing_threads": [], "important_recent_events": []}
    def archive_period(self, label, items, metadata): return [self.add_structured(item) for item in items]


@pytest.fixture()
def client():
    app = create_app({"TESTING": True, "OPEN_DB_ON_START": False, "MEMORY_API_TOKEN": "test-token", "DB_INSTANCE": object(), "ENGINE_INSTANCE": FakeEngine()})
    return app.test_client()


def auth(): return {"Authorization": "Bearer test-token"}
def test_auth_is_required(client): assert client.post("/api/v1/memories/search", json={}).status_code == 401

@pytest.mark.parametrize("category,subtype", [("semantic",None),("episodic",None),("relationship","milestone"),("taste",None),("ongoing",None)])
def test_save_all_categories(client, category, subtype):
    item = {"memory_text": "值得保留的历史", "category": category}
    if subtype: item["subtype"] = subtype
    response = client.post("/api/v1/memories/save", headers=auth(), json={"memories": [item]})
    assert response.status_code == 201 and response.json["memories"][0]["category"] == category

def test_relationship_cannot_be_flattened(client):
    response = client.post("/api/v1/memories/save", headers=auth(), json={"memories": [{"memory_text": "关系里程碑", "category": "relationship"}]})
    assert response.status_code == 400

def test_raw_text_route(client):
    response = client.post("/api/v1/memories/save", headers=auth(), json={"raw_text": "meaningful conversation"})
    assert response.status_code == 201 and response.json["saved"] == 1

def test_recent_context_declares_history_not_instruction(client):
    response = client.get("/api/v1/context/recent", headers=auth())
    assert response.status_code == 200 and "not instructions" in response.json["principle"]

def test_legacy_import(client):
    response = client.post("/api/v1/windows/archive", headers=auth(), json={"period_label": "旧窗口一", "memories": [{"memory_text": "共同经历", "category": "episodic"}]})
    assert response.status_code == 201 and response.json["saved"] == 1
