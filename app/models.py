"""Pydantic models: server.json-compatible payloads and registry API shapes."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Official-registry-style name: "namespace/server-name", lowercase, dashes.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*$")
NAMESPACE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


class Transport(StrEnum):
    STREAMABLE_HTTP = "streamable-http"
    STDIO = "stdio"


class RiskClass(StrEnum):
    READ = "read"
    WRITE = "write"
    DANGEROUS = "dangerous"


class VersionStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    DEPRECATED = "deprecated"


class ToolSpec(BaseModel):
    """One tool entry, mirroring MCP list_tools output + registry risk class."""

    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    risk_class: RiskClass = RiskClass.READ
    annotations: dict[str, Any] = Field(default_factory=dict)


class ServerJson(BaseModel):
    """server.json-compatible registration payload (deliberately narrow:
    metadata + schema + pointers, never packages/binaries)."""

    name: str  # "namespace/server-name"
    description: str = ""
    version: str
    transport: Transport
    remote_url: str | None = None  # for streamable-http remotes
    package: str | None = None  # pointer only, e.g. "npm:@acme/billing-mcp@1.0.0"
    tools: list[ToolSpec] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        if not NAME_RE.match(v):
            raise ValueError("name must look like 'namespace/server-name' (lowercase, dashes)")
        return v

    @field_validator("version")
    @classmethod
    def _valid_version(cls, v: str) -> str:
        if not SEMVER_RE.match(v):
            raise ValueError("version must be semver, e.g. '1.0.0'")
        return v

    @model_validator(mode="after")
    def _transport_pointer(self) -> "ServerJson":
        if self.transport == Transport.STREAMABLE_HTTP and not self.remote_url:
            raise ValueError("streamable-http transport requires remote_url")
        if self.transport == Transport.STDIO and not self.package:
            raise ValueError("stdio transport requires a package pointer")
        return self

    @property
    def namespace(self) -> str:
        return self.name.split("/", 1)[0]

    @property
    def server_name(self) -> str:
        return self.name.split("/", 1)[1]


# ---- API request/response shapes ----


class NamespaceClaim(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _valid_ns(cls, v: str) -> str:
        if not NAMESPACE_RE.match(v):
            raise ValueError("namespace must be lowercase letters/digits/dashes")
        return v


class VersionSummary(BaseModel):
    id: int
    version: str
    status: VersionStatus
    transport: Transport
    remote_url: str | None
    package: str | None
    tool_count: int
    submitted_by: str
    created_at: str


class ServerSummary(BaseModel):
    namespace: str
    name: str
    full_name: str
    description: str
    owner: str
    latest_status: VersionStatus | None
    version_count: int
    created_at: str


class ServerDetail(BaseModel):
    namespace: str
    name: str
    full_name: str
    description: str
    owner: str
    created_at: str
    versions: list[VersionSummary]


class ToolOut(BaseModel):
    name: str
    description: str
    risk_class: RiskClass
    input_schema: dict[str, Any]
    annotations: dict[str, Any]


class VersionDetail(BaseModel):
    id: int
    server: str  # full name
    version: str
    status: VersionStatus
    transport: Transport
    remote_url: str | None
    package: str | None
    submitted_by: str
    approved_by: str | None
    created_at: str
    tools: list[ToolOut]
