from pathlib import Path
import yaml

ROOT = Path(__file__).parents[1]


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values(): yield from walk(child)
    elif isinstance(value, list):
        for child in value: yield from walk(child)


def test_openapi_has_no_array_type_or_complex_schema():
    schema = yaml.safe_load((ROOT / "openapi.yaml").read_text())
    operation_ids = []
    for node in walk(schema):
        if "type" in node: assert not isinstance(node["type"], list)
        assert "oneOf" not in node
        assert "allOf" not in node
        assert "discriminator" not in node
        if "operationId" in node: operation_ids.append(node["operationId"])
    assert len(operation_ids) == len(set(operation_ids)) == 4
    assert "variables" not in schema["servers"][0]


def test_schema_work_is_not_in_request_code():
    app_text = "\n".join(p.read_text() for p in (ROOT / "app").glob("*.py"))
    assert "CREATE TABLE" not in app_text.upper()
    assert "CREATE INDEX" not in app_text.upper()


def test_required_indexes_exist():
    sql = (ROOT / "migrations" / "001_init.sql").read_text().lower()
    assert "using hnsw" in sql
    assert "memory_domain(category,occurred_at desc)" in sql
    assert "memory_domain(status,importance desc,occurred_at desc)" in sql


def test_mem0_is_authoritative_and_old_engine_is_absent():
    engine = (ROOT / "app" / "memory_engine.py").read_text()
    requirements = (ROOT / "requirements.txt").read_text()
    assert "self.mem0.add" in engine
    assert "self.mem0.search" in engine
    assert "self.mem0.update" in engine
    assert "self.mem0.delete" in engine
    assert "Memory.from_config" in engine
    assert "._ensure_collection" not in engine
    assert "embeddings.create" not in engine
    assert "xiaxia_mem0_engine" not in engine
    assert "mem0ai==2.0.19" in requirements
    assert "mem0ai==0.1.118" not in requirements


def test_domain_ledger_stores_no_memory_body_or_vector():
    sql = (ROOT / "migrations" / "001_init.sql").read_text().lower()
    ledger = sql.split("create table if not exists memory_domain", 1)[1].split(");", 1)[0]
    assert "memory_text" not in ledger
    assert " vector" not in ledger


def test_mem0_2019_provider_config_fields_are_supported():
    from mem0.configs.embeddings.base import BaseEmbedderConfig
    from mem0.configs.llms.openai import OpenAIConfig
    from mem0.configs.vector_stores.pgvector import PGVectorConfig

    llm = OpenAIConfig(model="qwen-flash", api_key="test", openai_base_url="https://qwen.example/v1", temperature=0.1)
    embedder = BaseEmbedderConfig(model="text-embedding-v4", api_key="test",
        openai_base_url="https://qwen.example/v1", embedding_dims=1024)
    vector = PGVectorConfig(connection_string="postgresql://u:p@localhost/db",
        collection_name="xiaxia_mem0_memories", embedding_model_dims=1024,
        hnsw=True, diskann=False, minconn=1, maxconn=2, sslmode="require")

    assert llm.openai_base_url.endswith("/v1")
    assert embedder.embedding_dims == vector.embedding_model_dims == 1024
    assert vector.connection_string.startswith("postgresql://")
    assert (vector.minconn, vector.maxconn, vector.sslmode) == (1, 2, "require")
