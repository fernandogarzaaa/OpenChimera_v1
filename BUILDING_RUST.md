# Building Optional Rust Extensions

OpenChimera's core Python implementation includes fallbacks for all functionality. The optional `chimera-core` Rust extension provides accelerated implementations of performance-critical paths.

## Status

The Rust extension is **optional** and **not required** for normal operation. All features work with pure-Python fallbacks.

## Building the Rust Extension

If you want to build the optional Rust extension for performance:

### Requirements

- Rust 1.70+ (install via [rustup](https://rustup.rs))
- Python 3.11+
- [maturin](https://github.com/PyO3/maturin) build backend

### Build Steps

```bash
# 1. Install Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env

# 2. Install maturin
pip install maturin

# 3. Build the extension in development mode
maturin develop --release

# 4. The extension is now available for import
python -c "from chimera_core import db; print('✓ Rust extension loaded')"
```

### Distribution Builds

To build wheels for distribution:

```bash
# Build for your current platform
maturin build --release

# Build with manylinux compatibility (Linux only)
docker run --rm -v $(pwd):/io konstin2/maturin build --release

# Wheels will be in target/wheels/
```

## What the Rust Extension Provides

When available, the extension accelerates:

- **Database operations** (`chimera_core.db.Database`) — faster SQLite connection pooling and query execution
- **Event bus** (`chimera_core.bus.EventBus`) — lock-free publish/subscribe with async-await support

The Python fallbacks in `core/_database_fallback.py` and `core/_bus_fallback.py` provide identical APIs with slightly lower throughput.

## Testing

The test suite verifies both paths:

```bash
# Run with Python fallbacks only
python -m pytest tests/test_database_backend.py -v

# Run with Rust extensions (after maturin build)
python -m pytest tests/ -v
```

## CI Integration

The GitHub Actions workflow has been updated to use pure-Python builds by default. To enable Rust builds in CI, uncomment the Rust toolchain and maturin steps in `.github/workflows/python-ci.yml`.

## Why Rust is Optional

OpenChimera prioritizes:

1. **Zero-friction installation** for first-time users
2. **Cross-platform portability** without build toolchains
3. **Fast test iteration** without compilation overhead

The Rust extension is an **optimization layer**, not a requirement.
