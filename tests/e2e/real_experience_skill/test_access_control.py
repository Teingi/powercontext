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

"""Explicitly enabled Access Control acceptance against the configured database."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from dotenv import load_dotenv
from sqlalchemy import delete, func, select

from powercontext.builtin.persistence.oceanbase import OceanBaseConfig, OceanBaseProfile
from powercontext.builtin.persistence.seekdb import SeekDBConfig, SeekDBProfile
from powercontext.builtin.persistence.sqlite import SQLiteConfig, SQLiteProfile
from powercontext.builtin.runtime import DatabaseConfig
from powercontext.server.authz import (
    AccessAction,
    AccessAuditContext,
    AccessDeniedError,
    AccessResourceType,
    AccessRole,
    CreateBinding,
    PrincipalRef,
    ResourceRef,
)
from powercontext.server.authz.composition import open_builtin_access_control
from powercontext.server.authz.repository import ACCESS_AUDIT_EVENTS_TABLE, ACCESS_BINDINGS_TABLE
from powercontext.server.settings import ServerSettings

pytestmark = pytest.mark.real_e2e


def test_configured_database_persists_exact_skill_grant_and_revocation(pytestconfig: pytest.Config) -> None:
    if pytestconfig.getoption("real_e2e_mode") not in {"configured", "all"}:
        pytest.skip("configured Access Control acceptance runs in configured mode")

    load_dotenv(pytestconfig.getoption("real_e2e_env_file"), override=False)
    settings = ServerSettings()
    suffix = uuid4().hex
    scope_id = f"configured-real-access:{suffix}"
    deployment_id = f"configured-real-access-{suffix}"
    admin = PrincipalRef(type="service", issuer=f"powercontext:{deployment_id}", id="admin")
    receiver = PrincipalRef(type="user", issuer=f"powercontext:{deployment_id}", id="receiver")

    async def scenario() -> None:
        exact = ResourceRef.artifact(
            scope_id,
            family="skill",
            artifact_id=f"managed-skill-{suffix}",
            revision=7,
        )
        adjacent = ResourceRef.artifact(
            scope_id,
            family="skill",
            artifact_id=f"managed-skill-{suffix}",
            revision=8,
        )
        context = AccessAuditContext(transport="test", operation="configured-real-access")
        try:
            async with open_builtin_access_control(
                settings.database,
                bootstrap_administrators=(admin,),
                deployment_id=deployment_id,
            ) as access:
                binding = await access.create_binding(
                    admin,
                    CreateBinding(
                        subject=receiver,
                        resource=exact,
                        role=AccessRole.SKILL_PUBLISHER,
                        idempotency_key=f"publish-exact-skill-{suffix}",
                    ),
                    context=context,
                )
                decisions = await access.require_all(
                    receiver,
                    (
                        (AccessAction.ARTIFACT_READ, exact),
                        (AccessAction.SKILL_PUBLISH, exact),
                    ),
                    context=context,
                )
                assert all(decision.allowed for decision in decisions)
                with pytest.raises(AccessDeniedError):
                    await access.require(receiver, AccessAction.ARTIFACT_READ, adjacent, context=context)

                visible = await access.list_resources(
                    receiver,
                    action=AccessAction.ARTIFACT_READ,
                    resource_type=AccessResourceType.ARTIFACT,
                    family="skill",
                    context=context,
                )
                assert visible.items == (exact,)
                assert visible.total == 1

                revoked = await access.revoke_binding(
                    admin,
                    binding.binding_id,
                    expected_version=binding.version,
                    context=context,
                )
                assert revoked.version == binding.version + 1
                with pytest.raises(AccessDeniedError):
                    await access.require(receiver, AccessAction.ARTIFACT_READ, exact, context=context)
                assert (
                    await access.list_resources(
                        receiver,
                        action=AccessAction.ARTIFACT_READ,
                        resource_type=AccessResourceType.ARTIFACT,
                        family="skill",
                        context=context,
                    )
                ).total == 0
        finally:
            remaining = await _purge_scope(settings.database, scope_id)
            assert remaining == 0

    asyncio.run(scenario())


async def _purge_scope(database: DatabaseConfig, scope_id: str) -> int:
    async with _profile(database) as profile, profile.database.transaction() as connection:
        await connection.execute(
            delete(ACCESS_AUDIT_EVENTS_TABLE).where(ACCESS_AUDIT_EVENTS_TABLE.c.scope_id == scope_id)
        )
        await connection.execute(delete(ACCESS_BINDINGS_TABLE).where(ACCESS_BINDINGS_TABLE.c.scope_id == scope_id))
        binding_count = int(
            await connection.scalar(
                select(func.count())
                .select_from(ACCESS_BINDINGS_TABLE)
                .where(ACCESS_BINDINGS_TABLE.c.scope_id == scope_id)
            )
            or 0
        )
        audit_count = int(
            await connection.scalar(
                select(func.count())
                .select_from(ACCESS_AUDIT_EVENTS_TABLE)
                .where(ACCESS_AUDIT_EVENTS_TABLE.c.scope_id == scope_id)
            )
            or 0
        )
        return binding_count + audit_count


@asynccontextmanager
async def _profile(database: DatabaseConfig) -> AsyncIterator[OceanBaseProfile | SeekDBProfile | SQLiteProfile]:
    if isinstance(database, OceanBaseConfig):
        context = OceanBaseProfile.open(database, tables=())
    elif isinstance(database, SeekDBConfig):
        context = SeekDBProfile.open(database, tables=())
    else:
        assert isinstance(database, SQLiteConfig)
        context = SQLiteProfile.open(database, tables=())
    async with context as profile:
        yield profile
