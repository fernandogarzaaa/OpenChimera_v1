/// chimera-core/src/router/mod.rs
///
/// LLM model-selection routing with exponential-decay scoring.
/// Mirrors the semantics of core/provider.py + data/local_llm_route_memory.json.
use pyo3::prelude::*;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::Path;
use thiserror::Error;

// ── Error ──────────────────────────────────────────────────────────────────

#[derive(Debug, Error)]
pub enum RouterError {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),
    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
}

impl From<RouterError> for PyErr {
    fn from(e: RouterError) -> PyErr {
        pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
    }
}

// ── Data model ─────────────────────────────────────────────────────────────

/// Mirrors one entry in data/local_llm_route_memory.json.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct QueryStats {
    pub successes: u32,
    pub failures: u32,
    pub low_quality_failures: u32,
    pub avg_latency_ms: f64,
    pub last_success_at: f64,
    pub last_failure_at: f64,
}

/// Per-model, per-query-type scoring record (part of public API).
#[allow(dead_code)]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelScore {
    pub model_id: String,
    pub query_type: String,
    pub success_count: u32,
    pub failure_count: u32,
    pub quality_rejections: u32,
    pub last_updated: u64,
}

/// Flat view of one model entry within RouteMemory (internal).
#[allow(dead_code)]
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
struct ModelEntry {
    #[serde(flatten)]
    pub stats: HashMap<String, QueryStats>,
}

/// Top-level route memory — keyed by model_id then query_type.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct RouteMemory {
    #[serde(flatten)]
    pub models: HashMap<String, HashMap<String, QueryStats>>,
}

// ── Outcome enum ───────────────────────────────────────────────────────────

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Outcome {
    Success,
    Failure,
    QualityRejection,
}

// ── Core functions ─────────────────────────────────────────────────────────

/// Extract current unix timestamp as f64.
fn now_unix() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}

/// Exponential-decay weight with 72-hour half-life.
/// Returns a weight in (0, 1] where 1 means "right now".
fn decay_weight(last_ts: f64) -> f64 {
    if last_ts <= 0.0 {
        return 0.0;
    }
    let now = now_unix();
    let age_secs = (now - last_ts).max(0.0);
    const HALF_LIFE_SECS: f64 = 72.0 * 3600.0;
    (-age_secs * std::f64::consts::LN_2 / HALF_LIFE_SECS).exp()
}

/// Score a model for a given query type using decay-weighted success rate.
/// Returns a value in [0, 1]; higher is better.
fn score_model(stats: &QueryStats) -> f64 {
    let total = (stats.successes + stats.failures + stats.low_quality_failures) as f64;
    if total == 0.0 {
        return 0.0; // no evidence yet
    }
    let raw_rate = stats.successes as f64 / total;
    // Decay the rate by how recently the last success occurred.
    let w = decay_weight(stats.last_success_at);
    raw_rate * w
}

/// Select the best model for `query_type`. Returns `None` if no model
/// passes the 0.7-success-rate threshold.
pub fn select_model(query_type: &str, memory: &RouteMemory) -> Option<String> {
    const MIN_SCORE: f64 = 0.7;
    let mut best: Option<(String, f64)> = None;

    for (model_id, qt_map) in &memory.models {
        let stats = qt_map.get(query_type).or_else(|| qt_map.get("general"))?;
        let score = score_model(stats);
        if score >= MIN_SCORE {
            match &best {
                None => best = Some((model_id.clone(), score)),
                Some((_, best_score)) if score > *best_score => {
                    best = Some((model_id.clone(), score));
                }
                _ => {}
            }
        }
    }

    best.map(|(id, _)| id)
}

/// Record an outcome for a (model, query_type) pair.
pub fn record_outcome(
    model_id: &str,
    query_type: &str,
    outcome: Outcome,
    memory: &mut RouteMemory,
) {
    let now = now_unix();
    let entry = memory
        .models
        .entry(model_id.to_owned())
        .or_default()
        .entry(query_type.to_owned())
        .or_insert_with(|| QueryStats {
            last_success_at: 0.0,
            last_failure_at: 0.0,
            ..Default::default()
        });

    match outcome {
        Outcome::Success => {
            entry.successes += 1;
            entry.last_success_at = now;
        }
        Outcome::Failure => {
            entry.failures += 1;
            entry.last_failure_at = now;
        }
        Outcome::QualityRejection => {
            entry.low_quality_failures += 1;
            entry.last_failure_at = now;
        }
    }
}

/// Serialize and write RouteMemory to disk atomically (write-then-rename).
pub fn persist_memory(memory: &RouteMemory, path: &Path) -> Result<(), RouterError> {
    let tmp = path.with_extension("json.tmp");
    let json = serde_json::to_string_pretty(memory)?;
    std::fs::write(&tmp, json)?;
    std::fs::rename(&tmp, path)?;
    Ok(())
}

/// Load RouteMemory from a JSON file.
pub fn load_memory(path: &Path) -> Result<RouteMemory, RouterError> {
    let raw = std::fs::read_to_string(path)?;
    let mem = serde_json::from_str(&raw)?;
    Ok(mem)
}

// ── PyO3 wrappers ──────────────────────────────────────────────────────────

/// Python-visible wrapper around RouteMemory.
#[pyclass(name = "RouteMemory")]
#[derive(Clone)]
pub struct PyRouteMemory {
    inner: RouteMemory,
}

#[pymethods]
impl PyRouteMemory {
    #[new]
    fn new() -> Self {
        PyRouteMemory {
            inner: RouteMemory::default(),
        }
    }

    #[staticmethod]
    fn load(path: &str) -> PyResult<Self> {
        let mem = load_memory(Path::new(path))?;
        Ok(PyRouteMemory { inner: mem })
    }

    fn save(&self, path: &str) -> PyResult<()> {
        persist_memory(&self.inner, Path::new(path))?;
        Ok(())
    }

    fn select_model(&self, query_type: &str) -> Option<String> {
        select_model(query_type, &self.inner)
    }

    fn record_success(&mut self, model_id: &str, query_type: &str) {
        record_outcome(model_id, query_type, Outcome::Success, &mut self.inner);
    }

    fn record_failure(&mut self, model_id: &str, query_type: &str) {
        record_outcome(model_id, query_type, Outcome::Failure, &mut self.inner);
    }

    fn record_quality_rejection(&mut self, model_id: &str, query_type: &str) {
        record_outcome(
            model_id,
            query_type,
            Outcome::QualityRejection,
            &mut self.inner,
        );
    }

    fn to_dict(&self, py: Python<'_>) -> PyResult<PyObject> {
        let json = serde_json::to_string(&self.inner)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
        let builtins = py.import_bound("json")?;
        let result = builtins.call_method1("loads", (json,))?;
        Ok(result.to_object(py))
    }
}

// Free-function wrappers so Python can call them without constructing a class.
#[pyfunction]
fn py_select_model(query_type: &str, memory: &PyRouteMemory) -> Option<String> {
    select_model(query_type, &memory.inner)
}

#[pyfunction]
fn py_record_outcome(
    model_id: &str,
    query_type: &str,
    outcome_str: &str,
    memory: &mut PyRouteMemory,
) -> PyResult<()> {
    let outcome = match outcome_str {
        "success" => Outcome::Success,
        "failure" => Outcome::Failure,
        "quality_rejection" => Outcome::QualityRejection,
        other => {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "Unknown outcome: {other}. Expected 'success', 'failure', or 'quality_rejection'."
            )))
        }
    };
    record_outcome(model_id, query_type, outcome, &mut memory.inner);
    Ok(())
}

#[pyfunction]
fn py_persist_memory(memory: &PyRouteMemory, path: &str) -> PyResult<()> {
    persist_memory(&memory.inner, Path::new(path))?;
    Ok(())
}

pub fn register(m: &pyo3::Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyRouteMemory>()?;
    m.add_function(wrap_pyfunction!(py_select_model, m)?)?;
    m.add_function(wrap_pyfunction!(py_record_outcome, m)?)?;
    m.add_function(wrap_pyfunction!(py_persist_memory, m)?)?;
    Ok(())
}

// ── Tests ──────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::NamedTempFile;

    fn make_memory_with_model(model: &str, successes: u32, failures: u32) -> RouteMemory {
        let mut mem = RouteMemory::default();
        let now = now_unix();
        let stats = QueryStats {
            successes,
            failures,
            low_quality_failures: 0,
            avg_latency_ms: 100.0,
            last_success_at: now - 60.0, // 1 minute ago
            last_failure_at: 0.0,
        };
        mem.models
            .entry(model.to_owned())
            .or_default()
            .insert("general".to_owned(), stats);
        mem
    }

    #[test]
    fn select_model_returns_best_above_threshold() {
        // Model A: 9/10 success rate — well above threshold.
        let mem = make_memory_with_model("model-a", 9, 1);
        let result = select_model("general", &mem);
        assert_eq!(result.as_deref(), Some("model-a"));
    }

    #[test]
    fn select_model_returns_none_below_threshold() {
        // Model B: 1/10 success rate — well below threshold.
        let mem = make_memory_with_model("model-b", 1, 9);
        let result = select_model("general", &mem);
        assert!(result.is_none(), "Expected None for low-success-rate model");
    }

    #[test]
    fn record_outcome_increments_counts() {
        let mut mem = RouteMemory::default();
        record_outcome("m", "general", Outcome::Success, &mut mem);
        record_outcome("m", "general", Outcome::Failure, &mut mem);
        record_outcome("m", "general", Outcome::QualityRejection, &mut mem);
        let stats = &mem.models["m"]["general"];
        assert_eq!(stats.successes, 1);
        assert_eq!(stats.failures, 1);
        assert_eq!(stats.low_quality_failures, 1);
    }

    #[test]
    fn persist_and_load_roundtrip() {
        let tmp = NamedTempFile::new().unwrap();
        let path = tmp.path();

        let mut mem = RouteMemory::default();
        record_outcome("model-x", "general", Outcome::Success, &mut mem);
        persist_memory(&mem, path).unwrap();

        let loaded = load_memory(path).unwrap();
        assert!(loaded.models.contains_key("model-x"));
    }

    #[test]
    fn decay_weight_recent_is_near_one() {
        let now = now_unix();
        let w = decay_weight(now - 1.0); // 1 second ago
        assert!(w > 0.99, "Expected weight near 1.0 for very recent event");
    }

    #[test]
    fn decay_weight_old_is_small() {
        let w = decay_weight(now_unix() - 72.0 * 3600.0); // exactly one half-life
        assert!((w - 0.5).abs() < 0.01, "Expected ~0.5 at one half-life");
    }
}
