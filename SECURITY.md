# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1   | :x:                |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, use [GitHub Security Advisories](https://github.com/fernandogarzaaa/OpenChimera_v1/security/advisories/new) to report vulnerabilities privately. This allows us to assess and patch the issue before public disclosure.

If GitHub Security Advisories are unavailable, email `security@openchimera.ai` with the subject line `[SECURITY] <brief description>`. Include:

- A description of the vulnerability and its potential impact
- Steps to reproduce or a proof-of-concept
- Any suggested mitigations you have identified

## Response Timeline

| Stage | Target |
|-------|--------|
| Acknowledgement | Within **48 hours** of receiving the report |
| Initial assessment | Within **5 business days** |
| Patch for critical issues | Within **14 days** |
| Patch for high/medium issues | Within **30 days** |
| Coordinated public disclosure | After patch is available, agreed with reporter |

We follow coordinated disclosure. Once a fix is released, we will publish a security advisory crediting the reporter (unless they prefer anonymity).

## Security Defaults

OpenChimera is designed with safe defaults for local and production deployments:

- **Localhost-only binding** — the API server binds to `127.0.0.1:7870` by default. Non-loopback binds require explicit `OPENCHIMERA_HOST=0.0.0.0` and, for unauthenticated binds, `OPENCHIMERA_ALLOW_INSECURE_BIND=1`.
- **Authentication optional but enforced when configured** — if `OPENCHIMERA_API_TOKEN` is set, the runtime requires it on every request. Enabling auth without a token is a fast-fail startup error.
- **TLS optional but enforced when configured** — if `api.tls.enabled=true` is set, the runtime requires both `certfile` and `keyfile`. Partial TLS configuration is a fast-fail startup error.
- **No committed secrets** — the default `config/runtime_profile.json` contains only publishable defaults. Machine-specific paths and credentials belong in `config/runtime_profile.local.json` (gitignored) or environment variables.
- **Restrictive HTTP security headers** — all responses include `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy`, and HSTS on HTTPS.
- **Credential surfaces are read-only and sanitized** — `openchimera doctor`, `openchimera config --json`, and `GET /v1/config/status` report auth and TLS state without printing raw token values.

## What Is In Scope

The following are in scope for security reports:

- Authentication and authorization bypasses in the API server
- Injection vulnerabilities (prompt injection with privilege escalation, command injection, path traversal)
- Secrets disclosure (tokens, credentials, or private config exposed via API responses or logs)
- Denial-of-service vulnerabilities in the Python runtime or API layer
- Insecure defaults that could expose local deployments without user awareness
- MCP tool-call privilege escalation or sandbox escapes
- Dependency vulnerabilities with a realistic exploitation path against OpenChimera

## What Is Out of Scope

The following are generally out of scope:

- Vulnerabilities in optional external integrations (AETHER, WRAITH, MiniMind, upstream harness) that are not exposed through the OpenChimera runtime surface
- Self-inflicted misconfigurations (e.g., user explicitly sets `OPENCHIMERA_ALLOW_INSECURE_BIND=1` and binds to 0.0.0.0 without auth)
- Issues requiring physical access to the machine running OpenChimera
- Theoretical vulnerabilities without a realistic attack scenario against a local-first runtime
- Security issues in local LLM models themselves (weights, inference outputs)
- Social engineering attacks

## Repository Hygiene

To keep the repository safe to publish from source:

- Do not commit real API tokens, passwords, webhook secrets, or private provider credentials
- Keep machine-specific runtime roots out of `config/runtime_profile.json`
- Use `config/runtime_profile.local.json` or `OPENCHIMERA_RUNTIME_PROFILE` for private overrides
- Keep `.env.example` placeholder-only
- Treat `data/credentials.json` and any local credential material as private runtime state
