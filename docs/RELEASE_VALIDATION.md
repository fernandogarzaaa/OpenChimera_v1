# Release validation

Run these gates from a clean checkout before release or PR merge:

```bash
python -m pip install -e ".[dev]"
pytest -q
ruff check .
python -m build
python -m pip_audit
cd src/dashboard && npm install && npm run build
```

Smoke-test the end-user journeys without real secrets:

```bash
openchimera bootstrap --json
openchimera onboard --json
openchimera doctor --json
openchimera status --json
openchimera capabilities --json
openchimera tools --json
openchimera serve --host 127.0.0.1 --port 8787
curl http://127.0.0.1:8787/health
curl http://127.0.0.1:8787/v1/models
curl -X POST http://127.0.0.1:8787/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"mock","messages":[{"role":"user","content":"hello"}]}'
curl -N -X POST http://127.0.0.1:8787/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"mock","stream":true,"messages":[{"role":"user","content":"hello"}]}'
# The streaming endpoint emits OpenAI-compatible SSE chunks ending in `data: [DONE]`.
```

Do not commit API keys, tokens, private model paths, or local credentials. Use environment variables or `config/local.yaml` for local overrides.

## Production exposure

Loopback binds (`127.0.0.1`, `localhost`, `::1`) need no auth. Binding beyond
loopback without API auth is refused by `openchimera serve` unless you pass
`--allow-insecure-bind`:

```bash
OPENCHIMERA_API__AUTH__ENABLED=true OPENCHIMERA_API__AUTH__TOKEN=<token> \
  openchimera serve --host 0.0.0.0 --port 7870
curl http://127.0.0.1:7870/v1/models -H 'Authorization: Bearer <token>'
```

With auth enabled, every API route except `/health` (and CORS preflights)
requires `Authorization: Bearer <token>` (`OPENCHIMERA_API__AUTH__TOKEN` or
`...__ADMIN_TOKEN`) and returns 401 otherwise.

Precedence is flags > environment > config files: explicitly-set
`OPENCHIMERA_*__*` variables override `config/default.yaml` (and
`config/local.yaml`), which only fill the gaps.

## TUI and cross-platform checks

The packaged CLI includes a non-interactive TUI preflight check:

```bash
openchimera tui --check --json
```

A native TUI launch requires a compiled Rust binary in `target/release/`. Do not mark Windows, macOS, or Linux native release gates as passed without a concrete local run or hosted CI witness for that OS.
