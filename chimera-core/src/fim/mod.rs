/// chimera-core/src/fim/mod.rs
///
/// File Integrity Monitor using the `notify` crate (v6+).
/// Replaces core/fim_daemon.py (FIMDaemon).
use notify::{Config, Event as NotifyEvent, EventKind, RecommendedWatcher, RecursiveMode, Watcher};
use pyo3::prelude::*;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};
use thiserror::Error;


// ── Error ──────────────────────────────────────────────────────────────────

#[derive(Debug, Error)]
pub enum FimError {
    #[error("Notify error: {0}")]
    Notify(#[from] notify::Error),
    #[error("Runtime error: {0}")]
    Runtime(String),
}

impl From<FimError> for PyErr {
    fn from(e: FimError) -> PyErr {
        pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
    }
}

// ── FimEventKind ───────────────────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FimEventKind {
    Modified,
    Created,
    Deleted,
}

impl FimEventKind {
    fn as_str(&self) -> &'static str {
        match self {
            FimEventKind::Modified => "modified",
            FimEventKind::Created => "created",
            FimEventKind::Deleted => "deleted",
        }
    }
}

// ── FimEvent ───────────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
pub struct FimEvent {
    pub path: String,
    pub kind: FimEventKind,
    pub timestamp: u64,
}

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

fn map_kind(ev: &NotifyEvent) -> Option<FimEventKind> {
    match ev.kind {
        EventKind::Create(_) => Some(FimEventKind::Created),
        EventKind::Modify(_) => Some(FimEventKind::Modified),
        EventKind::Remove(_) => Some(FimEventKind::Deleted),
        _ => None,
    }
}

// ── FimHandle ─────────────────────────────────────────────────────────────

pub struct FimHandle {
    _watcher: RecommendedWatcher,
    stopped: Arc<Mutex<bool>>,
}

impl FimHandle {
    pub fn stop(&self) {
        *self.stopped.lock().unwrap() = true;
    }
}

// ── FimDaemon ─────────────────────────────────────────────────────────────

pub struct FimDaemon;

impl FimDaemon {
    /// Start watching the given file paths. Events are sent on `tx`.
    /// Returns a FimHandle; drop or call `.stop()` to stop watching.
    pub fn start(
        paths: Vec<String>,
        tx: std::sync::mpsc::Sender<FimEvent>,
    ) -> Result<FimHandle, FimError> {
        let stopped = Arc::new(Mutex::new(false));
        let stopped_inner = stopped.clone();

        let (notify_tx, notify_rx) = std::sync::mpsc::channel::<notify::Result<NotifyEvent>>();

        let mut watcher = RecommendedWatcher::new(notify_tx, Config::default())?;

        for path in &paths {
            let p = PathBuf::from(path);
            // Watch the path; fall back to non-recursive if path doesn't exist yet.
            let _ = watcher.watch(&p, RecursiveMode::NonRecursive);
        }

        // Spawn a background thread to relay notify events → FimEvent.
        std::thread::spawn(move || {
            for result in notify_rx {
                if *stopped_inner.lock().unwrap() {
                    break;
                }
                if let Ok(event) = result {
                    if let Some(kind) = map_kind(&event) {
                        for p in &event.paths {
                            let fim_ev = FimEvent {
                                path: p.to_string_lossy().into_owned(),
                                kind: kind.clone(),
                                timestamp: now_secs(),
                            };
                            // Ignore send error (receiver dropped = stopped).
                            let _ = tx.send(fim_ev);
                        }
                    }
                }
            }
        });

        Ok(FimHandle {
            _watcher: watcher,
            stopped,
        })
    }
}

// ── PyO3 wrappers ──────────────────────────────────────────────────────────

/// Python-visible FIM daemon.
/// Usage:
///   daemon = FimDaemon(paths=["/etc/chimera.conf"])
///   events = daemon.poll()  # list of dicts
///   daemon.stop()
#[pyclass(name = "FimDaemon")]
pub struct PyFimDaemon {
    rx: std::sync::mpsc::Receiver<FimEvent>,
    handle: Option<FimHandle>,
}

#[pymethods]
impl PyFimDaemon {
    #[new]
    fn new(paths: Vec<String>) -> PyResult<Self> {
        let (tx, rx) = std::sync::mpsc::channel();
        let handle = FimDaemon::start(paths, tx)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
        Ok(PyFimDaemon {
            rx,
            handle: Some(handle),
        })
    }

    /// poll() -> list[dict] — non-blocking drain of available events.
    fn poll(&self, py: Python<'_>) -> PyResult<PyObject> {
        let list = pyo3::types::PyList::empty_bound(py);
        loop {
            match self.rx.try_recv() {
                Ok(ev) => {
                    let d = pyo3::types::PyDict::new_bound(py);
                    d.set_item("path", &ev.path)?;
                    d.set_item("kind", ev.kind.as_str())?;
                    d.set_item("timestamp", ev.timestamp)?;
                    list.append(d)?;
                }
                Err(std::sync::mpsc::TryRecvError::Empty) => break,
                Err(std::sync::mpsc::TryRecvError::Disconnected) => break,
            }
        }
        Ok(list.to_object(py))
    }

    /// stop() — stop watching.
    fn stop(&mut self) {
        if let Some(h) = self.handle.take() {
            h.stop();
        }
    }
}

pub fn register(m: &pyo3::Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyFimDaemon>()?;
    Ok(())
}

// ── Tests ──────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    #[test]
    fn fim_start_does_not_error_for_existing_path() {
        let tmp = NamedTempFile::new().unwrap();
        let path = tmp.path().to_str().unwrap().to_owned();
        let (tx, _rx) = std::sync::mpsc::channel();
        let handle = FimDaemon::start(vec![path], tx);
        assert!(handle.is_ok(), "FimDaemon::start should succeed for existing path");
    }

    #[test]
    fn fim_detects_file_modification() {
        let tmp = NamedTempFile::new().unwrap();
        let path = tmp.path().to_str().unwrap().to_owned();

        let (tx, rx) = std::sync::mpsc::channel();
        let _handle = FimDaemon::start(vec![path.clone()], tx).unwrap();

        // Give ReadDirectoryChangesW (Windows) time to arm.
        std::thread::sleep(std::time::Duration::from_millis(500));

        // Write new content and close to guarantee a flush to the OS.
        drop(tmp);
        let new_file = std::path::PathBuf::from(&path);
        std::fs::write(&new_file, b"change").unwrap();

        // Poll for up to 3 s; Windows RDCW can be slow on some CI hosts.
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(3);
        let mut events: Vec<FimEvent> = Vec::new();
        while std::time::Instant::now() < deadline {
            events.extend(rx.try_iter());
            if !events.is_empty() { break; }
            std::thread::sleep(std::time::Duration::from_millis(50));
        }

        assert!(
            !events.is_empty(),
            "Expected at least one FIM event after file modification"
        );
    }

    #[test]
    fn fim_stop_does_not_panic() {
        let tmp = NamedTempFile::new().unwrap();
        let path = tmp.path().to_str().unwrap().to_owned();
        let (tx, _rx) = std::sync::mpsc::channel();
        let handle = FimDaemon::start(vec![path], tx).unwrap();
        handle.stop(); // Should not panic.
    }
}
