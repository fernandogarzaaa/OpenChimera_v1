-- core/migrations/004_goal_planner.sql
-- Hierarchical goal planner: HTN-style goal decomposition.

CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY,
    parent_id TEXT REFERENCES goals(id) ON DELETE CASCADE,
    depth INTEGER NOT NULL DEFAULT 0 CHECK (depth >= 0 AND depth <= 8),
    description TEXT NOT NULL,
    domain TEXT NOT NULL DEFAULT 'general'
        CHECK (domain IN ('code', 'math', 'reasoning', 'creative', 'general')),
    preconditions TEXT NOT NULL DEFAULT '[]',     -- JSON array of precondition strings
    postconditions TEXT NOT NULL DEFAULT '[]',    -- JSON array of postcondition strings
    success_criteria TEXT NOT NULL DEFAULT '[]',  -- JSON array of criteria strings
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'active', 'completed', 'failed', 'blocked')),
    assigned_model TEXT,
    result TEXT,                                  -- JSON: outcome summary
    confidence REAL NOT NULL DEFAULT 0.0 CHECK (confidence >= 0.0 AND confidence <= 1.0),
    max_depth INTEGER NOT NULL DEFAULT 4,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_goals_parent_id ON goals(parent_id);
CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status);
CREATE INDEX IF NOT EXISTS idx_goals_domain ON goals(domain);
CREATE INDEX IF NOT EXISTS idx_goals_created_at ON goals(created_at DESC);

CREATE TABLE IF NOT EXISTS goal_dependencies (
    goal_id TEXT NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    depends_on_id TEXT NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    PRIMARY KEY (goal_id, depends_on_id)
);

CREATE INDEX IF NOT EXISTS idx_goal_deps_depends_on ON goal_dependencies(depends_on_id);
