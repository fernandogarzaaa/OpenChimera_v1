# chimeralang-mcp v0.2.0 release artifacts

The v0.2.0 work was fully implemented and integration-tested in the sandbox,
but the sandbox network policy only authorizes git traffic to
`fernandogarzaaa/OpenChimera_v1`. Pushing to `fernandogarzaaa/chimeralang-mcp`
and publishing to PyPI could not be done from here.

Everything needed to ship is in this directory. Run the three commands at the
bottom from your own machine to complete the release.

## What's here

| File | Purpose |
|---|---|
| `v0.2.0.patch` | Single-commit patch ready for `git am` on `chimeralang-mcp` `main` |
| `server.py` | Updated `chimeralang_mcp/server.py` (12 tools) |
| `pyproject.toml` | Version bumped to `0.2.0` |
| `README.md` | Updated tools table (9 -> 12) |
| `integration_test.py` | Standalone test that exercises all 12 tools |

## Integration test result

```
[PASS] chimera_run
[PASS] chimera_confident
[PASS] chimera_explore
[PASS] chimera_gate
[PASS] chimera_detect
[PASS] chimera_constrain
[PASS] chimera_typecheck
[PASS] chimera_prove
[PASS] chimera_audit
[PASS] chimera_compress
[PASS] chimera_optimize
[PASS] chimera_fracture

Result: 12/12 tools passed
```

## Release commands (run locally)

```bash
git clone https://github.com/fernandogarzaaa/chimeralang-mcp
cd chimeralang-mcp
git am /path/to/v0.2.0.patch
git push origin main
git tag v0.2.0
git push origin v0.2.0     # triggers the OIDC PyPI publish workflow
```

If `git am` conflicts for any reason, just copy `server.py`, `pyproject.toml`,
and `README.md` over the originals and commit with the message in the patch
header.
