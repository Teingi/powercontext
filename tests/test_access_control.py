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
    AccessInvalidRequestError,
    AccessProviderCapabilities,
    AccessRequest,
    AccessResourceType,
    AccessRole,
    AccessUnavailableError,
    BuiltinAuthorizationProvider,
    CreateBinding,
    MemoryEntrySelector,
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
            exact = ResourceRef.artifact("scope-a", family="handoff", artifact_id="handoff-a", revision=3)
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
                    AccessAction.ARTIFACT_READ,
                    ResourceRef.artifact("scope-a", family="handoff", artifact_id="handoff-b", revision=1),
                    context=AUDIT,
                )
            with pytest.raises(AccessDeniedError):
                await service.require(BOB, AccessAction.SCOPE_READ, ResourceRef.scope("scope-a"), context=AUDIT)

            visible = await service.list_resources(
                BOB,
                action=AccessAction.ARTIFACT_READ,
                resource_type=AccessResourceType.ARTIFACT,
                family="handoff",
                context=AUDIT,
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
            handoff = ResourceRef.artifact("scope-a", family="handoff", artifact_id="handoff-a", revision=1)
            assert (await service.require(ALICE, AccessAction.ARTIFACT_READ, handoff, context=AUDIT)).allowed
            assert not (await service.check(ALICE, AccessAction.HANDOFF_ACKNOWLEDGE, handoff, context=AUDIT)).allowed

            expired_provider = BuiltinAuthorizationProvider(
                repository,
                bootstrap_administrators=(ADMIN,),
                clock=lambda: NOW + timedelta(hours=2),
            )
            expired = await expired_provider.check(
                AccessRequest(subject=ALICE, action=AccessAction.ARTIFACT_READ, resource=handoff, context=AUDIT)
            )
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


def test_idempotency_key_is_scoped_to_grantor_and_resource() -> None:
    async def scenario() -> None:
        async with SQLiteProfile.open(SQLiteConfig(), tables=ACCESS_TABLES) as profile:
            service, repository = _service(profile.database)
            first = await service.create_binding(
                ADMIN,
                CreateBinding(
                    subject=BOB,
                    resource=ResourceRef.scope("scope-a"),
                    role=AccessRole.SCOPE_VIEWER,
                    idempotency_key="share-viewer",
                ),
                context=AUDIT,
            )
            second = await service.create_binding(
                ADMIN,
                CreateBinding(
                    subject=BOB,
                    resource=ResourceRef.scope("scope-b"),
                    role=AccessRole.SCOPE_VIEWER,
                    idempotency_key="share-viewer",
                ),
                context=AUDIT,
            )
            assert first.binding_id != second.binding_id
            assert await repository.policy_revision() == "2"

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


def test_artifact_family_profiles_enforce_selector_role_and_delegation_boundaries() -> None:
    async def scenario() -> None:
        async with SQLiteProfile.open(SQLiteConfig(), tables=ACCESS_TABLES) as profile:
            service, _ = _service(profile.database)
            await service.create_binding(
                ADMIN,
                CreateBinding(
                    subject=ALICE,
                    resource=ResourceRef.scope("scope-a"),
                    role=AccessRole.SCOPE_DELEGATOR,
                    idempotency_key="alice-scope-delegator",
                ),
                context=AUDIT,
            )
            handoff = ResourceRef.artifact("scope-a", family="handoff", artifact_id="handoff-a", revision=1)
            delegated = await service.create_binding(
                ALICE,
                CreateBinding(
                    subject=BOB,
                    resource=handoff,
                    role=AccessRole.HANDOFF_VIEWER,
                    idempotency_key="bob-handoff-viewer",
                ),
                context=AUDIT,
            )
            assert delegated.granted_by == ALICE

            skill = ResourceRef.artifact("scope-a", family="skill", artifact_id="skill-a", revision=1)
            with pytest.raises(AccessDeniedError):
                await service.create_binding(
                    ALICE,
                    CreateBinding(
                        subject=BOB,
                        resource=skill,
                        role=AccessRole.SKILL_PUBLISHER,
                        idempotency_key="bob-skill-publisher",
                    ),
                    context=AUDIT,
                )
            with pytest.raises(AccessInvalidRequestError, match="role"):
                await service.create_binding(
                    ADMIN,
                    CreateBinding(
                        subject=BOB,
                        resource=handoff,
                        role=AccessRole.ARTIFACT_VIEWER,
                        idempotency_key="invalid-handoff-role",
                    ),
                    context=AUDIT,
                )

            memory_without_selector = ResourceRef.artifact(
                "scope-a", family="memory", artifact_id="memory-a", revision=1
            )
            with pytest.raises(AccessInvalidRequestError, match="Memory Entry Version"):
                await service.check(BOB, AccessAction.ARTIFACT_READ, memory_without_selector, context=AUDIT)
            prompt = ResourceRef.artifact("scope-a", family="prompt", artifact_id="prompt-a", revision=1)
            with pytest.raises(AccessInvalidRequestError, match="disabled"):
                await service.create_binding(
                    ADMIN,
                    CreateBinding(
                        subject=BOB,
                        resource=prompt,
                        role=AccessRole.PROMPT_USER,
                        idempotency_key="disabled-prompt",
                    ),
                    context=AUDIT,
                )

    asyncio.run(scenario())


def test_exact_memory_and_skill_grants_do_not_follow_versions_or_collapse_actions() -> None:
    async def scenario() -> None:
        async with SQLiteProfile.open(SQLiteConfig(), tables=ACCESS_TABLES) as profile:
            service, _ = _service(profile.database)
            memory = ResourceRef.artifact(
                "scope-a",
                family="memory",
                artifact_id="memory-a",
                revision=4,
                selector=MemoryEntrySelector(entry_id="entry-a", entry_version_id="entry-version-2"),
            )
            skill = ResourceRef.artifact("scope-a", family="skill", artifact_id="skill-a", revision=7)
            await service.create_binding(
                ADMIN,
                CreateBinding(
                    subject=BOB,
                    resource=memory,
                    role=AccessRole.ARTIFACT_VIEWER,
                    idempotency_key="bob-memory-entry-version",
                ),
                context=AUDIT,
            )
            await service.create_binding(
                ADMIN,
                CreateBinding(
                    subject=BOB,
                    resource=skill,
                    role=AccessRole.SKILL_PUBLISHER,
                    idempotency_key="bob-skill-publisher",
                ),
                context=AUDIT,
            )

            assert (await service.require(BOB, AccessAction.ARTIFACT_READ, memory, context=AUDIT)).allowed
            future_memory = ResourceRef.artifact(
                "scope-a",
                family="memory",
                artifact_id="memory-a",
                revision=5,
                selector=MemoryEntrySelector(entry_id="entry-a", entry_version_id="entry-version-3"),
            )
            with pytest.raises(AccessDeniedError):
                await service.require(BOB, AccessAction.ARTIFACT_READ, future_memory, context=AUDIT)
            decisions = await service.require_all(
                BOB,
                ((AccessAction.ARTIFACT_READ, skill), (AccessAction.SKILL_PUBLISH, skill)),
                context=AUDIT,
            )
            assert all(decision.allowed for decision in decisions)
            with pytest.raises(AccessInvalidRequestError, match="action"):
                await service.check(BOB, AccessAction.SKILL_PUBLISH, memory, context=AUDIT)

    asyncio.run(scenario())


def test_safe_listing_is_exact_paginated_and_fails_closed_without_provider_support() -> None:
    async def scenario() -> None:
        async with SQLiteProfile.open(SQLiteConfig(), tables=ACCESS_TABLES) as profile:
            service, repository = _service(profile.database)
            resources = tuple(
                ResourceRef.artifact(
                    "scope-a",
                    family="handoff",
                    artifact_id=f"handoff-{index}",
                    revision=1,
                )
                for index in range(3)
            )
            for index, resource in enumerate(resources):
                await service.create_binding(
                    ADMIN,
                    CreateBinding(
                        subject=BOB,
                        resource=resource,
                        role=AccessRole.HANDOFF_VIEWER,
                        idempotency_key=f"handoff-{index}-viewer",
                    ),
                    context=AUDIT,
                )
            first = await service.list_resources(
                BOB,
                action=AccessAction.ARTIFACT_READ,
                resource_type=AccessResourceType.ARTIFACT,
                family="handoff",
                limit=2,
                context=AUDIT,
            )
            assert len(first.items) == 2
            assert first.total == 3
            assert first.next_cursor is not None
            second = await service.list_resources(
                BOB,
                action=AccessAction.ARTIFACT_READ,
                resource_type=AccessResourceType.ARTIFACT,
                family="handoff",
                cursor=first.next_cursor,
                limit=2,
                context=AUDIT,
            )
            assert len(second.items) == 1
            assert second.total == 3
            with pytest.raises(AccessInvalidRequestError, match="cursor"):
                await service.list_resources(
                    BOB,
                    action=AccessAction.ARTIFACT_READ,
                    resource_type=AccessResourceType.ARTIFACT,
                    family="handoff",
                    cursor="not-base64!",
                    context=AUDIT,
                )

            unavailable = AccessControlService(
                service.provider,
                relationships=repository,
                audit=repository,
                provider_capabilities=AccessProviderCapabilities(
                    safe_resource_filtering=False,
                    multi_requirement_check=True,
                    relationship_management=True,
                ),
            )
            with pytest.raises(AccessUnavailableError, match="filtering"):
                await unavailable.list_resources(
                    BOB,
                    action=AccessAction.ARTIFACT_READ,
                    resource_type=AccessResourceType.ARTIFACT,
                    family="handoff",
                    context=AUDIT,
                )
            no_multi_check = AccessControlService(
                service.provider,
                relationships=repository,
                audit=repository,
                provider_capabilities=AccessProviderCapabilities(
                    safe_resource_filtering=True,
                    multi_requirement_check=False,
                    relationship_management=True,
                ),
            )
            with pytest.raises(AccessUnavailableError, match="multi-requirement"):
                await no_multi_check.require_all(
                    BOB,
                    (
                        (AccessAction.ARTIFACT_READ, resources[0]),
                        (AccessAction.HANDOFF_EVIDENCE_READ, resources[0]),
                    ),
                    context=AUDIT,
                )

    asyncio.run(scenario())


def test_access_self_is_not_exposed_as_a_public_audit_action() -> None:
    async def scenario() -> None:
        async with SQLiteProfile.open(SQLiteConfig(), tables=ACCESS_TABLES) as profile:
            service, repository = _service(profile.database)
            decision = await service.check(BOB, AccessAction.ACCESS_SELF, ResourceRef.server(), context=AUDIT)
            assert decision.allowed is True
            assert await repository.list_audit() == ()

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
