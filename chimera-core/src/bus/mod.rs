/// chimera-core/src/bus/mod.rs
///
/// Tokio broadcast-channel event bus with synchronous PyO3 wrappers.
/// Replaces core/bus.py (EventBus).
///
/// Design: Python callers get a sync interface. Internally, we use
/// tokio::runtime::Handle::current().block_on() so there's no async
/// boundary crossing the PyO3 FFI — safer and simpler than pyo3-asyncio
/// until that dependency matures.
use pyo3::prelude::*;
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};
use thiserror::Error;

// ── Helpers ────────────────────────────────────────────────────────────────

fn now_millis() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

// ── Error ──────────────────────────────────────────────────────────────────

#[derive(Debug, Error)]
pub enum BusError {
    #[error("Publish failed: all receivers have dropped")]
    NoReceivers,
    #[error("Receive failed (channel lagged): {0}")]
    Lagged(u64),
    #[error("JSON serialization error: {0}")]
    Json(#[from] serde_json::Error),
}

impl From<BusError> for PyErr {
    fn from(e: BusError) -> PyErr {
        pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
    }
}

// ── Event ──────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Event {
    pub topic: String,
    pub payload: serde_json::Value,
    pub timestamp: u64,
}

// ── Inner shared state ─────────────────────────────────────────────────────

/// History kept for late-joining subscribers.
const HISTORY_SIZE: usize = 256;

struct BusInner {
    sender: tokio::sync::broadcast::Sender<Event>,
    history: VecDeque<Event>,
}

impl BusInner {
    fn new(capacity: usize) -> Self {
        let (sender, _) = tokio::sync::broadcast::channel(capacity);
        BusInner {
            sender,
            history: VecDeque::with_capacity(HISTORY_SIZE),
        }
    }

    fn publish(&mut self, topic: String, payload: serde_json::Value) -> Result<(), BusError> {
        let event = Event {
            topic,
            payload,
            timestamp: now_millis(),
        };
        // Push to history (bounded).
        if self.history.len() >= HISTORY_SIZE {
            self.history.pop_front();
        }
        self.history.push_back(event.clone());
        // Ignore SendError when no active receivers — that's fine for a bus.
        let _ = self.sender.send(event);
        Ok(())
    }

    fn subscribe(&self) -> tokio::sync::broadcast::Receiver<Event> {
        self.sender.subscribe()
    }
}

// ── EventBus (public Rust API) ─────────────────────────────────────────────

#[derive(Clone)]
pub struct EventBus {
    inner: Arc<Mutex<BusInner>>,
}

impl EventBus {
    pub fn new(capacity: usize) -> Self {
        EventBus {
            inner: Arc::new(Mutex::new(BusInner::new(capacity))),
        }
    }

    pub fn publish(&self, topic: String, payload: serde_json::Value) -> Result<(), BusError> {
        self.inner.lock().unwrap().publish(topic, payload)
    }

    pub fn subscribe(&self) -> EventReceiver {
        let rx = self.inner.lock().unwrap().subscribe();
        EventReceiver { rx }
    }

    pub fn recent_events(&self) -> Vec<Event> {
        self.inner.lock().unwrap().history.iter().cloned().collect()
    }
}

// ── EventReceiver ──────────────────────────────────────────────────────────

pub struct EventReceiver {
    rx: tokio::sync::broadcast::Receiver<Event>,
}

impl EventReceiver {
    /// Non-blocking poll — returns events currently available.
    pub fn drain(&mut self) -> Vec<Event> {
        let mut out = Vec::new();
        loop {
            match self.rx.try_recv() {
                Ok(ev) => out.push(ev),
                Err(tokio::sync::broadcast::error::TryRecvError::Empty) => break,
                Err(tokio::sync::broadcast::error::TryRecvError::Lagged(n)) => {
                    // Report lag but continue draining.
                    eprintln!("chimera_core.bus: receiver lagged {n} messages");
                    continue;
                }
                Err(tokio::sync::broadcast::error::TryRecvError::Closed) => break,
            }
        }
        out
    }

    /// Filter the drain by topic prefix.
    pub fn drain_filtered(&mut self, topic_filter: &str) -> Vec<Event> {
        self.drain()
            .into_iter()
            .filter(|e| e.topic.starts_with(topic_filter))
            .collect()
    }
}

// ── PyO3 wrappers ──────────────────────────────────────────────────────────

/// Python-visible EventBus.
#[pyclass(name = "EventBus")]
pub struct PyEventBus {
    inner: EventBus,
}

#[pymethods]
impl PyEventBus {
    #[new]
    #[pyo3(signature = (capacity = 512))]
    fn new(capacity: usize) -> Self {
        PyEventBus {
            inner: EventBus::new(capacity),
        }
    }

    /// publish(topic: str, payload: dict) -> None
    fn publish(&self, py: Python<'_>, topic: &str, payload: &pyo3::Bound<'_, pyo3::types::PyDict>) -> PyResult<()> {
        let json_mod = py.import_bound("json")?;
        let json_str: String = json_mod.call_method1("dumps", (payload,))?.extract()?;
        let value: serde_json::Value = serde_json::from_str(&json_str)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        self.inner
            .publish(topic.to_owned(), value)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
        Ok(())
    }

    /// subscribe(topic_filter=None) -> EventReceiver
    #[pyo3(signature = (topic_filter = None))]
    fn subscribe(&self, topic_filter: Option<String>) -> PyEventReceiver {
        PyEventReceiver {
            inner: self.inner.subscribe(),
            topic_filter,
        }
    }

    /// recent_events() -> list[dict]
    fn recent_events(&self, py: Python<'_>) -> PyResult<PyObject> {
        let events = self.inner.recent_events();
        let list = pyo3::types::PyList::empty_bound(py);
        for ev in events {
            let d = pyo3::types::PyDict::new_bound(py);
            d.set_item("topic", &ev.topic)?;
            d.set_item("timestamp", ev.timestamp)?;
            let json_str = serde_json::to_string(&ev.payload)
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
            let json_mod = py.import_bound("json")?;
            let payload_obj = json_mod.call_method1("loads", (json_str,))?;
            d.set_item("payload", payload_obj)?;
            list.append(d)?;
        }
        Ok(list.to_object(py))
    }
}

/// Python-visible EventReceiver.
#[pyclass(name = "EventReceiver")]
pub struct PyEventReceiver {
    inner: EventReceiver,
    topic_filter: Option<String>,
}

#[pymethods]
impl PyEventReceiver {
    /// drain() -> list[dict]  — non-blocking poll.
    fn drain(&mut self, py: Python<'_>) -> PyResult<PyObject> {
        let events = match &self.topic_filter {
            Some(f) => self.inner.drain_filtered(f),
            None => self.inner.drain(),
        };
        events_to_py_bound(py, events)
    }
}

fn events_to_py_bound(py: Python<'_>, events: Vec<Event>) -> PyResult<PyObject> {
    let list = pyo3::types::PyList::empty_bound(py);
    for ev in events {
        let d = pyo3::types::PyDict::new_bound(py);
        d.set_item("topic", &ev.topic)?;
        d.set_item("timestamp", ev.timestamp)?;
        let json_str = serde_json::to_string(&ev.payload)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
        let json_mod = py.import_bound("json")?;
        let payload_obj = json_mod.call_method1("loads", (json_str,))?;
        d.set_item("payload", payload_obj)?;
        list.append(d)?;
    }
    Ok(list.to_object(py))
}

pub fn register(m: &pyo3::Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyEventBus>()?;
    m.add_class::<PyEventReceiver>()?;
    Ok(())
}

// ── Tests ──────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn make_bus() -> EventBus {
        EventBus::new(64)
    }

    #[test]
    fn publish_and_drain_happy_path() {
        let bus = make_bus();
        let mut rx = bus.subscribe();

        bus.publish(
            "test.topic".to_owned(),
            serde_json::json!({"key": "value"}),
        )
        .unwrap();

        let events = rx.drain();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].topic, "test.topic");
        assert_eq!(events[0].payload["key"], "value");
    }

    #[test]
    fn drain_filtered_excludes_wrong_topic() {
        let bus = make_bus();
        let mut rx = bus.subscribe();

        bus.publish("security_alert".to_owned(), serde_json::json!({}))
            .unwrap();
        bus.publish("system.ready".to_owned(), serde_json::json!({}))
            .unwrap();

        let events = rx.drain_filtered("security");
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].topic, "security_alert");
    }

    #[test]
    fn no_receivers_publish_does_not_panic() {
        let bus = make_bus();
        // No subscriber — should not panic.
        let result = bus.publish("orphan".to_owned(), serde_json::json!(null));
        assert!(result.is_ok());
    }

    #[test]
    fn recent_events_bounded_by_history_size() {
        let bus = make_bus();
        for i in 0..300 {
            bus.publish(format!("topic.{i}"), serde_json::json!({}))
                .unwrap();
        }
        let history = bus.recent_events();
        assert!(
            history.len() <= 256,
            "History must not grow beyond HISTORY_SIZE"
        );
    }

    #[test]
    fn drain_empty_returns_empty_vec() {
        let bus = make_bus();
        let mut rx = bus.subscribe();
        let events = rx.drain();
        assert!(events.is_empty());
    }
}
