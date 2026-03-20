import psycopg2
import json
import os
import sys

# Configuration for MCP Postgres database
DB_CONFIG = {
    "dbname": "mcp",
    "user": "postgres",
    "password": "password", # Default local development password
    "host": "localhost",
    "port": "8000"
}

def get_connection():
    return psycopg2.connect(**DB_CONFIG)

def init_db():
    """Ensure the checkpoints table exists."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS swarm_checkpoints (
            id SERIAL PRIMARY KEY,
            swarm_id TEXT NOT NULL,
            state JSONB NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

def save_checkpoint(swarm_id, state_data):
    """Saves the state of an active swarm to the checkpoint table."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO swarm_checkpoints (swarm_id, state) VALUES (%s, %s)",
            (swarm_id, json.dumps(state_data))
        )
        conn.commit()
        cur.close()
        conn.close()
        print(f"Checkpoint saved for swarm: {swarm_id}")
    except Exception as e:
        print(f"Failed to save checkpoint: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python checkpoint_manager.py <swarm_id> <json_state_file_path>")
        sys.exit(1)
        
    swarm_id = sys.argv[1]
    state_file = sys.argv[2]
    
    with open(state_file, 'r') as f:
        state_data = json.load(f)
        
    init_db()
    save_checkpoint(swarm_id, state_data)
