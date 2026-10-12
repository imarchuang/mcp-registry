"""SQLite storage layer. stdlib sqlite3, one connection per request."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import ServerJson

SCHEMA = """
CREATE TABLE IF NOT EXISTS namespaces (
    name        TEXT PRIMARY KEY,
    owner_user  TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS servers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace   TEXT NOT NULL REFERENCES namespaces(name),
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    owner       TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (namespace, name)
);
CREATE TABLE IF NOT EXISTS versions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id    INTEGER NOT NULL REFERENCES servers(id),
    version      TEXT NOT NULL,
    transport    TEXT NOT NULL,
    remote_url   TEXT,
    package      TEXT,
    status       TEXT NOT NULL DEFAULT 'pending_review',
    submitted_by TEXT NOT NULL,
    approved_by  TEXT,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (server_id, version)
);
CREATE TABLE IF NOT EXISTS tools (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id       INTEGER NOT NULL REFERENCES versions(id),
    name             TEXT NOT NULL,
    description      TEXT NOT NULL DEFAULT '',
    schema_json      TEXT NOT NULL DEFAULT '{}',
    risk_class       TEXT NOT NULL DEFAULT 'read',
    annotations_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (version_id, name)
);
CREATE TABLE IF NOT EXISTS registry_audit (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    actor        TEXT NOT NULL,
    action       TEXT NOT NULL,
    target       TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_versions_status ON versions(status);
CREATE INDEX IF NOT EXISTS idx_tools_version ON tools(version_id);
"""


class RegistryStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._init_schema()

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        try:
            yield c
            c.commit()
        finally:
            c.close()

    def _init_schema(self) -> None:
        with self.conn() as c:
            c.executescript(SCHEMA)

    # ---- namespaces ----

    def claim_namespace(self, name: str, owner: str) -> bool:
        """First-come claim. Returns False if already owned by someone else."""
        with self.conn() as c:
            row = c.execute("SELECT owner_user FROM namespaces WHERE name = ?", (name,)).fetchone()
            if row:
                return row["owner_user"] == owner
            c.execute("INSERT INTO namespaces (name, owner_user) VALUES (?, ?)", (name, owner))
            return True

    def list_namespaces(self) -> list[dict[str, Any]]:
        with self.conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM namespaces ORDER BY name")]

    # ---- servers ----

    def get_server(self, namespace: str, name: str) -> dict[str, Any] | None:
        with self.conn() as c:
            row = c.execute(
                "SELECT * FROM servers WHERE namespace = ? AND name = ?", (namespace, name)
            ).fetchone()
            return dict(row) if row else None

    def register_server_json(self, payload: ServerJson, actor: str) -> dict[str, Any]:
        """Idempotent-ish registration: creates the server row on first publish,
        then adds a new immutable version row. Raises ValueError on conflicts."""
        ns, sname = payload.namespace, payload.server_name
        with self.conn() as c:
            ns_row = c.execute("SELECT owner_user FROM namespaces WHERE name = ?", (ns,)).fetchone()
            if not ns_row:
                raise ValueError(f"namespace '{ns}' is not claimed")
            if ns_row["owner_user"] != actor:
                raise ValueError(f"namespace '{ns}' is owned by '{ns_row['owner_user']}'")

            srv = c.execute(
                "SELECT * FROM servers WHERE namespace = ? AND name = ?", (ns, sname)
            ).fetchone()
            if srv is None:
                cur = c.execute(
                    "INSERT INTO servers (namespace, name, description, owner) VALUES (?, ?, ?, ?)",
                    (ns, sname, payload.description, actor),
                )
                server_id = cur.lastrowid
            else:
                server_id = srv["id"]
                if srv["owner"] != actor:
                    raise ValueError(f"server '{payload.name}' is owned by '{srv['owner']}'")

            existing = c.execute(
                "SELECT id, status FROM versions WHERE server_id = ? AND version = ?",
                (server_id, payload.version),
            ).fetchone()
            if existing:
                raise ValueError(
                    f"version {payload.version} already registered "
                    f"(status={existing['status']}); versions are immutable"
                )

            cur = c.execute(
                """INSERT INTO versions
                   (server_id, version, transport, remote_url, package, submitted_by)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    server_id,
                    payload.version,
                    str(payload.transport),
                    payload.remote_url,
                    payload.package,
                    actor,
                ),
            )
            version_id = cur.lastrowid
            for t in payload.tools:
                c.execute(
                    """INSERT INTO tools
                       (version_id, name, description, schema_json, risk_class, annotations_json)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        version_id,
                        t.name,
                        t.description,
                        json.dumps(t.input_schema),
                        str(t.risk_class),
                        json.dumps(t.annotations),
                    ),
                )

        return {"server_id": server_id, "version_id": version_id, "status": "pending_review"}

    def search_servers(
        self, query: str | None = None, status: str | None = None, risk: str | None = None
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT s.namespace, s.name, s.description, s.owner, s.created_at,
                   COUNT(DISTINCT v.id) AS version_count,
                   (SELECT v2.status FROM versions v2
                    WHERE v2.server_id = s.id
                    ORDER BY v2.id DESC LIMIT 1) AS latest_status
            FROM servers s
            LEFT JOIN versions v ON v.server_id = s.id
        """
        clauses, params = [], []
        if status:
            clauses.append(
                "EXISTS (SELECT 1 FROM versions v3 WHERE v3.server_id = s.id AND v3.status = ?)"
            )
            params.append(status)
        if risk:
            clauses.append(
                """EXISTS (SELECT 1 FROM versions v4 JOIN tools t ON t.version_id = v4.id
                          WHERE v4.server_id = s.id AND t.risk_class = ?)"""
            )
            params.append(risk)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " GROUP BY s.id ORDER BY s.namespace, s.name"

        with self.conn() as c:
            rows = [dict(r) for r in c.execute(sql, params)]
        if query:
            q = query.lower()
            rows = [
                r
                for r in rows
                if q in f"{r['namespace']}/{r['name']}".lower() or q in r["description"].lower()
            ]
        return rows

    def get_versions(self, server_id: int) -> list[dict[str, Any]]:
        with self.conn() as c:
            return [
                dict(r)
                for r in c.execute(
                    """SELECT v.*, (SELECT COUNT(*) FROM tools t WHERE t.version_id = v.id)
                          AS tool_count
                       FROM versions v WHERE v.server_id = ? ORDER BY v.id DESC""",
                    (server_id,),
                )
            ]

    def get_version_detail(
        self, namespace: str, name: str, version: str
    ) -> dict[str, Any] | None:
        with self.conn() as c:
            row = c.execute(
                """SELECT v.*, s.namespace, s.name AS server_name
                   FROM versions v JOIN servers s ON s.id = v.server_id
                   WHERE s.namespace = ? AND s.name = ? AND v.version = ?""",
                (namespace, name, version),
            ).fetchone()
            if not row:
                return None
            detail = dict(row)
            detail["tools"] = [
                {
                    **{k: r[k] for k in ("name", "description", "risk_class")},
                    "input_schema": json.loads(r["schema_json"]),
                    "annotations": json.loads(r["annotations_json"]),
                }
                for r in c.execute(
                    "SELECT * FROM tools WHERE version_id = ? ORDER BY name", (row["id"],)
                )
            ]
            return detail
