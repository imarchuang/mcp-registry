"""Seed the M1 demo: alice claims 'acme', registers acme/billing-mcp v1.0.0.

Usage: python examples/seed_demo.py  (server must be running on :8080)
"""

import httpx

BASE = "http://127.0.0.1:8080"
ALICE = {"Authorization": "Bearer alice-token"}

BILLING_V1 = {
    "name": "acme/billing-mcp",
    "description": "Billing domain tools: invoices, payments, refunds.",
    "version": "1.0.0",
    "transport": "streamable-http",
    "remote_url": "http://127.0.0.1:9101/mcp",
    "tools": [
        {
            "name": "get_invoice",
            "description": "Fetch one invoice by id.",
            "risk_class": "read",
            "input_schema": {
                "type": "object",
                "properties": {"invoice_id": {"type": "string"}},
                "required": ["invoice_id"],
            },
        },
        {
            "name": "refund_payment",
            "description": "Refund a payment. Irreversible.",
            "risk_class": "dangerous",
            "input_schema": {
                "type": "object",
                "properties": {
                    "payment_id": {"type": "string"},
                    "amount": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["payment_id", "amount"],
            },
        },
    ],
}


def main() -> None:
    with httpx.Client(base_url=BASE, headers=ALICE, timeout=10) as c:
        r = c.post("/v1/namespaces", json={"name": "acme"})
        print("claim acme      ->", r.status_code, r.json())

        r = c.post("/v1/servers", json=BILLING_V1)
        print("register v1.0.0 ->", r.status_code, r.json())

        r = c.get("/v1/servers", params={"risk": "dangerous"})
        print("search risk=dangerous ->", [s["full_name"] for s in r.json()["servers"]])

        r = c.get("/v1/servers/acme/billing-mcp/1.0.0")
        body = r.json()
        print(
            "version detail  ->",
            body["status"],
            [f"{t['name']}({t['risk_class']})" for t in body["tools"]],
        )


if __name__ == "__main__":
    main()
