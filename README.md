# mcp-registry (demo)

A **private MCP registry** demo: the authoritative catalogue of which MCP
servers/tools are *approved to exist* — ownership, schemas, per-tool risk
classes, lifecycle. It decides on a timescale of days; it is **not** in the
runtime call path (that is `mcp-gateway`). See [PLAN.md](PLAN.md).

## Status

- **M1 — skeleton** ✅ FastAPI app, SQLite schema (5 tables), namespace claim,
  server.json-validated server+version registration, list/get/search APIs
- M2 — lifecycle (approve/deprecate, four-eyes, registry audit): planned
- M3/M4/M5: planned

## Run

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python main.py            # serves on http://127.0.0.1:8080
.venv/bin/python examples/seed_demo.py   # in another shell: seeds acme/billing-mcp v1.0.0
.venv/bin/python tests/test_m1.py        # smoke test (temp DB, no server needed)
```

OpenAPI docs: http://127.0.0.1:8080/docs

## AuthN (demo)

Static bearer tokens: `alice-token` (submitter), `bob-token` (approver).
Override with `REGISTRY_TOKENS="tok1:user1,tok2:user2"`. DB path via
`REGISTRY_DB` (default `./registry.db`). Production note: SSO/OIDC.

## API (M1)

```
POST /v1/namespaces                    claim namespace (first-come)
GET  /v1/namespaces
POST /v1/servers                       register server.json payload → version pending_review
GET  /v1/servers?query=&status=&risk=  search
GET  /v1/servers/{ns}/{name}           detail + all versions
GET  /v1/servers/{ns}/{name}/{ver}     one version incl. tool schemas + risk classes
```

Key invariants enforced in M1: namespace must be claimed by the registering
user; `(server, version)` is immutable — re-registering the same version
returns 409; `server.json` payload is pydantic-validated (name shape, semver,
transport/pointer consistency).
