# Security Policy

## Reporting

If you discover a security issue in OpenChimera, open a private report through the repository security workflow if available. If that is not available, avoid filing public issues with active exploit details or live credentials.

## Repository Hygiene

OpenChimera should remain safe to publish from source:

- do not commit real API tokens, passwords, webhook secrets, or private provider credentials
- keep machine-specific runtime roots out of `config/runtime_profile.json`
- use `config/runtime_profile.local.json` or `OPENCHIMERA_RUNTIME_PROFILE` for private overrides
- keep `.env.example` placeholder-only
- treat `data/credentials.json` and any local credential material as private runtime state

## Runtime Guidance

- Prefer `OPENCHIMERA_API_TOKEN` and `OPENCHIMERA_ADMIN_TOKEN` for protected deployments.
- Do not expose OpenChimera on `0.0.0.0` or any non-loopback host without API auth enabled.
- Review `openchimera doctor` output before exposing the API beyond localhost.
- Review `openchimera config --json` or `GET /v1/config/status` to confirm the effective bind host, TLS state, structured logging path, and override-profile source before deployment.
- Keep optional channel and browser routes behind admin auth when enabled.
- OpenChimera now emits restrictive default HTTP headers including `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, and HSTS on HTTPS responses.
- If you must run a non-loopback unauthenticated bind in an isolated lab, require an explicit `OPENCHIMERA_ALLOW_INSECURE_BIND=1` override and treat that configuration as temporary and high-risk.

## Scope

This policy covers the Python runtime, bundled CLI, API routes, local state handling, and repository documentation.
