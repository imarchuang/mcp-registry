"""HTTP API. AuthN for the demo: static bearer tokens mapped to users
(production note: SSO/OIDC). See PLAN.md section 4."""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query

from .db import RegistryStore
from .models import (
    NamespaceClaim,
    ServerDetail,
    ServerJson,
    ServerSummary,
    VersionDetail,
    VersionStatus,
    VersionSummary,
)

# Static demo tokens: token -> user. Override with REGISTRY_TOKENS="tok1:user1,tok2:user2".
DEFAULT_TOKENS = {
    "alice-token": "alice",  # submitter
    "bob-token": "bob",  # approver (used from M2)
}


def load_tokens() -> dict[str, str]:
    raw = os.environ.get("REGISTRY_TOKENS")
    if not raw:
        return DEFAULT_TOKENS
    return dict(pair.split(":", 1) for pair in raw.split(","))


TOKENS = load_tokens()

store = RegistryStore(os.environ.get("REGISTRY_DB", "registry.db"))
app = FastAPI(title="mcp-registry (demo)", version="0.1.0-m1")


def current_user(authorization: Annotated[str | None, Header()] = None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    user = TOKENS.get(authorization.removeprefix("Bearer ").strip())
    if not user:
        raise HTTPException(401, "unknown token")
    return user


User = Annotated[str, Depends(current_user)]


# ---- namespaces ----


@app.post("/v1/namespaces", status_code=201)
def claim_namespace(body: NamespaceClaim, user: User):
    ok = store.claim_namespace(body.name, user)
    if not ok:
        raise HTTPException(409, f"namespace '{body.name}' already claimed by another user")
    return {"namespace": body.name, "owner": user}


@app.get("/v1/namespaces")
def list_namespaces():
    return {"namespaces": store.list_namespaces()}


# ---- servers / versions ----


@app.post("/v1/servers", status_code=201)
def register_server(body: ServerJson, user: User):
    """Register a server.json payload. Creates the server on first publish and
    adds one immutable version (status=pending_review)."""
    try:
        result = store.register_server_json(body, user)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {
        "server": body.name,
        "version": body.version,
        "status": result["status"],
        "version_id": result["version_id"],
    }


@app.get("/v1/servers", response_model=dict[str, list[ServerSummary]])
def search_servers(
    query: str | None = Query(default=None),
    status: VersionStatus | None = Query(default=None),
    risk: str | None = Query(default=None, pattern="^(read|write|dangerous)$"),
):
    rows = store.search_servers(query=query, status=status.value if status else None, risk=risk)
    return {
        "servers": [
            ServerSummary(
                namespace=r["namespace"],
                name=r["name"],
                full_name=f"{r['namespace']}/{r['name']}",
                description=r["description"],
                owner=r["owner"],
                latest_status=r["latest_status"],
                version_count=r["version_count"],
                created_at=r["created_at"],
            )
            for r in rows
        ]
    }


@app.get("/v1/servers/{ns}/{name}", response_model=ServerDetail)
def get_server(ns: str, name: str):
    srv = store.get_server(ns, name)
    if not srv:
        raise HTTPException(404, f"server '{ns}/{name}' not found")
    versions = [
        VersionSummary(
            id=v["id"],
            version=v["version"],
            status=v["status"],
            transport=v["transport"],
            remote_url=v["remote_url"],
            package=v["package"],
            tool_count=v["tool_count"],
            submitted_by=v["submitted_by"],
            created_at=v["created_at"],
        )
        for v in store.get_versions(srv["id"])
    ]
    return ServerDetail(
        namespace=srv["namespace"],
        name=srv["name"],
        full_name=f"{srv['namespace']}/{srv['name']}",
        description=srv["description"],
        owner=srv["owner"],
        created_at=srv["created_at"],
        versions=versions,
    )


@app.get("/v1/servers/{ns}/{name}/{version}", response_model=VersionDetail)
def get_version(ns: str, name: str, version: str):
    detail = store.get_version_detail(ns, name, version)
    if not detail:
        raise HTTPException(404, f"version '{ns}/{name}@{version}' not found")
    return VersionDetail(
        id=detail["id"],
        server=f"{detail['namespace']}/{detail['server_name']}",
        version=detail["version"],
        status=detail["status"],
        transport=detail["transport"],
        remote_url=detail["remote_url"],
        package=detail["package"],
        submitted_by=detail["submitted_by"],
        approved_by=detail["approved_by"],
        created_at=detail["created_at"],
        tools=detail["tools"],
    )
