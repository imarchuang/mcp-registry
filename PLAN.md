# mcp-registry — Demo Plan

A **private MCP registry** demo, following the industry consensus shape
(official MCP Registry preview, Azure API Center, Kong registry tech-preview):

> A registry is the authoritative catalogue of which servers and tools are
> **approved to exist** — who owns them, what their schemas are, what risk
> class they carry, and what their lifecycle state is. It decides on a
> timescale of days/weeks. **It is NOT in the runtime call path.**

## 1. Industry anchors

| Reference | What we borrow |
| --- | --- |
| Official MCP Registry (preview, launched 2025-09; ~39.5k servers by 2026-10) | `server.json` metadata schema; namespace ownership concept; read API shape (`/v0/servers`); "deliberately narrow, pointers not packages" |
| Azure API Center ("private enterprise-ready MCP registry") | Private deployment, SSO, curation/approval flow |
| Gateway/registry split (Barzel, ASCENDING, vdf.ai) | Registry publishes the approved list; the **gateway enforces it per call**. Failure mode of registry alone: approved servers used in unapproved ways. |

Key non-goal inherited from the official registry: **no package hosting** —
we store metadata + schema + pointers, never the server binaries.

## 2. Scope

### In scope (demo)

1. **Server registration** via `server.json`-compatible payload
   - name (`namespace/server-name`), description, version, transport
     (`streamable-http` | `stdio`), remote URL or package pointer
   - tool list with JSON schemas (pasted or fetched from the server's
     `list_tools`)
2. **Namespace ownership (simplified)**
   - namespaces are claimed by users (demo: first-come; no DNS/GitHub
     challenge — noted as production requirement)
3. **Versioning & lifecycle**
   - immutable (name, version) entries — a changed version is a new entry
   - states: `pending_review → approved → deprecated`
   - only `approved` entries appear in the gateway-facing read API
4. **Risk classification**
   - per-tool risk class: `read` | `write` | `dangerous` (e.g. refunds,
     deletions) — the field a gateway's policy engine consumes
5. **Read APIs**
   - public-ish: search/list/get servers + versions + tool schemas
   - **gateway-facing sync API**: `GET /v1/sync/approved?since=<ts>` —
     the approved list + tool risk classes, delta-capable
6. **Audit of the registry itself**: who registered/approved/deprecated what
   (publish audit log, mirroring what ContextHub does with change_requests)

### Out of scope

- Per-call authorization / routing / rate limiting (that is the gateway:
  `~/workspace_gh/mcp-gateway`)
- Package/binary hosting, security scanning of packages
- UI beyond a minimal read-only catalog page (stretch)

## 3. Data model (SQLite)

```
namespaces   (name, owner_user, created_at)
servers      (id, namespace, name, description, owner, created_at)
versions     (id, server_id, version, transport, remote_url,
              status,          -- pending_review|approved|deprecated
              submitted_by, approved_by, created_at,
              UNIQUE(server_id, version))
tools        (id, version_id, name, description, schema_json,
              risk_class,      -- read|write|dangerous
              annotations_json)
registry_audit(id, actor, action, target, payload_json, created_at)
```

Invariants: `(server, version)` immutable after `approved`; deprecating a
version never rewrites it; `approved` requires a distinct approver ≠ submitter
(four-eyes, demo-flaggable).

## 4. API sketch

```
POST   /v1/namespaces                       claim namespace
POST   /v1/servers                          register server (server.json body)
POST   /v1/servers/{ns}/{name}/versions     publish a version
GET    /v1/servers?query=&risk=&status=     search
GET    /v1/servers/{ns}/{name}              detail (all versions)
GET    /v1/servers/{ns}/{name}/{version}    one version incl. tool schemas
POST   /v1/versions/{id}/approve            approver action
POST   /v1/versions/{id}/deprecate
GET    /v1/sync/approved?since=             gateway sync feed
GET    /v1/audit                            registry audit log
```

## 5. Tech choices

- **TypeScript + Node 22 + Hono** (same stack as the gateway demo to keep the
  pair uniform), zod for `server.json` validation, better-sqlite3 for storage
- AuthN for the demo: static bearer tokens mapped to users
  (`alice:submitter`, `bob:approver`); production note: SSO/OIDC
- No external deps beyond that; `docker-compose.yml` optional

## 6. Milestones

- **M1 — skeleton**: Hono app, SQLite schema, namespace + server + version
  registration with zod-validated `server.json`, list/get APIs
- **M2 — lifecycle**: pending → approve → deprecate, four-eyes check,
  registry audit log
- **M3 — tool schemas & risk**: tool table, risk classes, tool-level search
- **M4 — sync feed**: `/v1/sync/approved?since=`, consumed by
  `mcp-gateway` demo
- **M5 (stretch)**: import from the official public registry API
  (`GET https://registry.modelcontextprotocol.io/v0/servers`) into a
  read-only "public mirror" table to show private-over-public curation

## 7. Demo script (end state)

1. `alice` claims namespace `acme`, registers `acme/billing-mcp` v1.0.0 with
   tools `get_invoice (read)`, `refund_payment (dangerous)`
2. `bob` approves v1.0.0 → appears in `/v1/sync/approved`
3. Register v1.1.0 (adds `delete_customer (dangerous)`) — stays invisible to
   the gateway until approved
4. `curl` the sync feed → only approved versions with risk classes
5. The **mcp-gateway** demo consumes this feed; a call to
   `refund_payment` is allowed/denied per policy sourced from the registry —
   showing the "registry decides weeks-scale, gateway decides ms-scale" split

## 8. Relation to mcp-gateway

```
┌──────────────┐  /v1/sync/approved   ┌──────────────┐   MCP    ┌────────────┐
│ mcp-registry │ ───────────────────▶ │ mcp-gateway  │ ───────▶ │ MCP servers│
│ (this repo)  │   approved list +    │  (call path) │  calls   │ (billing…) │
│              │   risk classes       │              │          │            │
└──────────────┘                      └──────────────┘          └────────────┘
  decides in days                       decides in milliseconds
```

The registry never sees a tool call; the gateway never decides what is
approved — it enforces what the registry published.
