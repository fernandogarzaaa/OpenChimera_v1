-- core/migrations/002_episodic_memory.sql
-- Episodic memory: records full deliberation episodes and postmortems.

CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    goal TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('success', 'failure', 'partial')),
    confidence_initial REAL NOT NULL DEFAULT 0.0,
    confidence_final REAL NOT NULL DEFAULT 0.0,
    models_used TEXT NOT NULL DEFAULT '[]',         -- JSON array of model id strings
    reasoning_chain TEXT NOT NULL DEFAULT '[]',      -- JSON array of step strings
    failure_reason TEXT,                             -- null on success
    domain TEXT NOT NULL DEFAULT 'general'
        CHECK (domain IN ('code', 'math', 'reasoning', 'creative', 'general')),
    embedding BLOB,                                  -- sentence-transformers vector bytes
    curated INTEGER NOT NULL DEFAULT 0               -- boolean: has curator scored this?
);

CREATE INDEX IF NOT EXISTS idx_episodes_session_id ON episodes(session_id);
CREATE INDEX IF NOT EXISTS idx_episodes_domain_outcome ON episodes(domain, outcome);
CREATE INDEX IF NOT EXISTS idx_episodes_timestamp ON episodes(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_episodes_curated ON episodes(curated, timestamp);

CREATE TABLE IF NOT EXISTS episode_postmortems (
    id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    timestamp INTEGER NOT NULL,
    failure_mode TEXT NOT NULL,
    contributing_models TEXT NOT NULL DEFAULT '[]',   -- JSON array
    correct_reasoning TEXT,
    prevention_hypothesis TEXT NOT NULL,
    knowledge_gap_description TEXT,
    confidence_at_failure REAL NOT NULL DEFAULT 0.0,
    similar_past_failures TEXT NOT NULL DEFAULT '[]', -- JSON array of episode ids
    incorporated_into_training INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_postmortems_episode_id ON episode_postmortems(episode_id);
CREATE INDEX IF NOT EXISTS idx_postmortems_failure_mode ON episode_postmortems(failure_mode);
