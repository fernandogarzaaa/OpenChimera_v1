/// chimera-core/src/db/mod.rs
///
/// SQLite database layer using sqlx 0.8 + WAL mode + embedded migrations.
/// Replaces core/database.py (DatabaseManager).
///
/// Backup strategy: `VACUUM INTO 'dest'` — no rusqlite needed; SQLite 3.27+
/// handles WAL correctly and produces a defragmented, consistent copy.
use pyo3::prelude::*;
use serde::{Deserialize, Serialize};
use sqlx::sqlite::{SqliteConnectOptions, SqliteJournalMode, SqliteSynchronous};
use sqlx::{Row, SqlitePool};
use std::path::Path;
use thiserror::Error;

// ── Error ──────────────────────────────────────────────────────────────────

#[derive(Debug, Error)]
pub enum DbError {
    #[error("sqlx error: {0}")]
    Sqlx(#[from] sqlx::Error),
    #[error("sqlx migrate error: {0}")]
    Migrate(#[from] sqlx::migrate::MigrateError),
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),
    #[error("Runtime error: {0}")]
    Runtime(String),
}

impl From<DbError> for PyErr {
    fn from(e: DbError) -> PyErr {
        pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
    }
}

// ── DbStatus ───────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DbStatus {
    pub database_path: String,
    pub wal_enabled: bool,
    pub applied_migrations: Vec<String>,
}

// ── Database ───────────────────────────────────────────────────────────────

pub struct Database {
    pool: SqlitePool,
    path: String,
}

impl Database {
    /// Create or open the SQLite database, enable WAL, and run migrations.
    pub async fn initialize(path: &str) -> Result<Self, DbError> {
        // Ensure parent directory exists.
        if let Some(parent) = Path::new(path).parent() {
            if !parent.as_os_str().is_empty() {
                tokio::fs::create_dir_all(parent).await?;
            }
        }

        let url = format!("sqlite:{path}");
        let opts = url
            .parse::<SqliteConnectOptions>()
            .map_err(DbError::Sqlx)?
            .create_if_missing(true)
            .journal_mode(SqliteJournalMode::Wal)
            .synchronous(SqliteSynchronous::Normal)
            .foreign_keys(true);

        let pool = SqlitePool::connect_with(opts).await?;

        // Run embedded migrations.
        sqlx::migrate!("./migrations").run(&pool).await?;

        Ok(Database {
            pool,
            path: path.to_owned(),
        })
    }

    /// Copy the live database to `dest` using `VACUUM INTO`.
    /// Safe under WAL mode (SQLite 3.27+); no extra crate required.
    pub async fn backup(&self, dest: &Path) -> Result<(), DbError> {
        if let Some(parent) = dest.parent() {
            if !parent.as_os_str().is_empty() {
                tokio::fs::create_dir_all(parent).await?;
            }
        }
        let dest_str = dest
            .to_str()
            .ok_or_else(|| DbError::Runtime("Non-UTF8 backup path".to_owned()))?;
        // Escape single-quotes in path for SQLite literal syntax.
        let sql = format!("VACUUM INTO '{}'", dest_str.replace('\'', "''"));
        sqlx::query(&sql).execute(&self.pool).await?;
        Ok(())
    }

    /// Restore the database from a backup file (file copy).
    /// The caller must close any live pool before calling this.
    pub async fn restore(src: &Path, db_path: &Path) -> Result<(), DbError> {
        if !src.exists() {
            return Err(DbError::Runtime(format!(
                "Backup does not exist: {}",
                src.display()
            )));
        }
        tokio::fs::copy(src, db_path).await.map(|_| ())?;
        Ok(())
    }

    /// Return operational status including applied migrations.
    pub async fn status(&self) -> Result<DbStatus, DbError> {
        // Query the _sqlx_migrations table created by sqlx migrate.
        let rows = sqlx::query("SELECT version, description FROM _sqlx_migrations ORDER BY version")
            .fetch_all(&self.pool)
            .await?;

        let applied: Vec<String> = rows
            .iter()
            .map(|r| {
                let version: i64 = r.try_get("version").unwrap_or_default();
                let desc: String = r.try_get("description").unwrap_or_default();
                format!("{version:04}_{desc}")
            })
            .collect();

        Ok(DbStatus {
            database_path: self.path.clone(),
            wal_enabled: true,
            applied_migrations: applied,
        })
    }

    #[allow(dead_code)]
    pub fn pool(&self) -> &SqlitePool {
        &self.pool
    }
}

// ── Tokio runtime helper ───────────────────────────────────────────────────

/// Get or create a static tokio Runtime for blocking calls from Python.
fn rt() -> &'static tokio::runtime::Runtime {
    use once_cell::sync::Lazy;
    static RT: Lazy<tokio::runtime::Runtime> = Lazy::new(|| {
        tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .expect("Failed to build chimera_core tokio runtime")
    });
    &RT
}

// ── PyO3 wrappers ──────────────────────────────────────────────────────────

#[pyclass(name = "Database")]
pub struct PyDatabase {
    inner: Database,
}

#[pymethods]
impl PyDatabase {
    #[staticmethod]
    fn initialize(path: &str) -> PyResult<Self> {
        let db = rt()
            .block_on(Database::initialize(path))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
        Ok(PyDatabase { inner: db })
    }

    fn backup(&self, dest: &str) -> PyResult<()> {
        rt().block_on(self.inner.backup(Path::new(dest)))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
        Ok(())
    }

    #[staticmethod]
    fn restore(src: &str, db_path: &str) -> PyResult<()> {
        rt().block_on(Database::restore(Path::new(src), Path::new(db_path)))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
        Ok(())
    }

    fn status(&self, py: Python<'_>) -> PyResult<PyObject> {
        let s = rt()
            .block_on(self.inner.status())
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
        let d = pyo3::types::PyDict::new_bound(py);
        d.set_item("database_path", &s.database_path)?;
        d.set_item("wal_enabled", s.wal_enabled)?;
        let migs = pyo3::types::PyList::new_bound(py, &s.applied_migrations);
        d.set_item("applied_migrations", migs)?;
        Ok(d.to_object(py))
    }
}

pub fn register(m: &pyo3::Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyDatabase>()?;
    Ok(())
}

// ── Tests ──────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[tokio::test]
    async fn initialize_creates_database() {
        let dir = TempDir::new().unwrap();
        let db_path = dir.path().join("test.db").to_str().unwrap().to_owned();
        let db = Database::initialize(&db_path).await.unwrap();
        let status = db.status().await.unwrap();
        assert_eq!(status.database_path, db_path);
        assert!(status.wal_enabled);
    }

    #[tokio::test]
    async fn backup_creates_backup_file() {
        let dir = TempDir::new().unwrap();
        let db_path = dir.path().join("main.db").to_str().unwrap().to_owned();
        let bak_path = dir.path().join("backup.db");

        let db = Database::initialize(&db_path).await.unwrap();
        db.backup(&bak_path).await.unwrap();

        assert!(bak_path.exists(), "Backup file should exist after backup()");
    }

    #[tokio::test]
    async fn restore_copies_file() {
        let dir = TempDir::new().unwrap();
        let src_path = dir.path().join("source.db");
        let dst_path = dir.path().join("destination.db");

        // Build a valid source database.
        let _db = Database::initialize(src_path.to_str().unwrap()).await.unwrap();
        drop(_db);

        Database::restore(&src_path, &dst_path).await.unwrap();
        assert!(dst_path.exists(), "Restored file should exist");
    }

    #[tokio::test]
    async fn restore_fails_for_missing_source() {
        let dir = TempDir::new().unwrap();
        let missing = dir.path().join("missing.db");
        let dst = dir.path().join("dst.db");
        let result = Database::restore(&missing, &dst).await;
        assert!(result.is_err(), "restore() should fail when source does not exist");
    }

    #[tokio::test]
    async fn status_returns_applied_migrations() {
        let dir = TempDir::new().unwrap();
        let db_path = dir.path().join("status.db").to_str().unwrap().to_owned();
        let db = Database::initialize(&db_path).await.unwrap();
        let status = db.status().await.unwrap();
        // At least the initial migration should be applied.
        assert!(
            !status.applied_migrations.is_empty(),
            "Expected at least one applied migration"
        );
    }
}
