/// chimera-core/src/lib.rs
/// PyO3 module root — registers router, bus, db, and fim submodules.
use pyo3::prelude::*;

mod bus;
mod db;
mod fim;
mod router;

#[pymodule]
fn chimera_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = m.py();

    let router_mod = PyModule::new_bound(py, "router")?;
    router::register(&router_mod)?;
    m.add_submodule(&router_mod)?;

    let bus_mod = PyModule::new_bound(py, "bus")?;
    bus::register(&bus_mod)?;
    m.add_submodule(&bus_mod)?;

    let db_mod = PyModule::new_bound(py, "db")?;
    db::register(&db_mod)?;
    m.add_submodule(&db_mod)?;

    let fim_mod = PyModule::new_bound(py, "fim")?;
    fim::register(&fim_mod)?;
    m.add_submodule(&fim_mod)?;

    // Make submodules importable as `chimera_core.router` etc.
    let sys_modules = py.import_bound("sys")?.getattr("modules")?;
    sys_modules.set_item("chimera_core.router", &router_mod)?;
    sys_modules.set_item("chimera_core.bus", &bus_mod)?;
    sys_modules.set_item("chimera_core.db", &db_mod)?;
    sys_modules.set_item("chimera_core.fim", &fim_mod)?;

    Ok(())
}

