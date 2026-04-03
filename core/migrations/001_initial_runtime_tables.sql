CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    job_class TEXT NOT NULL,
    label TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    history_json TEXT NOT NULL DEFAULT '[]',
    result_json TEXT,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS query_sessions (
    session_id TEXT PRIMARY KEY,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    title TEXT NOT NULL,
    permission_scope TEXT NOT NULL,
    turns_json TEXT NOT NULL DEFAULT '[]',
    task_snapshots_json TEXT NOT NULL DEFAULT '[]',
    last_result_json TEXT
);

CREATE TABLE IF NOT EXISTS subscriptions (
    subscription_id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    topics_json TEXT NOT NULL DEFAULT '[]',
    config_json TEXT NOT NULL DEFAULT '{}',
    last_validation_json TEXT
);

CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id TEXT,
    topic TEXT NOT NULL,
    dispatched_at INTEGER NOT NULL,
    delivery_count INTEGER NOT NULL DEFAULT 0,
    delivered_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    payload_preview_json TEXT NOT NULL DEFAULT '{}',
    results_json TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY(subscription_id) REFERENCES subscriptions(subscription_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS autonomy_artifacts (
    artifact_name TEXT NOT NULL,
    recorded_at REAL NOT NULL,
    generated_at TEXT,
    status TEXT,
    summary TEXT,
    payload_json TEXT,
    path TEXT,
    job_name TEXT,
    PRIMARY KEY (artifact_name, recorded_at)
);

CREATE TABLE IF NOT EXISTS credentials (
    provider_id TEXT NOT NULL,
    credential_key TEXT NOT NULL,
    credential_value TEXT NOT NULL,
    PRIMARY KEY (provider_id, credential_key)
);

CREATE TABLE IF NOT EXISTS query_tool_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    query_type TEXT NOT NULL,
    suggested_tools_json TEXT NOT NULL DEFAULT '[]',
    recorded_at INTEGER NOT NULL,
    event_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_status_created_at ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_query_sessions_updated_at ON query_sessions(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_channels_topic_dispatched_at ON channels(topic, dispatched_at DESC);
CREATE INDEX IF NOT EXISTS idx_tool_history_session_id ON query_tool_history(session_id, recorded_at DESC);