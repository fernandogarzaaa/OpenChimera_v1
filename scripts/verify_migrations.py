"""Verify all SQL migrations apply cleanly against a fresh in-memory SQLite DB."""
import sqlite3
import pathlib

db = sqlite3.connect(":memory:")
db.execute("PRAGMA foreign_keys=ON")

for f in sorted(pathlib.Path("core/migrations").glob("*.sql")):
    print(f"Applying {f.name}...")
    db.executescript(f.read_text())
    print("  OK")

tables = [
    r[0]
    for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
]
print(f"\nAll tables: {tables}")

indexes = [
    r[0]
    for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
]
print(f"All indexes ({len(indexes)}): {indexes}")

# Spot-check FK constraint on episode_postmortems
try:
    db.execute(
        "INSERT INTO episode_postmortems (id, episode_id, timestamp, failure_mode, prevention_hypothesis) "
        "VALUES ('pm1','DOES_NOT_EXIST',1,'test','test')"
    )
    db.commit()
    print("FK FAIL - orphan insert succeeded")
except Exception as e:
    print(f"FK OK - correctly rejected: {e}")

# Spot-check goal_dependencies FK
try:
    db.execute(
        "INSERT INTO goal_dependencies (goal_id, depends_on_id) VALUES ('NOPE1','NOPE2')"
    )
    db.commit()
    print("FK FAIL - orphan dep insert succeeded")
except Exception as e:
    print(f"FK OK - goal_dep rejected: {e}")

# Spot-check kg_assertions FK
try:
    db.execute(
        "INSERT INTO kg_assertions (id, subject, predicate, object, asserted_by, valid_from) "
        "VALUES ('a1','no','no','no','test',1)"
    )
    db.commit()
    print("FK FAIL - orphan assertion succeeded")
except Exception as e:
    print(f"FK OK - assertion rejected: {e}")

# Check constraint on episodes.outcome
try:
    db.execute(
        "INSERT INTO episodes (id, session_id, timestamp, goal, outcome) "
        "VALUES ('e1','s1',1,'test','INVALID')"
    )
    db.commit()
    print("CHECK FAIL - invalid outcome accepted")
except Exception as e:
    print(f"CHECK OK - bad outcome rejected: {e}")

# Check constraint on goals.status
try:
    db.execute(
        "INSERT INTO goals (id, description, status, created_at, updated_at) "
        "VALUES ('g1','test','BADSTATUS',1,1)"
    )
    db.commit()
    print("CHECK FAIL - invalid status accepted")
except Exception as e:
    print(f"CHECK OK - bad status rejected: {e}")

print("\nMigration verification complete.")
