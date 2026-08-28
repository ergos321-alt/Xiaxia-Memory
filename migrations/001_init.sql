CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Mem0 2.0.19 authoritative collections. Pre-created so request paths never
-- execute CREATE TABLE / CREATE INDEX. Names must match MEM0_COLLECTION.
CREATE TABLE IF NOT EXISTS xiaxia_mem0_memories (
    id uuid PRIMARY KEY,
    vector vector(1024),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS xiaxia_mem0_memories_hnsw_idx
ON xiaxia_mem0_memories USING hnsw (vector vector_cosine_ops);
CREATE INDEX IF NOT EXISTS xiaxia_mem0_memories_text_lemmatized_idx
ON xiaxia_mem0_memories USING gin(to_tsvector('simple', payload->>'text_lemmatized'));

CREATE TABLE IF NOT EXISTS xiaxia_mem0_memories_entities (
    id uuid PRIMARY KEY,
    vector vector(1024),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS xiaxia_mem0_memories_entities_hnsw_idx
ON xiaxia_mem0_memories_entities USING hnsw (vector vector_cosine_ops);

-- Xiaxia Domain Layer: deliberately contains no Memory body or vector.
CREATE TABLE IF NOT EXISTS memory_domain (
    mem0_id uuid PRIMARY KEY,
    category text NOT NULL CHECK (category IN ('semantic','episodic','relationship','taste','ongoing')),
    subtype text,
    importance smallint NOT NULL DEFAULT 5 CHECK (importance BETWEEN 1 AND 10),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    source text NOT NULL DEFAULT 'custom_gpt',
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','historical','superseded','archived')),
    supersedes uuid REFERENCES memory_domain(mem0_id) ON DELETE SET NULL,
    superseded_by uuid REFERENCES memory_domain(mem0_id) ON DELETE SET NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz
);
CREATE INDEX IF NOT EXISTS memory_domain_recent_idx ON memory_domain(occurred_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS memory_domain_category_recent_idx ON memory_domain(category,occurred_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS memory_domain_status_importance_idx ON memory_domain(status,importance DESC,occurred_at DESC);
CREATE INDEX IF NOT EXISTS memory_domain_subtype_idx ON memory_domain(category,subtype);
CREATE UNIQUE INDEX IF NOT EXISTS memory_domain_legacy_import_key_idx
ON memory_domain((metadata->>'legacy_import_key'))
WHERE deleted_at IS NULL AND metadata ? 'legacy_import_key';

CREATE TABLE IF NOT EXISTS memory_audit_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    mem0_id uuid NOT NULL REFERENCES memory_domain(mem0_id) ON DELETE RESTRICT,
    event_type text NOT NULL,
    before_state jsonb,
    after_state jsonb,
    actor text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS memory_audit_mem0_idx ON memory_audit_events(mem0_id,created_at);

CREATE TABLE IF NOT EXISTS memory_import_batches (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    period_label text NOT NULL,
    source text NOT NULL DEFAULT 'legacy_window',
    created_at timestamptz NOT NULL DEFAULT now(),
    item_count integer NOT NULL DEFAULT 0,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- Preserve an unreleased V1 self-built table for one-time import only. Runtime
-- code never reads it; after verified import it may be dropped manually.
DO $$ BEGIN
    IF to_regclass('public.memories') IS NOT NULL AND to_regclass('public.legacy_v1_memories') IS NULL THEN
        ALTER TABLE memories RENAME TO legacy_v1_memories;
    END IF;
END $$;
