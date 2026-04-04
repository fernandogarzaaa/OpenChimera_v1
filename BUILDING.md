# Building OpenChimera (Rust/Python Hybrid)

OpenChimera contains a native Rust extension (`chimera-core`) that is compiled
via [PyO3](https://pyo3.rs/) and [Maturin](https://www.maturin.rs/).  
The four modules compiled to native code are:

| Module | Python import | Replaces |
|--------|--------------|---------|
| Router | `chimera_core.router` | `data/local_llm_route_memory.json` scoring |
| Event bus | `chimera_core.bus` | `core/bus.py` (threading) |
| Database | `chimera_core.db` | `core/database.py` (sqlite3) |
| FIM | `chimera_core.fim` | `core/fim_daemon.py` |

Each module falls back transparently to its pure-Python counterpart if the
Rust extension is not installed.

---

## Prerequisites

| Tool | Minimum version | Install |
|------|----------------|---------|
| Python | 3.11 | <https://www.python.org/downloads/> |
| Rust toolchain | stable (1.70+) | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` |
| Maturin | 1.5+ | `pip install maturin` |

On Windows, use the `stable-x86_64-pc-windows-msvc` Rust target (default
when Visual Studio Build Tools are installed).

---

## Developer setup (editable install)

```bash
# 1. Clone the repo
git clone https://github.com/your-org/openchimera.git
cd openchimera

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
.\.venv\Scripts\Activate.ps1    # Windows PowerShell

# 3. Install Maturin and build the Rust extension in-place
pip install maturin
maturin develop                  # debug build (fast)
# or for a release-optimised build:
maturin develop --release

# 4. Install remaining Python dependencies
pip install -r requirements-dev.txt

# 5. Verify the runtime is healthy
python run.py doctor
```

---

## Running the Rust test suite

```bash
cargo test -p chimera-core
```

Expected output: **19 passed; 0 failed**

Run with backtrace on failure:

```bash
RUST_BACKTRACE=1 cargo test -p chimera-core
```

---

## Checking the active backend at runtime

```python
from core import bus, database

print(bus.backend())       # 'rust' or 'python'
print(database.backend())  # 'rust' or 'python'
```

---

## CI workflow

The GitHub Actions workflow (`python-ci.yml`) automatically:

1. Installs the stable Rust toolchain via `dtolnay/rust-toolchain@stable`.
2. Builds the extension with `maturin develop --release`.
3. Runs `cargo test -p chimera-core --release`.
4. Proceeds with the existing Python test suite.

No additional secrets or runners are required beyond the standard
`ubuntu-latest` / `windows-latest` matrix.

---

## Distribution

To build a distributable wheel (includes the compiled `.so`/`.pyd`):

```bash
maturin build --release
# Wheel lands in target/wheels/
```

To publish to PyPI:

```bash
maturin publish
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ModuleNotFoundError: No module named 'chimera_core'` | Run `maturin develop` first |
| `libsqlite3-sys` link conflict | Ensure only sqlx 0.8 is in `Cargo.toml`; no `rusqlite` dependency |
| FIM test flaky on Windows | The test polls for 3 s; increase if CI host is heavily loaded |
| `cargo clippy` missing | `rustup component add clippy` |
