"""M1 smoke test — runs the API against a temp SQLite DB via httpx ASGI transport."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["REGISTRY_DB"] = tempfile.mktemp(suffix=".db")

from fastapi.testclient import TestClient  # noqa: E402

from app.api import app  # noqa: E402

ALICE = {"Authorization": "Bearer alice-token"}
BOB = {"Authorization": "Bearer bob-token"}

SERVER_JSON = {
    "name": "acme/billing-mcp",
    "description": "Billing tools.",
    "version": "1.0.0",
    "transport": "streamable-http",
    "remote_url": "http://127.0.0.1:9101/mcp",
    "tools": [
        {"name": "get_invoice", "risk_class": "read", "input_schema": {"type": "object"}},
        {"name": "refund_payment", "risk_class": "dangerous"},
    ],
}


def main() -> None:
    c = TestClient(app)

    # auth required
    assert c.post("/v1/namespaces", json={"name": "acme"}).status_code == 401

    # claim + idempotent re-claim by same user, conflict by another user
    assert c.post("/v1/namespaces", json={"name": "acme"}, headers=ALICE).status_code == 201
    assert c.post("/v1/namespaces", json={"name": "acme"}, headers=ALICE).status_code == 201
    assert c.post("/v1/namespaces", json={"name": "acme"}, headers=BOB).status_code == 409

    # registration
    r = c.post("/v1/servers", json=SERVER_JSON, headers=ALICE)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "pending_review"

    # immutable version: re-register same version -> 409
    assert c.post("/v1/servers", json=SERVER_JSON, headers=ALICE).status_code == 409

    # unclaimed namespace -> 409
    bad = dict(SERVER_JSON, name="evil/x", version="1.0.0")
    assert c.post("/v1/servers", json=bad, headers=ALICE).status_code == 409

    # pydantic validation: bad name / bad version / missing remote_url
    for patch in (
        {"name": "Acme/Billing"},
        {"version": "v1"},
        {"remote_url": None},
    ):
        r = c.post("/v1/servers", json={**SERVER_JSON, **patch}, headers=ALICE)
        assert r.status_code == 422, (patch, r.status_code)

    # list / get
    servers = c.get("/v1/servers").json()["servers"]
    assert servers[0]["full_name"] == "acme/billing-mcp"
    assert servers[0]["latest_status"] == "pending_review"

    assert c.get("/v1/servers", params={"risk": "dangerous"}).json()["servers"]
    assert not c.get("/v1/servers", params={"query": "crm"}).json()["servers"]

    detail = c.get("/v1/servers/acme/billing-mcp").json()
    assert detail["versions"][0]["tool_count"] == 2

    v = c.get("/v1/servers/acme/billing-mcp/1.0.0").json()
    assert v["status"] == "pending_review"
    assert {t["name"] for t in v["tools"]} == {"get_invoice", "refund_payment"}

    assert c.get("/v1/servers/acme/nope").status_code == 404
    assert c.get("/v1/servers/acme/billing-mcp/9.9.9").status_code == 404

    print("M1 smoke test: all assertions passed")


if __name__ == "__main__":
    main()
