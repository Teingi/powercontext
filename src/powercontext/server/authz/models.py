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

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from powercontext.server.authz.errors import AccessInvalidRequestError

DEFAULT_DEPLOYMENT_ID = "powercontext"


class AccessAction(StrEnum):
    """Stable actions checked by Server business operations."""

    # Internal authentication-only requirement used by Access self-service routes.
    ACCESS_SELF = "access.self"
    SERVER_OBSERVE = "server.observe"
    SERVER_ADMIN = "server.admin"
    SCOPE_READ = "scope.read"
    SCOPE_CONTRIBUTE = "scope.contribute"
    SCOPE_REVIEW = "scope.review"
    SCOPE_DELEGATE = "scope.delegate"
    SCOPE_ADMIN = "scope.admin"
    ARTIFACT_READ = "artifact.read"
    HANDOFF_EVIDENCE_READ = "handoff.evidence.read"
    HANDOFF_ACKNOWLEDGE = "handoff.acknowledge"
    PROMPT_USE = "prompt.use"
    SKILL_PUBLISH = "skill.publish"


PUBLIC_ACCESS_ACTIONS = tuple(action for action in AccessAction if action is not AccessAction.ACCESS_SELF)


class AccessResourceType(StrEnum):
    """Stable Resource Kinds understood by the authorization boundary."""

    SERVER = "server"
    SCOPE = "scope"
    ARTIFACT = "artifact"


class AccessRole(StrEnum):
    """Fixed first-version roles exposed by the Access API."""

    HANDOFF_VIEWER = "handoff.viewer"
    HANDOFF_RECEIVER = "handoff.receiver"
    ARTIFACT_VIEWER = "artifact.viewer"
    PROMPT_USER = "prompt.user"
    SKILL_PUBLISHER = "skill.publisher"
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
        if not (
            _valid_text(self.type, maximum=64)
            and _valid_text(self.issuer, maximum=255)
            and _valid_text(self.id, maximum=255)
        ):
            raise AccessInvalidRequestError("principal")

    @property
    def key(self) -> str:
        return _canonical_json({"id": self.id, "issuer": self.issuer, "type": self.type})


@dataclass(frozen=True, slots=True)
class AccessArtifactReference:
    """Exact immutable Artifact identity used by one Access resource."""

    family: str
    artifact_id: str
    revision: int

    def __post_init__(self) -> None:
        if not _valid_text(self.family, maximum=128) or not _valid_text(self.artifact_id, maximum=128):
            raise AccessInvalidRequestError("artifact-reference")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 1:
            raise AccessInvalidRequestError("artifact-reference")


@dataclass(frozen=True, slots=True)
class MemoryEntrySelector:
    """Exact Memory Entry Version selected inside one Memory Revision."""

    entry_id: str
    entry_version_id: str

    type: str = "memory_entry"

    def __post_init__(self) -> None:
        if not _valid_text(self.entry_id, maximum=128) or not _valid_text(self.entry_version_id, maximum=128):
            raise AccessInvalidRequestError("memory-entry-selector")


@dataclass(frozen=True, slots=True)
class ResourceRef:
    """Canonical structured target of one authorization decision."""

    type: AccessResourceType
    deployment_id: str | None = None
    scope_id: str | None = None
    reference: AccessArtifactReference | None = None
    selector: MemoryEntrySelector | None = None

    def __post_init__(self) -> None:
        if self.type is AccessResourceType.SERVER:
            valid = (
                _valid_text(self.deployment_id, maximum=128)
                and self.scope_id is None
                and self.reference is None
                and self.selector is None
            )
        elif self.type is AccessResourceType.SCOPE:
            valid = (
                self.deployment_id is None
                and _valid_text(self.scope_id, maximum=256)
                and self.reference is None
                and self.selector is None
            )
        else:
            valid = (
                self.deployment_id is None and _valid_text(self.scope_id, maximum=256) and self.reference is not None
            )
        if not valid:
            raise AccessInvalidRequestError("resource")

    @classmethod
    def server(cls, deployment_id: str = DEFAULT_DEPLOYMENT_ID) -> ResourceRef:
        return cls(type=AccessResourceType.SERVER, deployment_id=deployment_id)

    @classmethod
    def scope(cls, scope_id: str) -> ResourceRef:
        return cls(type=AccessResourceType.SCOPE, scope_id=scope_id)

    @classmethod
    def artifact(
        cls,
        scope_id: str,
        *,
        family: str,
        artifact_id: str,
        revision: int,
        selector: MemoryEntrySelector | None = None,
    ) -> ResourceRef:
        return cls(
            type=AccessResourceType.ARTIFACT,
            scope_id=scope_id,
            reference=AccessArtifactReference(
                family=family,
                artifact_id=artifact_id,
                revision=revision,
            ),
            selector=selector,
        )

    @property
    def family(self) -> str | None:
        return None if self.reference is None else self.reference.family

    @property
    def artifact_id(self) -> str | None:
        return None if self.reference is None else self.reference.artifact_id

    @property
    def revision(self) -> int | None:
        return None if self.reference is None else self.reference.revision

    @property
    def key(self) -> str:
        if self.type is AccessResourceType.SERVER:
            value: dict[str, object] = {"deployment_id": self.deployment_id, "type": self.type.value}
        elif self.type is AccessResourceType.SCOPE:
            value = {"scope_id": self.scope_id, "type": self.type.value}
        else:
            if self.reference is None:
                raise AccessInvalidRequestError("artifact-reference")
            value = {
                "reference": {
                    "artifact_id": self.reference.artifact_id,
                    "family": self.reference.family,
                    "revision": self.reference.revision,
                },
                "scope_id": self.scope_id,
                "selector": (
                    None
                    if self.selector is None
                    else {
                        "entry_id": self.selector.entry_id,
                        "entry_version_id": self.selector.entry_version_id,
                        "type": self.selector.type,
                    }
                ),
                "type": self.type.value,
            }
        return _canonical_json(value)

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
    AccessRole.HANDOFF_VIEWER: frozenset({AccessAction.ARTIFACT_READ, AccessAction.HANDOFF_EVIDENCE_READ}),
    AccessRole.HANDOFF_RECEIVER: frozenset({
        AccessAction.ARTIFACT_READ,
        AccessAction.HANDOFF_EVIDENCE_READ,
        AccessAction.HANDOFF_ACKNOWLEDGE,
    }),
    AccessRole.ARTIFACT_VIEWER: frozenset({AccessAction.ARTIFACT_READ}),
    AccessRole.PROMPT_USER: frozenset({AccessAction.ARTIFACT_READ, AccessAction.PROMPT_USE}),
    AccessRole.SKILL_PUBLISHER: frozenset({AccessAction.ARTIFACT_READ, AccessAction.SKILL_PUBLISH}),
    AccessRole.SCOPE_VIEWER: frozenset({
        AccessAction.SCOPE_READ,
        AccessAction.ARTIFACT_READ,
        AccessAction.HANDOFF_EVIDENCE_READ,
        AccessAction.PROMPT_USE,
    }),
    AccessRole.SCOPE_CONTRIBUTOR: frozenset({
        AccessAction.SCOPE_READ,
        AccessAction.SCOPE_CONTRIBUTE,
        AccessAction.ARTIFACT_READ,
        AccessAction.HANDOFF_EVIDENCE_READ,
        AccessAction.HANDOFF_ACKNOWLEDGE,
        AccessAction.PROMPT_USE,
    }),
    AccessRole.SCOPE_REVIEWER: frozenset({
        AccessAction.SCOPE_READ,
        AccessAction.SCOPE_REVIEW,
        AccessAction.ARTIFACT_READ,
        AccessAction.HANDOFF_EVIDENCE_READ,
        AccessAction.PROMPT_USE,
    }),
    AccessRole.SCOPE_DELEGATOR: frozenset({
        AccessAction.SCOPE_READ,
        AccessAction.SCOPE_DELEGATE,
        AccessAction.ARTIFACT_READ,
        AccessAction.HANDOFF_EVIDENCE_READ,
        AccessAction.PROMPT_USE,
    }),
    AccessRole.SCOPE_ADMIN: frozenset({
        AccessAction.SCOPE_READ,
        AccessAction.SCOPE_CONTRIBUTE,
        AccessAction.SCOPE_REVIEW,
        AccessAction.SCOPE_DELEGATE,
        AccessAction.SCOPE_ADMIN,
        AccessAction.ARTIFACT_READ,
        AccessAction.HANDOFF_EVIDENCE_READ,
        AccessAction.HANDOFF_ACKNOWLEDGE,
        AccessAction.PROMPT_USE,
        AccessAction.SKILL_PUBLISH,
    }),
    AccessRole.SERVER_OBSERVER: frozenset({AccessAction.SERVER_OBSERVE}),
    AccessRole.SERVER_ADMIN: frozenset(AccessAction),
}

ROLE_RESOURCE_TYPES: dict[AccessRole, AccessResourceType] = {
    AccessRole.HANDOFF_VIEWER: AccessResourceType.ARTIFACT,
    AccessRole.HANDOFF_RECEIVER: AccessResourceType.ARTIFACT,
    AccessRole.ARTIFACT_VIEWER: AccessResourceType.ARTIFACT,
    AccessRole.PROMPT_USER: AccessResourceType.ARTIFACT,
    AccessRole.SKILL_PUBLISHER: AccessResourceType.ARTIFACT,
    AccessRole.SCOPE_VIEWER: AccessResourceType.SCOPE,
    AccessRole.SCOPE_CONTRIBUTOR: AccessResourceType.SCOPE,
    AccessRole.SCOPE_REVIEWER: AccessResourceType.SCOPE,
    AccessRole.SCOPE_DELEGATOR: AccessResourceType.SCOPE,
    AccessRole.SCOPE_ADMIN: AccessResourceType.SCOPE,
    AccessRole.SERVER_OBSERVER: AccessResourceType.SERVER,
    AccessRole.SERVER_ADMIN: AccessResourceType.SERVER,
}


def _valid_text(value: object, *, maximum: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip() and len(value) <= maximum


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


__all__ = (
    "DEFAULT_DEPLOYMENT_ID",
    "PUBLIC_ACCESS_ACTIONS",
    "ROLE_ACTIONS",
    "ROLE_RESOURCE_TYPES",
    "AccessAction",
    "AccessArtifactReference",
    "AccessAuditEvent",
    "AccessBinding",
    "AccessBindingState",
    "AccessDecision",
    "AccessResourceType",
    "AccessRole",
    "MemoryEntrySelector",
    "PrincipalRef",
    "ResourceRef",
)
