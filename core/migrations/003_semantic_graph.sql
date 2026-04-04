-- core/migrations/003_semantic_graph.sql
-- Semantic memory: knowledge-graph triples and temporal assertions.

CREATE TABLE IF NOT EXISTS kg_triples (
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0 CHECK (confidence >= 0.0 AND confidence <= 1.0),
    source TEXT NOT NULL DEFAULT 'unknown',
    timestamp INTEGER NOT NULL,
    PRIMARY KEY (subject, predicate, object)
);

CREATE INDEX IF NOT EXISTS idx_kg_triples_subject ON kg_triples(subject);
CREATE INDEX IF NOT EXISTS idx_kg_triples_predicate ON kg_triples(predicate);
CREATE INDEX IF NOT EXISTS idx_kg_triples_object ON kg_triples(object);

CREATE TABLE IF NOT EXISTS kg_assertions (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    asserted_by TEXT NOT NULL,
    valid_from INTEGER NOT NULL,
    valid_until INTEGER,  -- null = still valid
    FOREIGN KEY (subject, predicate, object)
        REFERENCES kg_triples(subject, predicate, object) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_kg_assertions_valid ON kg_assertions(valid_until);
CREATE INDEX IF NOT EXISTS idx_kg_assertions_triple
    ON kg_assertions(subject, predicate, object);
