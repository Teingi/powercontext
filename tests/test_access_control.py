# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from powercontext.builtin.persistence.sqlite import SQLiteConfig, SQLiteProfile
from powercontext.server.authz import (
    AccessAction,
    AccessAuditContext,
    AccessConflictError,
    AccessControlService,
    AccessDeniedError,
    AccessResourceType,
    AccessRole,
    BuiltinAuthorizationProvider,
    CreateBinding,
    PrincipalRef,
    ResourceRef,
)
from powercontext.server.authz.repository import ACCESS_TABLES, RelationalAccessRepository

NOW = datetime(2026, 8, 30, 10, tzinfo=UTC)
ADMIN = PrincipalRef(type="user", issuer="https://identity.example", id="admin")
ALICE = PrincipalRef(type="user", issuer="https://identity.example", id="alice")
BOB = PrincipalRef(type="user", issuer="https://identity.example", id="bob")
AUDIT = AccessAuditContext(transport="http", operation="test", request_id="req-1")


def test_exact_handoff_receiver_cannot_discover_other_handoffs_or_scope_data() -> None:
    async def scenario() -> None:
        async with SQLiteProfile.open(SQLiteConfig(), tables=ACCESS_TABLES) as profile:
            service, repository = _service(profile.database)
            exact = ResourceRef.handoff("scope-a", artifact_id="handoff-a", revision=3)
            created = await service.create_binding(
                ADMIN,
                CreateBinding(
                    subject=BOB,
                    resource=exact,
                    role=AccessRole.HANDOFF_RECEIVER,
                    idempotency_key="handoff-a-to-bob",
                ),
                context=AUDIT,
            )

            allowed = await service.require(
                BOB,
                AccessAction.HANDOFF_ACKNOWLEDGE,
                exact,
                context=AUDIT,
            )
            assert allowed.allowed is True
            with pytest.raises(AccessDeniedError):
                await service.require(
                    BOB,
                    AccessAction.HANDOFF_READ,
                    ResourceRef.handoff("scope-a", artifact_id="handoff-b", revision=1),
                    context=AUDIT,
                )
            with pytest.raises(AccessDeniedError):
                await service.require(BOB, AccessAction.SCOPE_READ, ResourceRef.scope("scope-a"), context=AUDIT)

            visible = await service.provider.list_resources(
                BOB,
                action=AccessAction.HANDOFF_READ,
                resource_type=AccessResourceType.HANDOFF,
            )
            assert visible.items == (exact,)
            assert created.policy_revision == "1"
            assert len(await repository.list_audit()) == 5

    asyncio.run(scenario())


def test_scope_role_covers_handoffs_but_expired_bindings_do_not() -> None:
    async def scenario() -> None:
        async with SQLiteProfile.open(SQLiteConfig(), tables=ACCESS_TABLES) as profile:
            service, repository = _service(profile.database)
            await service.create_binding(
                ADMIN,
                CreateBinding(
                    subject=ALICE,
                    resource=ResourceRef.scope("scope-a"),
                    role=AccessRole.SCOPE_VIEWER,
                    idempotency_key="scope-a-viewer",
                    expires_at=NOW + timedelta(hours=1),
                ),
                context=AUDIT,
            )
            handoff = ResourceRef.handoff("scope-a", artifact_id="handoff-a", revision=1)
            assert (await service.require(ALICE, AccessAction.HANDOFF_READ, handoff, context=AUDIT)).allowed
            assert not (await service.check(ALICE, AccessAction.HANDOFF_ACKNOWLEDGE, handoff, context=AUDIT)).allowed

            expired_provider = BuiltinAuthorizationProvider(
                repository,
                bootstrap_administrators=(ADMIN,),
                clock=lambda: NOW + timedelta(hours=2),
            )
            expired = await expired_provider.check(ALICE, AccessAction.HANDOFF_READ, handoff)
            assert expired.allowed is False

    asyncio.run(scenario())


def test_binding_creation_is_idempotent_and_revocation_uses_cas() -> None:
    async def scenario() -> None:
        async with SQLiteProfile.open(SQLiteConfig(), tables=ACCESS_TABLES) as profile:
            service, repository = _service(profile.database)
            request = CreateBinding(
                subject=BOB,
                resource=ResourceRef.scope("scope-a"),
                role=AccessRole.SCOPE_VIEWER,
                idempotency_key="stable-key",
                reason="pairing session",
            )
            first = await service.create_binding(ADMIN, request, context=AUDIT)
            repeated = await service.create_binding(ADMIN, request, context=AUDIT)
            assert repeated.binding_id == first.binding_id
            assert await repository.policy_revision() == "1"

            with pytest.raises(AccessConflictError, match="idempotency"):
                await service.create_binding(
                    ADMIN,
                    CreateBinding(
                        subject=ALICE,
                        resource=request.resource,
                        role=request.role,
                        idempotency_key=request.idempotency_key,
                    ),
                    context=AUDIT,
                )

            revoked = await service.revoke_binding(
                ADMIN,
                first.binding_id,
                expected_version=1,
                context=AUDIT,
            )
            assert revoked.version == 2
            assert revoked.policy_revision == "2"
            with pytest.raises(AccessConflictError, match="version"):
                await service.revoke_binding(
                    ADMIN,
                    first.binding_id,
                    expected_version=1,
                    context=AUDIT,
                )

    asyncio.run(scenario())


def test_persisted_server_admin_covers_scope_administration() -> None:
    async def scenario() -> None:
        async with SQLiteProfile.open(SQLiteConfig(), tables=ACCESS_TABLES) as profile:
            service, _ = _service(profile.database)
            await service.create_binding(
                ADMIN,
                CreateBinding(
                    subject=ALICE,
                    resource=ResourceRef.server(),
                    role=AccessRole.SERVER_ADMIN,
                    idempotency_key="alice-server-admin",
                ),
                context=AUDIT,
            )
            delegated = await service.create_binding(
                ALICE,
                CreateBinding(
                    subject=BOB,
                    resource=ResourceRef.scope("scope-a"),
                    role=AccessRole.SCOPE_VIEWER,
                    idempotency_key="bob-scope-viewer",
                ),
                context=AUDIT,
            )

            assert delegated.granted_by == ALICE
            assert (
                await service.require(BOB, AccessAction.SCOPE_READ, ResourceRef.scope("scope-a"), context=AUDIT)
            ).allowed

    asyncio.run(scenario())


def _service(database) -> tuple[AccessControlService, RelationalAccessRepository]:
    repository = RelationalAccessRepository(database)
    provider = BuiltinAuthorizationProvider(
        repository,
        bootstrap_administrators=(ADMIN,),
        clock=lambda: NOW,
    )
    return (
        AccessControlService(provider, relationships=repository, audit=repository, clock=lambda: NOW),
        repository,
    )
