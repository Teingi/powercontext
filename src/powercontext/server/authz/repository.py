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

"""Dialect-neutral persistence for Server-owned Access relationships."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from hashlib import sha256
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    insert,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError

from powercontext.builtin.persistence.database import AsyncDatabase
from powercontext.builtin.persistence.tables import identity_string
from powercontext.limits import MAX_ARTIFACT_FAMILY_LENGTH, MAX_ARTIFACT_ID_LENGTH, MAX_SCOPE_ID_LENGTH
from powercontext.server.authz.errors import AccessConflictError, AccessInvalidRequestError
from powercontext.server.authz.models import (
    AccessAction,
    AccessAuditEvent,
    AccessBinding,
    AccessBindingState,
    AccessResourceType,
    AccessRole,
    PrincipalRef,
    ResourceRef,
)

ACCESS_METADATA = MetaData()

ACCESS_POLICY_HEADS_TABLE = Table(
    "pc_access_policy_heads",
    ACCESS_METADATA,
    Column("name", identity_string(32), primary_key=True),
    Column("revision", Integer, nullable=False),
    CheckConstraint("revision >= 0", name="ck_pc_access_policy_heads_revision_nonnegative"),
)

ACCESS_BINDINGS_TABLE = Table(
    "pc_access_bindings",
    ACCESS_METADATA,
    Column("binding_id", identity_string(64), primary_key=True),
    Column("subject_type", identity_string(64), nullable=False),
    Column("subject_issuer", identity_string(255), nullable=False),
    Column("subject_id", identity_string(255), nullable=False),
    Column("resource_type", identity_string(16), nullable=False),
    Column("scope_id", identity_string(MAX_SCOPE_ID_LENGTH)),
    Column("family", identity_string(MAX_ARTIFACT_FAMILY_LENGTH)),
    Column("artifact_id", identity_string(MAX_ARTIFACT_ID_LENGTH)),
    Column("revision", Integer),
    Column("role", identity_string(32), nullable=False),
    Column("granted_by_type", identity_string(64), nullable=False),
    Column("granted_by_issuer", identity_string(255), nullable=False),
    Column("granted_by_id", identity_string(255), nullable=False),
    Column("grantor_key_hash", identity_string(64), nullable=False),
    Column("reason", Text),
    Column("created_at", identity_string(32), nullable=False),
    Column("expires_at", identity_string(32)),
    Column("state", identity_string(16), nullable=False),
    Column("version", Integer, nullable=False),
    Column("policy_revision", identity_string(32), nullable=False),
    Column("idempotency_key", identity_string(255), nullable=False),
    Column("idempotency_key_hash", identity_string(64), nullable=False),
    Column("revoked_at", identity_string(32)),
    Column("revoked_by_type", identity_string(64)),
    Column("revoked_by_issuer", identity_string(255)),
    Column("revoked_by_id", identity_string(255)),
    UniqueConstraint(
        "grantor_key_hash",
        "idempotency_key_hash",
        name="uq_pc_access_bindings_grantor_idempotency",
    ),
    CheckConstraint("version > 0", name="ck_pc_access_bindings_version_positive"),
)

ACCESS_AUDIT_EVENTS_TABLE = Table(
    "pc_access_audit_events",
    ACCESS_METADATA,
    Column("cursor", Integer, primary_key=True, autoincrement=True),
    Column("event_id", identity_string(64), nullable=False, unique=True),
    Column("occurred_at", identity_string(32), nullable=False),
    Column("request_id", identity_string(128)),
    Column("transport", identity_string(16), nullable=False),
    Column("operation", identity_string(128), nullable=False),
    Column("principal_type", identity_string(64), nullable=False),
    Column("principal_issuer", identity_string(255), nullable=False),
    Column("principal_id", identity_string(255), nullable=False),
    Column("action", identity_string(64), nullable=False),
    Column("resource_type", identity_string(16), nullable=False),
    Column("scope_id", identity_string(MAX_SCOPE_ID_LENGTH)),
    Column("family", identity_string(MAX_ARTIFACT_FAMILY_LENGTH)),
    Column("artifact_id", identity_string(MAX_ARTIFACT_ID_LENGTH)),
    Column("revision", Integer),
    Column("allowed", Boolean, nullable=False),
    Column("reason_code", identity_string(64), nullable=False),
    Column("policy_revision", identity_string(32)),
    Column("binding_id", identity_string(64)),
    Column("target_type", identity_string(64)),
    Column("target_issuer", identity_string(255)),
    Column("target_id", identity_string(255)),
    Column("role", identity_string(32)),
)

ACCESS_TABLES = (ACCESS_POLICY_HEADS_TABLE, ACCESS_BINDINGS_TABLE, ACCESS_AUDIT_EVENTS_TABLE)
_POLICY_HEAD = "authorization"


class RelationalAccessRepository:
    """Persist bindings, policy revisions, and data-minimized audit events."""

    def __init__(self, database: AsyncDatabase) -> None:
        self._database = database

    async def policy_revision(self) -> str:
        async with self._database.transaction() as connection:
            row = (
                await connection.execute(
                    select(ACCESS_POLICY_HEADS_TABLE.c.revision).where(ACCESS_POLICY_HEADS_TABLE.c.name == _POLICY_HEAD)
                )
            ).scalar_one_or_none()
            return str(row or 0)

    async def active_bindings(self, subject: PrincipalRef, *, now: datetime) -> tuple[AccessBinding, ...]:
        async with self._database.transaction() as connection:
            rows = (
                (
                    await connection.execute(
                        select(ACCESS_BINDINGS_TABLE).where(
                            ACCESS_BINDINGS_TABLE.c.subject_type == subject.type,
                            ACCESS_BINDINGS_TABLE.c.subject_issuer == subject.issuer,
                            ACCESS_BINDINGS_TABLE.c.subject_id == subject.id,
                            ACCESS_BINDINGS_TABLE.c.state == AccessBindingState.ACTIVE.value,
                        )
                    )
                )
                .mappings()
                .all()
            )
        return tuple(binding for row in rows if (binding := _decode_binding(row)).active_at(now))

    async def get_binding(self, binding_id: str) -> AccessBinding | None:
        async with self._database.transaction() as connection:
            row = (
                (
                    await connection.execute(
                        select(ACCESS_BINDINGS_TABLE).where(ACCESS_BINDINGS_TABLE.c.binding_id == binding_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _decode_binding(row)

    async def list_bindings(
        self,
        *,
        subject: PrincipalRef | None = None,
        resource: ResourceRef | None = None,
        include_revoked: bool = False,
    ) -> tuple[AccessBinding, ...]:
        statement = select(ACCESS_BINDINGS_TABLE)
        if subject is not None:
            statement = statement.where(
                ACCESS_BINDINGS_TABLE.c.subject_type == subject.type,
                ACCESS_BINDINGS_TABLE.c.subject_issuer == subject.issuer,
                ACCESS_BINDINGS_TABLE.c.subject_id == subject.id,
            )
        if resource is not None:
            statement = statement.where(*_resource_predicates(resource))
        if not include_revoked:
            statement = statement.where(ACCESS_BINDINGS_TABLE.c.state == AccessBindingState.ACTIVE.value)
        statement = statement.order_by(ACCESS_BINDINGS_TABLE.c.created_at, ACCESS_BINDINGS_TABLE.c.binding_id)
        async with self._database.transaction() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return tuple(_decode_binding(row) for row in rows)

    async def create_binding(self, binding: AccessBinding) -> AccessBinding:
        async with self._database.transaction() as connection:
            existing = (
                (
                    await connection.execute(
                        select(ACCESS_BINDINGS_TABLE).where(
                            ACCESS_BINDINGS_TABLE.c.grantor_key_hash == _digest(binding.granted_by.key),
                            ACCESS_BINDINGS_TABLE.c.idempotency_key_hash == _digest(binding.idempotency_key),
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                decoded = _decode_binding(existing)
                if _same_creation(decoded, binding):
                    return decoded
                raise AccessConflictError("idempotency-key")
            revision = await self._increment_policy_revision(connection)
            created = replace(binding, policy_revision=str(revision))
            try:
                await connection.execute(insert(ACCESS_BINDINGS_TABLE).values(_binding_row(created)))
            except IntegrityError as error:
                raise AccessConflictError("idempotency-key") from error
            return created

    async def revoke_binding(
        self,
        binding_id: str,
        *,
        expected_version: int,
        revoked_at: datetime,
        revoked_by: PrincipalRef,
    ) -> AccessBinding:
        async with self._database.transaction() as connection:
            row = (
                (
                    await connection.execute(
                        select(ACCESS_BINDINGS_TABLE).where(ACCESS_BINDINGS_TABLE.c.binding_id == binding_id)
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise AccessConflictError("binding-version")
            current = _decode_binding(row)
            if current.version != expected_version or current.state is not AccessBindingState.ACTIVE:
                raise AccessConflictError("binding-version")
            revision = await self._increment_policy_revision(connection)
            result = await connection.execute(
                update(ACCESS_BINDINGS_TABLE)
                .where(
                    ACCESS_BINDINGS_TABLE.c.binding_id == binding_id,
                    ACCESS_BINDINGS_TABLE.c.version == expected_version,
                    ACCESS_BINDINGS_TABLE.c.state == AccessBindingState.ACTIVE.value,
                )
                .values(
                    state=AccessBindingState.REVOKED.value,
                    version=expected_version + 1,
                    policy_revision=str(revision),
                    revoked_at=_timestamp(revoked_at),
                    revoked_by_type=revoked_by.type,
                    revoked_by_issuer=revoked_by.issuer,
                    revoked_by_id=revoked_by.id,
                )
            )
            if result.rowcount != 1:
                raise AccessConflictError("binding-version")
            return replace(
                current,
                state=AccessBindingState.REVOKED,
                version=expected_version + 1,
                policy_revision=str(revision),
                revoked_at=revoked_at,
                revoked_by=revoked_by,
            )

    async def append_audit(self, event: AccessAuditEvent) -> AccessAuditEvent:
        async with self._database.transaction() as connection:
            await connection.execute(insert(ACCESS_AUDIT_EVENTS_TABLE).values(_audit_row(event)))
            cursor = (
                await connection.execute(
                    select(ACCESS_AUDIT_EVENTS_TABLE.c.cursor).where(
                        ACCESS_AUDIT_EVENTS_TABLE.c.event_id == event.event_id
                    )
                )
            ).scalar_one()
        return replace(event, cursor=int(cursor))

    async def list_audit(self, *, after: int | None = None, limit: int = 100) -> tuple[AccessAuditEvent, ...]:
        statement = select(ACCESS_AUDIT_EVENTS_TABLE)
        if after is not None:
            statement = statement.where(ACCESS_AUDIT_EVENTS_TABLE.c.cursor > after)
        statement = statement.order_by(ACCESS_AUDIT_EVENTS_TABLE.c.cursor).limit(limit)
        async with self._database.transaction() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return tuple(_decode_audit(row) for row in rows)

    @staticmethod
    async def _increment_policy_revision(connection: Any) -> int:
        current = (
            await connection.execute(
                select(ACCESS_POLICY_HEADS_TABLE.c.revision).where(ACCESS_POLICY_HEADS_TABLE.c.name == _POLICY_HEAD)
            )
        ).scalar_one_or_none()
        if current is None:
            try:
                await connection.execute(insert(ACCESS_POLICY_HEADS_TABLE).values(name=_POLICY_HEAD, revision=1))
            except IntegrityError as error:
                raise AccessConflictError("binding-version") from error
            return 1
        result = await connection.execute(
            update(ACCESS_POLICY_HEADS_TABLE)
            .where(
                ACCESS_POLICY_HEADS_TABLE.c.name == _POLICY_HEAD,
                ACCESS_POLICY_HEADS_TABLE.c.revision == current,
            )
            .values(revision=current + 1)
        )
        if result.rowcount != 1:
            raise AccessConflictError("binding-version")
        return int(current) + 1


def _resource_predicates(resource: ResourceRef) -> Sequence[Any]:
    return (
        ACCESS_BINDINGS_TABLE.c.resource_type == resource.type.value,
        ACCESS_BINDINGS_TABLE.c.scope_id == resource.scope_id,
        ACCESS_BINDINGS_TABLE.c.family == resource.family,
        ACCESS_BINDINGS_TABLE.c.artifact_id == resource.artifact_id,
        ACCESS_BINDINGS_TABLE.c.revision == resource.revision,
    )


def _binding_row(binding: AccessBinding) -> dict[str, object | None]:
    revoked_by = binding.revoked_by
    return {
        "binding_id": binding.binding_id,
        "subject_type": binding.subject.type,
        "subject_issuer": binding.subject.issuer,
        "subject_id": binding.subject.id,
        "resource_type": binding.resource.type.value,
        "scope_id": binding.resource.scope_id,
        "family": binding.resource.family,
        "artifact_id": binding.resource.artifact_id,
        "revision": binding.resource.revision,
        "role": binding.role.value,
        "granted_by_type": binding.granted_by.type,
        "granted_by_issuer": binding.granted_by.issuer,
        "granted_by_id": binding.granted_by.id,
        "grantor_key_hash": _digest(binding.granted_by.key),
        "reason": binding.reason,
        "created_at": _timestamp(binding.created_at),
        "expires_at": None if binding.expires_at is None else _timestamp(binding.expires_at),
        "state": binding.state.value,
        "version": binding.version,
        "policy_revision": binding.policy_revision,
        "idempotency_key": binding.idempotency_key,
        "idempotency_key_hash": _digest(binding.idempotency_key),
        "revoked_at": None if binding.revoked_at is None else _timestamp(binding.revoked_at),
        "revoked_by_type": None if revoked_by is None else revoked_by.type,
        "revoked_by_issuer": None if revoked_by is None else revoked_by.issuer,
        "revoked_by_id": None if revoked_by is None else revoked_by.id,
    }


def _decode_binding(row: Mapping[Any, Any]) -> AccessBinding:
    resource = _decode_resource(row)
    revoked_by = _optional_principal(row, "revoked_by")
    return AccessBinding(
        binding_id=str(row["binding_id"]),
        subject=_principal(row, "subject"),
        resource=resource,
        role=AccessRole(str(row["role"])),
        granted_by=_principal(row, "granted_by"),
        reason=None if row["reason"] is None else str(row["reason"]),
        created_at=_parse_timestamp(row["created_at"]),
        expires_at=None if row["expires_at"] is None else _parse_timestamp(row["expires_at"]),
        state=AccessBindingState(str(row["state"])),
        version=int(row["version"]),
        policy_revision=str(row["policy_revision"]),
        idempotency_key=str(row["idempotency_key"]),
        revoked_at=None if row["revoked_at"] is None else _parse_timestamp(row["revoked_at"]),
        revoked_by=revoked_by,
    )


def _audit_row(event: AccessAuditEvent) -> dict[str, object | None]:
    target = event.target
    return {
        "event_id": event.event_id,
        "occurred_at": _timestamp(event.occurred_at),
        "request_id": event.request_id,
        "transport": event.transport,
        "operation": event.operation,
        "principal_type": event.principal.type,
        "principal_issuer": event.principal.issuer,
        "principal_id": event.principal.id,
        "action": event.action.value,
        "resource_type": event.resource.type.value,
        "scope_id": event.resource.scope_id,
        "family": event.resource.family,
        "artifact_id": event.resource.artifact_id,
        "revision": event.resource.revision,
        "allowed": event.allowed,
        "reason_code": event.reason_code,
        "policy_revision": event.policy_revision,
        "binding_id": event.binding_id,
        "target_type": None if target is None else target.type,
        "target_issuer": None if target is None else target.issuer,
        "target_id": None if target is None else target.id,
        "role": None if event.role is None else event.role.value,
    }


def _decode_audit(row: Mapping[Any, Any]) -> AccessAuditEvent:
    return AccessAuditEvent(
        cursor=int(row["cursor"]),
        event_id=str(row["event_id"]),
        occurred_at=_parse_timestamp(row["occurred_at"]),
        request_id=None if row["request_id"] is None else str(row["request_id"]),
        transport=str(row["transport"]),
        operation=str(row["operation"]),
        principal=_principal(row, "principal"),
        action=AccessAction(str(row["action"])),
        resource=_decode_resource(row),
        allowed=bool(row["allowed"]),
        reason_code=str(row["reason_code"]),
        policy_revision=None if row["policy_revision"] is None else str(row["policy_revision"]),
        binding_id=None if row["binding_id"] is None else str(row["binding_id"]),
        target=_optional_principal(row, "target"),
        role=None if row["role"] is None else AccessRole(str(row["role"])),
    )


def _decode_resource(row: Mapping[Any, Any]) -> ResourceRef:
    resource_type = AccessResourceType(str(row["resource_type"]))
    if resource_type is AccessResourceType.SERVER:
        return ResourceRef.server()
    if resource_type is AccessResourceType.SCOPE:
        return ResourceRef.scope(str(row["scope_id"]))
    return ResourceRef.handoff(
        str(row["scope_id"]),
        artifact_id=str(row["artifact_id"]),
        revision=int(row["revision"]),
    )


def _principal(row: Mapping[Any, Any], prefix: str) -> PrincipalRef:
    return PrincipalRef(
        type=str(row[f"{prefix}_type"]),
        issuer=str(row[f"{prefix}_issuer"]),
        id=str(row[f"{prefix}_id"]),
    )


def _optional_principal(row: Mapping[Any, Any], prefix: str) -> PrincipalRef | None:
    return None if row[f"{prefix}_type"] is None else _principal(row, prefix)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise AccessInvalidRequestError("timestamp")
    return value.isoformat()


def _parse_timestamp(value: object) -> datetime:
    return datetime.fromisoformat(str(value))


def _same_creation(existing: AccessBinding, requested: AccessBinding) -> bool:
    return (
        existing.subject == requested.subject
        and existing.resource == requested.resource
        and existing.role is requested.role
        and existing.reason == requested.reason
        and existing.expires_at == requested.expires_at
    )


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


__all__ = (
    "ACCESS_TABLES",
    "RelationalAccessRepository",
)
