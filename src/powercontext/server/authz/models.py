# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Transport-independent Access Control values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from powercontext.server.authz.errors import AccessInvalidRequestError


class AccessAction(StrEnum):
    """Stable actions checked by Server business operations."""

    ACCESS_SELF = "access.self"
    SERVER_OBSERVE = "server.observe"
    SERVER_ADMIN = "server.admin"
    SCOPE_READ = "scope.read"
    SCOPE_CONTRIBUTE = "scope.contribute"
    SCOPE_REVIEW = "scope.review"
    SCOPE_DELEGATE = "scope.delegate"
    SCOPE_ADMIN = "scope.admin"
    HANDOFF_READ = "handoff.read"
    HANDOFF_EVIDENCE_READ = "handoff.evidence.read"
    HANDOFF_ACKNOWLEDGE = "handoff.acknowledge"


class AccessResourceType(StrEnum):
    """Resource types understood by the first authorization profile."""

    SERVER = "server"
    SCOPE = "scope"
    HANDOFF = "handoff"


class AccessRole(StrEnum):
    """Fixed first-version roles exposed by the Access API."""

    HANDOFF_VIEWER = "handoff.viewer"
    HANDOFF_RECEIVER = "handoff.receiver"
    SCOPE_VIEWER = "scope.viewer"
    SCOPE_CONTRIBUTOR = "scope.contributor"
    SCOPE_REVIEWER = "scope.reviewer"
    SCOPE_DELEGATOR = "scope.delegator"
    SCOPE_ADMIN = "scope.admin"
    SERVER_OBSERVER = "server.observer"
    SERVER_ADMIN = "server.admin"


class AccessBindingState(StrEnum):
    """Lifecycle state of an immutable role assignment."""

    ACTIVE = "active"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class PrincipalRef:
    """Stable opaque identity established by authentication."""

    type: str
    issuer: str
    id: str

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value and value.strip() for value in (self.type, self.issuer, self.id)):
            raise AccessInvalidRequestError("principal")

    @property
    def key(self) -> str:
        return "\x1f".join((self.type, self.issuer, self.id))


@dataclass(frozen=True, slots=True)
class ResourceRef:
    """Canonical structured target of one authorization decision."""

    type: AccessResourceType
    scope_id: str | None = None
    family: str | None = None
    artifact_id: str | None = None
    revision: int | None = None

    def __post_init__(self) -> None:
        if self.type is AccessResourceType.SERVER:
            valid = self.scope_id is None and self.family is None and self.artifact_id is None and self.revision is None
        elif self.type is AccessResourceType.SCOPE:
            valid = bool(self.scope_id) and self.family is None and self.artifact_id is None and self.revision is None
        else:
            valid = (
                bool(self.scope_id)
                and self.family == "handoff"
                and bool(self.artifact_id)
                and self.revision is not None
                and self.revision > 0
            )
        if not valid:
            raise AccessInvalidRequestError(
                "handoff-reference" if self.type is AccessResourceType.HANDOFF else "resource"
            )

    @classmethod
    def server(cls) -> ResourceRef:
        return cls(type=AccessResourceType.SERVER)

    @classmethod
    def scope(cls, scope_id: str) -> ResourceRef:
        return cls(type=AccessResourceType.SCOPE, scope_id=scope_id)

    @classmethod
    def handoff(
        cls,
        scope_id: str,
        *,
        artifact_id: str,
        revision: int,
    ) -> ResourceRef:
        return cls(
            type=AccessResourceType.HANDOFF,
            scope_id=scope_id,
            family="handoff",
            artifact_id=artifact_id,
            revision=revision,
        )

    @property
    def key(self) -> str:
        values = (
            self.type.value,
            self.scope_id or "",
            self.family or "",
            self.artifact_id or "",
            "" if self.revision is None else str(self.revision),
        )
        return "\x1f".join(values)

    @property
    def parent_scope(self) -> ResourceRef | None:
        return None if self.scope_id is None else ResourceRef.scope(self.scope_id)


@dataclass(frozen=True, slots=True)
class AccessDecision:
    """One low-sensitivity authorization result."""

    allowed: bool
    reason_code: str
    policy_revision: str | None


@dataclass(frozen=True, slots=True)
class AccessBinding:
    """One persisted role assignment."""

    binding_id: str
    subject: PrincipalRef
    resource: ResourceRef
    role: AccessRole
    granted_by: PrincipalRef
    reason: str | None
    created_at: datetime
    expires_at: datetime | None
    state: AccessBindingState
    version: int
    policy_revision: str
    idempotency_key: str
    revoked_at: datetime | None = None
    revoked_by: PrincipalRef | None = None

    def active_at(self, now: datetime) -> bool:
        return self.state is AccessBindingState.ACTIVE and (self.expires_at is None or self.expires_at > now)


@dataclass(frozen=True, slots=True)
class AccessAuditEvent:
    """Data-minimized authorization or relationship audit record."""

    cursor: int | None
    event_id: str
    occurred_at: datetime
    request_id: str | None
    transport: str
    operation: str
    principal: PrincipalRef
    action: AccessAction
    resource: ResourceRef
    allowed: bool
    reason_code: str
    policy_revision: str | None
    binding_id: str | None = None
    target: PrincipalRef | None = None
    role: AccessRole | None = None


ROLE_ACTIONS: dict[AccessRole, frozenset[AccessAction]] = {
    AccessRole.HANDOFF_VIEWER: frozenset({AccessAction.HANDOFF_READ, AccessAction.HANDOFF_EVIDENCE_READ}),
    AccessRole.HANDOFF_RECEIVER: frozenset({
        AccessAction.HANDOFF_READ,
        AccessAction.HANDOFF_EVIDENCE_READ,
        AccessAction.HANDOFF_ACKNOWLEDGE,
    }),
    AccessRole.SCOPE_VIEWER: frozenset({
        AccessAction.SCOPE_READ,
        AccessAction.HANDOFF_READ,
        AccessAction.HANDOFF_EVIDENCE_READ,
    }),
    AccessRole.SCOPE_CONTRIBUTOR: frozenset({
        AccessAction.SCOPE_READ,
        AccessAction.SCOPE_CONTRIBUTE,
        AccessAction.HANDOFF_READ,
        AccessAction.HANDOFF_EVIDENCE_READ,
        AccessAction.HANDOFF_ACKNOWLEDGE,
    }),
    AccessRole.SCOPE_REVIEWER: frozenset({
        AccessAction.SCOPE_READ,
        AccessAction.SCOPE_REVIEW,
        AccessAction.HANDOFF_READ,
        AccessAction.HANDOFF_EVIDENCE_READ,
    }),
    AccessRole.SCOPE_DELEGATOR: frozenset({
        AccessAction.SCOPE_READ,
        AccessAction.SCOPE_DELEGATE,
        AccessAction.HANDOFF_READ,
        AccessAction.HANDOFF_EVIDENCE_READ,
    }),
    AccessRole.SCOPE_ADMIN: frozenset({
        AccessAction.SCOPE_READ,
        AccessAction.SCOPE_CONTRIBUTE,
        AccessAction.SCOPE_REVIEW,
        AccessAction.SCOPE_DELEGATE,
        AccessAction.SCOPE_ADMIN,
        AccessAction.HANDOFF_READ,
        AccessAction.HANDOFF_EVIDENCE_READ,
        AccessAction.HANDOFF_ACKNOWLEDGE,
    }),
    AccessRole.SERVER_OBSERVER: frozenset({AccessAction.SERVER_OBSERVE}),
    AccessRole.SERVER_ADMIN: frozenset(AccessAction),
}

ROLE_RESOURCE_TYPES: dict[AccessRole, AccessResourceType] = {
    AccessRole.HANDOFF_VIEWER: AccessResourceType.HANDOFF,
    AccessRole.HANDOFF_RECEIVER: AccessResourceType.HANDOFF,
    AccessRole.SCOPE_VIEWER: AccessResourceType.SCOPE,
    AccessRole.SCOPE_CONTRIBUTOR: AccessResourceType.SCOPE,
    AccessRole.SCOPE_REVIEWER: AccessResourceType.SCOPE,
    AccessRole.SCOPE_DELEGATOR: AccessResourceType.SCOPE,
    AccessRole.SCOPE_ADMIN: AccessResourceType.SCOPE,
    AccessRole.SERVER_OBSERVER: AccessResourceType.SERVER,
    AccessRole.SERVER_ADMIN: AccessResourceType.SERVER,
}


__all__ = (
    "ROLE_ACTIONS",
    "ROLE_RESOURCE_TYPES",
    "AccessAction",
    "AccessAuditEvent",
    "AccessBinding",
    "AccessBindingState",
    "AccessDecision",
    "AccessResourceType",
    "AccessRole",
    "PrincipalRef",
    "ResourceRef",
)
