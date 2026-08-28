import json
import os
import hashlib
from datetime import datetime, timedelta, timezone

os.environ.setdefault("MEM0_TELEMETRY", "false")
from mem0 import Memory
from openai import OpenAI

CATEGORIES = {"semantic", "episodic", "relationship", "taste", "ongoing"}
RELATIONSHIP_SUBTYPES = {"milestone", "boundary", "conflict", "repair", "shared_habit", "shared_language", "identity_shift", "relationship_dynamic"}
STATUSES = {"active", "historical", "superseded", "archived"}

CUSTOM_INSTRUCTIONS = """
Store only durable history worth recalling in a future conversation. Exclude greetings,
filler, transient wording and full chat transcripts. Preserve uncertainty and temporal
language. A preference, opinion, boundary or relationship dynamic describes what was true
at that time; it never commands the person's future identity. Preserve changes, conflict,
repair and identity shifts as historical facts. Do not flatten shared relationship events
into generic user preferences. Follow Mem0's required extraction output schema exactly and
keep each extracted Memory independently useful.
""".strip()


def build_mem0(config):
    return Memory.from_config({
        "llm": {"provider": "openai", "config": {
            "model": config["QWEN_CHAT_MODEL"], "api_key": config["QWEN_API_KEY"],
            "openai_base_url": config["QWEN_BASE_URL"], "temperature": 0.1,
        }},
        "embedder": {"provider": "openai", "config": {
            "model": config["QWEN_EMBEDDING_MODEL"], "api_key": config["QWEN_API_KEY"],
            "openai_base_url": config["QWEN_BASE_URL"], "embedding_dims": config["EMBEDDING_DIMENSIONS"],
        }},
        "vector_store": {"provider": "pgvector", "config": {
            "connection_string": config["DATABASE_URL"], "collection_name": config["MEM0_COLLECTION"],
            "embedding_model_dims": config["EMBEDDING_DIMENSIONS"], "hnsw": True, "diskann": False,
            "minconn": config["MEM0_DB_POOL_MIN"], "maxconn": config["MEM0_DB_POOL_MAX"], "sslmode": "require",
        }},
        "history_db_path": config["MEM0_HISTORY_DB_PATH"],
        "custom_instructions": CUSTOM_INSTRUCTIONS,
    })


class DomainClassifier:
    """Classifies Mem0-produced facts; it never extracts or embeds Memory text."""
    def __init__(self, config):
        self.client = OpenAI(api_key=config["QWEN_API_KEY"], base_url=config["QWEN_BASE_URL"])
        self.model = config["QWEN_CHAT_MODEL"]

    def classify(self, facts):
        prompt = """Classify each already-extracted historical Memory. Return JSON key items in the same order. Fields: category, subtype|null, importance 1-10, occurred_at|null, metadata. Categories: semantic, episodic, relationship, taste, ongoing. Relationship subtype must be one of milestone, boundary, conflict, repair, shared_habit, shared_language, identity_shift, relationship_dynamic. Do not rewrite or extract new Memory text. History does not prescribe the future."""
        response = self.client.chat.completions.create(
            model=self.model, temperature=0.1, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": json.dumps(facts, ensure_ascii=False)}],
        )
        items = json.loads(response.choices[0].message.content).get("items", [])
        return items if len(items) == len(facts) else [{} for _ in facts]


class MemoryEngine:
    """Xiaxia domain facade. Mem0 is the sole Memory/embedding/vector/search engine."""
    def __init__(self, repository, config, mem0=None, classifier=None):
        self.repository = repository
        self.config = config
        self.mem0 = mem0 or build_mem0(config)
        self.classifier = classifier or DomainClassifier(config)
        self.user_id = config["MEM0_USER_ID"]

    @staticmethod
    def validate(item):
        category = item.get("category")
        if category not in CATEGORIES: raise ValueError(f"invalid category: {category}")
        if category == "relationship" and item.get("subtype") not in RELATIONSHIP_SUBTYPES:
            raise ValueError("relationship memory requires a supported subtype")
        if category != "relationship" and item.get("subtype") in RELATIONSHIP_SUBTYPES:
            raise ValueError("relationship subtype requires relationship category")
        if item.get("status", "active") not in STATUSES: raise ValueError("invalid status")
        if not 1 <= int(item.get("importance", 5)) <= 10: raise ValueError("importance must be between 1 and 10")
        text = str(item.get("memory_text", "")).strip()
        if not text: raise ValueError("memory_text is required")
        if len(text) > 4000: raise ValueError("one Memory cannot exceed 4000 characters")

    def add_inferred(self, raw_text, source="automatic"):
        if not str(raw_text).strip(): raise ValueError("raw_text is required")
        if len(str(raw_text)) > int(self.config.get("MAX_RAW_TEXT_CHARS", 24000)):
            raise ValueError("raw_text exceeds configured extraction limit")
        result = self.mem0.add(raw_text, user_id=self.user_id, metadata={"source": source, "status": "active", "xiaxia_schema": "v1"}, infer=True)
        added = result.get("results", [])
        if not added: return []
        classifications = self.classifier.classify([item["memory"] for item in added])
        completed = []
        try:
            for memory, classification in zip(added, classifications):
                domain = self._domain_from(memory["id"], classification, source)
                self.mem0.update(memory["id"], metadata=self._mem0_metadata(domain))
                row = self.repository.create(domain)
                completed.append(self._merge(memory, row))
            return completed
        except Exception:
            for memory in added:
                try: self.mem0.delete(memory["id"])
                except Exception: pass
                try: self.repository.compensate_failed_create(memory["id"])
                except Exception: pass
            raise

    def add_structured(self, item, import_event=False):
        self.validate(item)
        occurred_at = item.get("occurred_at") or datetime.now(timezone.utc).isoformat()
        seed = {**item, "occurred_at": occurred_at}
        source = item.get("source", "custom_gpt")
        normalized = self._domain_from("pending", seed, source)
        result = self.mem0.add(item["memory_text"].strip(), user_id=self.user_id, metadata=self._mem0_metadata(normalized), infer=False)
        added = result.get("results", [])
        if len(added) != 1: raise RuntimeError("structured Mem0 add did not return exactly one Memory")
        mem0_id = added[0]["id"]
        domain = {**normalized, "mem0_id": str(mem0_id)}
        try:
            row = self.repository.create(domain, "imported" if import_event else "created")
            if item.get("supersedes"):
                row = self._apply_supersede(item["supersedes"], mem0_id, item.get("source", "custom_gpt"))
            return self._merge(added[0], row)
        except Exception:
            try: self.mem0.delete(mem0_id)
            except Exception: pass
            try: self.repository.compensate_failed_create(mem0_id)
            except Exception: pass
            raise

    def search(self, query, filters, top_k=6, include_historical=False):
        top_k = max(1, min(int(top_k), 20))
        mem_filters = {"user_id": self.user_id}
        if not include_historical: mem_filters["status"] = filters.get("status", "active")
        if filters.get("category"): mem_filters["category"] = filters["category"]
        if filters.get("subtype"): mem_filters["subtype"] = filters["subtype"]
        if filters.get("min_importance") is not None: mem_filters["importance"] = {"gte": int(filters["min_importance"])}
        if filters.get("from"): mem_filters["occurred_at_epoch"] = {"gte": self._as_epoch(filters["from"])}
        if filters.get("to"):
            existing = mem_filters.get("occurred_at_epoch", {})
            mem_filters["occurred_at_epoch"] = {**existing, "lte": self._as_epoch(filters["to"])}
        if str(query).strip():
            raw = self.mem0.search(query, filters=mem_filters, top_k=min(top_k * 4, 80), threshold=0.0).get("results", [])
        else:
            raw = self.mem0.get_all(filters=mem_filters, top_k=min(top_k * 4, 80)).get("results", [])
        domains = self.repository.get_many([item["id"] for item in raw])
        results = []
        for item in raw:
            domain = domains.get(str(item["id"]))
            if not domain: continue
            if not include_historical and domain["status"] != filters.get("status", "active"): continue
            if filters.get("subtype") and domain["subtype"] != filters["subtype"]: continue
            if filters.get("min_importance") is not None and domain["importance"] < int(filters["min_importance"]): continue
            results.append(self._merge(item, domain))
            if len(results) >= top_k: break
        return results

    def get(self, mem0_id, include_deleted=False):
        domain = self.repository.get(mem0_id, include_deleted=include_deleted)
        if not domain: return None
        try: memory = self.mem0.get(str(mem0_id))
        except Exception: memory = None
        if memory is None and not include_deleted: return None
        return self._merge(memory or {"id": str(mem0_id), "memory": None}, domain)

    def update(self, mem0_id, memory_text, changes, actor="viewer"):
        self.validate({"memory_text": memory_text, **changes})
        old_memory = self.mem0.get(str(mem0_id)); old_domain = self.repository.get(mem0_id)
        if not old_memory or not old_domain: raise ValueError("Memory not found")
        merged = {**dict(old_domain), **changes}
        self.mem0.update(str(mem0_id), text=memory_text, metadata=self._mem0_metadata(merged))
        try:
            row = self.repository.update(mem0_id, changes, old_memory.get("memory"), memory_text, actor)
            return self._merge(self.mem0.get(str(mem0_id)), row)
        except Exception:
            self.mem0.update(str(mem0_id), text=old_memory["memory"], metadata=self._mem0_metadata(old_domain)); raise

    def delete(self, mem0_id, actor="viewer"):
        memory = self.mem0.get(str(mem0_id)); before, _ = self.repository.mark_deleted(mem0_id, actor)
        try: self.mem0.delete(str(mem0_id))
        except Exception:
            self.repository.rollback_delete(before); raise
        self.repository.confirm_deleted(mem0_id, memory, actor)

    def recent_context(self, days=14, max_items=20):
        days = max(1, min(int(days), 90)); max_items = max(5, min(int(max_items), 40))
        sections = {"recent_relationship": [], "recent_shared_life": [], "xiaxia_development": [], "ongoing_threads": [], "important_recent_events": []}
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
        memories = self.mem0.get_all(filters={"user_id": self.user_id,
            "status": {"in": ["active", "historical"]}, "occurred_at_epoch": {"gte": cutoff}},
            top_k=min(max_items * 2, 80)).get("results", [])
        domains = self.repository.get_many([memory["id"] for memory in memories])
        candidates = [(memory, domains.get(str(memory["id"]))) for memory in memories]
        candidates = [(memory, row) for memory, row in candidates if row and row["status"] in {"active", "historical"}]
        candidates.sort(key=lambda pair: (pair[1]["importance"], str(pair[1]["occurred_at"])), reverse=True)
        for memory, row in candidates[:max_items]:
            item = self._merge(memory, row)
            if row["category"] == "relationship": sections["recent_relationship"].append(item)
            elif row["category"] == "ongoing": sections["ongoing_threads"].append(item)
            elif row["subtype"] == "identity_shift" or (row.get("metadata") or {}).get("subject") == "xiaxia": sections["xiaxia_development"].append(item)
            elif row["category"] == "episodic": sections["important_recent_events"].append(item)
            else: sections["recent_shared_life"].append(item)
        return sections

    def list_admin(self, filters, limit=100):
        limit = max(1, min(int(limit), 100))
        mem_filters = {"user_id": self.user_id}
        for key in ("category", "status"):
            if filters.get(key): mem_filters[key] = filters[key]
        if filters.get("from"): mem_filters["occurred_at_epoch"] = {"gte": self._as_epoch(filters["from"])}
        if filters.get("to"):
            existing = mem_filters.get("occurred_at_epoch", {})
            mem_filters["occurred_at_epoch"] = {**existing, "lte": self._as_epoch(filters["to"])}
        if filters.get("q"):
            memories = self.mem0.search(filters["q"], filters=mem_filters, top_k=limit, threshold=0.0).get("results", [])
        else:
            memories = self.mem0.get_all(filters=mem_filters, top_k=limit).get("results", [])
        domains = self.repository.get_many([memory["id"] for memory in memories])
        output = [self._merge(memory, domains[str(memory["id"])]) for memory in memories if str(memory["id"]) in domains]
        output.sort(key=lambda row: str(row["occurred_at"]), reverse=True)
        return output[:limit]

    def history(self, mem0_id): return self.repository.history(mem0_id)

    def archive_period(self, period_label, items, metadata=None):
        if not items or len(items) > 100: raise ValueError("Legacy Import requires 1 to 100 memories per batch")
        saved = []
        try:
            for item in items:
                normalized = " ".join(str(item.get("memory_text", "")).split()).casefold()
                identity = "|".join((str(item.get("category")), str(item.get("subtype")), str(item.get("occurred_at")), normalized))
                import_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
                duplicate = self.repository.find_by_import_key(import_key)
                if duplicate:
                    existing = self.get(duplicate["mem0_id"])
                    if existing: saved.append(existing); continue
                enriched = {**item, "source": item.get("source", "legacy_window"), "metadata": {
                    **item.get("metadata", {}), "period_label": period_label, "legacy_import_key": import_key}}
                saved.append(self.add_structured(enriched, import_event=True))
            self.repository.create_import_batch(period_label, len(saved), metadata or {})
            return saved
        except Exception:
            for row in saved:
                try: self.delete(row["id"], actor="legacy_import_rollback")
                except Exception: pass
            raise

    def _apply_supersede(self, old_id, new_id, actor):
        old = self.mem0.get(str(old_id)); new = self.mem0.get(str(new_id))
        if not old or not new: raise ValueError("supersede target not found in Mem0")
        old_domain = self.repository.get(old_id)
        self.mem0.update(str(old_id), metadata={**self._mem0_metadata(old_domain), "status": "superseded", "superseded_by": str(new_id)})
        try:
            _, new_row = self.repository.supersede(old_id, new_id, actor)
            return new_row
        except Exception:
            self.mem0.update(str(old_id), metadata=self._mem0_metadata(old_domain)); raise

    def _domain_from(self, mem0_id, values, source):
        category, subtype = values.get("category", "semantic"), values.get("subtype")
        if category == "relationship" and subtype not in RELATIONSHIP_SUBTYPES: subtype = "relationship_dynamic"
        if category not in CATEGORIES: category, subtype = "semantic", None
        return {"mem0_id": str(mem0_id), "category": category, "subtype": subtype,
            "importance": max(1, min(int(values.get("importance", 5)), 10)),
            "occurred_at": values.get("occurred_at") or datetime.now(timezone.utc).isoformat(),
            "source": source, "status": values.get("status", "active"), "supersedes": values.get("supersedes"),
            "superseded_by": values.get("superseded_by"), "metadata": values.get("metadata", {})}

    @staticmethod
    def _mem0_metadata(domain):
        data = dict(domain.get("metadata") or {})
        data.update({key: domain.get(key) for key in ("category", "subtype", "importance", "occurred_at", "source", "status", "supersedes", "superseded_by") if domain.get(key) is not None})
        data["occurred_at_epoch"] = MemoryEngine._as_epoch(domain.get("occurred_at"))
        data["xiaxia_schema"] = "v1"; return data

    @staticmethod
    def _as_epoch(value):
        if isinstance(value, datetime): return value.timestamp()
        if value is None: return datetime.now(timezone.utc).timestamp()
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()

    @staticmethod
    def _merge(memory, domain):
        row = dict(domain); row["id"] = str(row.pop("mem0_id")); row["memory_text"] = memory.get("memory") if memory else None
        if memory and memory.get("score") is not None: row["relevance"] = memory["score"]
        return row
