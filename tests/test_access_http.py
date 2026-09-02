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
from pathlib import Path
from types import SimpleNamespace
from typing import Self

import httpx
import pytest
from starlette.middleware import Middleware

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import MemoryEntryVersion
from powercontext.builtin.artifacts.skill import AgentSkillTarget, Skill, SkillContent
from powercontext.builtin.persistence.sqlite import SQLiteConfig, SQLiteProfile
from powercontext.builtin.runtime import MemoryEntryRecord
from powercontext.server.app import create_app
from powercontext.server.authz import (
    AccessAuditContext,
    AccessControlService,
    AccessRole,
    BuiltinAuthorizationProvider,
    CreateBinding,
    MemoryEntrySelector,
    PrincipalRef,
    ResourceRef,
)
from powercontext.server.authz.repository import ACCESS_TABLES, RelationalAccessRepository
from powercontext.server.factory import create_server_app
from powercontext.server.middleware import StaticBearerMiddleware
from powercontext.server.settings import AccessControlConfig, ServerSettings
from powercontext.server.web import mount_web_ui

ADMIN = PrincipalRef(type="user", issuer="https://identity.example", id="admin")
BOB = PrincipalRef(type="user", issuer="https://identity.example", id="bob")
ALICE = PrincipalRef(type="user", issuer="https://identity.example", id="alice")
AUDIT = AccessAuditContext(transport="test", operation="seed")


def test_enforced_mode_cannot_silently_start_without_authentication_or_provider() -> None:
    with pytest.raises(ValueError, match="enforced Access Control"):
        create_server_app(settings=ServerSettings(access=AccessControlConfig(mode="enforced")))


def test_low_level_enforced_app_fails_closed_without_an_authorization_provider() -> None:
    async def scenario() -> None:
        async with _client(create_app(access_mode="enforced")) as client:
            readiness = await client.get("/health/ready")
            capabilities = await client.get("/v1/capabilities")

        assert readiness.status_code == 503
        assert readiness.json()["checks"]["access_provider"] == "not_ready"
        assert capabilities.status_code == 503
        assert capabilities.json()["error"]["code"] == "access_unavailable"

    asyncio.run(scenario())


class _HandoffShareability:
    def for_scope(self, scope_id: str) -> Self:
        del scope_id
        return self

    async def revision(self, artifact) -> object:
        del artifact
        return object()


class _MemoryApplication:
    def __init__(self, record: MemoryEntryRecord) -> None:
        self.record = record

    def for_scope(self, scope_id: str) -> Self:
        del scope_id
        return self

    async def get(self, request) -> MemoryEntryRecord:
        del request
        return self.record


class _SkillApplication:
    def __init__(self, result: object | None = None) -> None:
        self.get_calls = 0
        self.result = object() if result is None else result

    def for_scope(self, scope_id: str) -> Self:
        del scope_id
        return self

    async def get(self, request) -> object:
        del request
        self.get_calls += 1
        return self.result


class _ExternalSkillsApplication:
    def for_scope(self, scope_id: str) -> Self:
        del scope_id
        return self

    async def scan(self) -> object:
        return object()


def test_access_api_and_handoff_pep_enforce_exact_receiver_visibility() -> None:
    async def scenario() -> None:
        async with SQLiteProfile.open(SQLiteConfig(), tables=ACCESS_TABLES) as profile:
            repository = RelationalAccessRepository(profile.database)
            service = AccessControlService(
                BuiltinAuthorizationProvider(repository, bootstrap_administrators=(ADMIN,)),
                relationships=repository,
                audit=repository,
            )
            admin_app = _app(
                service,
                principal=ADMIN,
                token="admin-token",  # noqa: S106 - test credential.
                application=SimpleNamespace(handoff=_HandoffShareability()),
            )
            async with _client(admin_app) as admin:
                readiness = await admin.get("/health/ready")
                assert readiness.status_code == 200
                readiness_checks = readiness.json()["checks"]
                assert readiness_checks["access_mode"] == "enforced"
                assert readiness_checks["access_provider"] == "ready"
                assert readiness_checks["access_resource_kinds"] == "server,scope,artifact"
                principal = await admin.get("/v1/access/me", headers=_auth("admin-token"))
                assert principal.status_code == 200
                assert principal.json()["principal"] == {
                    "type": "user",
                    "issuer": "https://identity.example",
                    "id": "admin",
                }
                assert principal.json()["mode"] == "enforced"
                assert principal.json()["resource_kinds"] == ["server", "scope", "artifact"]
                assert {
                    profile["family"] for profile in principal.json()["artifact_families"] if profile["enabled"]
                } == {
                    "handoff",
                    "memory",
                    "experience",
                    "skill",
                }
                created = await admin.post(
                    "/v1/access/bindings/create",
                    headers=_auth("admin-token"),
                    json={
                        "subject": {"type": "user", "issuer": "https://identity.example", "id": "bob"},
                        "resource": {
                            "type": "artifact",
                            "scope_id": "scope-a",
                            "reference": {"family": "handoff", "artifact_id": "handoff-a", "revision": 3},
                            "selector": None,
                        },
                        "role": "handoff.receiver",
                        "idempotency_key": "handoff-a-to-bob",
                    },
                )
                assert created.status_code == 201
                assert created.json()["policy_revision"] == "1"

            bob_app = _app(service, principal=BOB, token="bob-token")  # noqa: S106 - test credential.
            async with _client(bob_app) as bob:
                exact = {
                    "type": "artifact",
                    "scope_id": "scope-a",
                    "reference": {"family": "handoff", "artifact_id": "handoff-a", "revision": 3},
                    "selector": None,
                }
                decision = await bob.post(
                    "/v1/access/check",
                    headers=_auth("bob-token"),
                    json={"action": "handoff.acknowledge", "resource": exact},
                )
                assert decision.status_code == 200
                assert decision.json()["allowed"] is True

                resources = await bob.post(
                    "/v1/access/resources/list",
                    headers=_auth("bob-token"),
                    json={"action": "artifact.read", "resource_type": "artifact", "family": "handoff"},
                )
                assert resources.status_code == 200
                assert resources.json()["items"] == [exact]
                assert resources.json()["total"] == 1

                denied = await bob.post(
                    "/v1/handoff/continue",
                    headers=_auth("bob-token"),
                    json={
                        "scope_id": "scope-a",
                        "selection": "exact",
                        "revision": {"family": "handoff", "artifact_id": "handoff-b", "revision": 1},
                    },
                )
                assert denied.status_code == 403, denied.json()
                assert denied.json()["error"]["code"] == "forbidden"

                latest = await bob.post(
                    "/v1/handoff/continue",
                    headers=_auth("bob-token"),
                    json={"scope_id": "scope-a", "selection": "latest"},
                )
                assert latest.status_code == 403

                allowed_to_runtime_boundary = await bob.post(
                    "/v1/handoff/continue",
                    headers=_auth("bob-token"),
                    json={
                        "scope_id": "scope-a",
                        "selection": "exact",
                        "revision": {"family": "handoff", "artifact_id": "handoff-a", "revision": 3},
                    },
                )
                assert allowed_to_runtime_boundary.status_code == 503
                assert allowed_to_runtime_boundary.json()["error"]["code"] == "runtime_not_ready"

                cannot_delegate = await bob.post(
                    "/v1/access/bindings/create",
                    headers=_auth("bob-token"),
                    json={
                        "subject": {"type": "user", "issuer": "https://identity.example", "id": "alice"},
                        "resource": exact,
                        "role": "handoff.viewer",
                        "idempotency_key": "bob-cannot-delegate",
                    },
                )
                assert cannot_delegate.status_code == 403

                unauthenticated = await bob.get("/v1/access/me")
                assert unauthenticated.status_code == 401

    asyncio.run(scenario())


def test_exact_memory_entry_version_grant_allows_get_but_not_scope_listing() -> None:
    async def scenario() -> None:
        async with SQLiteProfile.open(SQLiteConfig(), tables=ACCESS_TABLES) as profile:
            repository = RelationalAccessRepository(profile.database)
            service = AccessControlService(
                BuiltinAuthorizationProvider(repository, bootstrap_administrators=(ADMIN,)),
                relationships=repository,
                audit=repository,
            )
            exact = ResourceRef.artifact(
                "scope-a",
                family="memory",
                artifact_id="memory-a",
                revision=4,
                selector=MemoryEntrySelector(entry_id="entry-a", entry_version_id="entry-version-2"),
            )
            await service.create_binding(
                ADMIN,
                CreateBinding(
                    subject=BOB,
                    resource=exact,
                    role=AccessRole.ARTIFACT_VIEWER,
                    idempotency_key="bob-exact-memory",
                ),
                context=AUDIT,
            )
            memory_ref = ArtifactRef(family="memory", artifact_id="memory-a", revision=4)
            record = MemoryEntryRecord(
                memory_ref=memory_ref,
                state="active",
                entry=MemoryEntryVersion(
                    memory_artifact_id="memory-a",
                    entry_id="entry-a",
                    entry_version_id="entry-version-2",
                    version=2,
                    previous_version_id="entry-version-1",
                    kind="decision",
                    text="Only this exact Memory Entry Version is shared.",
                    entry_content_hash="a" * 64,
                    created_in_revision=4,
                ),
            )
            app = _app(
                service,
                principal=BOB,
                token="bob-token",  # noqa: S106 - test credential.
                application=SimpleNamespace(memory=_MemoryApplication(record)),
            )
            request = {
                "scope_id": "scope-a",
                "citation": {
                    "memory_ref": {"family": "memory", "artifact_id": "memory-a", "revision": 4},
                    "entry_id": "entry-a",
                    "entry_version_id": "entry-version-2",
                },
            }
            async with _client(app) as client:
                allowed = await client.post("/v1/memory/entries/get", headers=_auth("bob-token"), json=request)
                assert allowed.status_code == 200, allowed.json()
                assert allowed.json()["text"] == "Only this exact Memory Entry Version is shared."

                sibling = request | {"citation": request["citation"] | {"entry_version_id": "entry-version-3"}}
                denied = await client.post("/v1/memory/entries/get", headers=_auth("bob-token"), json=sibling)
                assert denied.status_code == 403

                aggregate = await client.post(
                    "/v1/memory/entries/list",
                    headers=_auth("bob-token"),
                    json={"scope_id": "scope-a"},
                )
                assert aggregate.status_code == 403

    asyncio.run(scenario())


def test_skill_publication_requires_read_and_publish_before_target_lookup(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with SQLiteProfile.open(SQLiteConfig(), tables=ACCESS_TABLES) as profile:
            repository = RelationalAccessRepository(profile.database)
            service = AccessControlService(
                BuiltinAuthorizationProvider(repository, bootstrap_administrators=(ADMIN,)),
                relationships=repository,
                audit=repository,
            )
            skill = ResourceRef.artifact("scope-a", family="skill", artifact_id="skill-a", revision=7)
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
            await service.create_binding(
                ADMIN,
                CreateBinding(
                    subject=ALICE,
                    resource=skill,
                    role=AccessRole.ARTIFACT_VIEWER,
                    idempotency_key="alice-skill-viewer",
                ),
                context=AUDIT,
            )
            managed_skill = Skill(
                artifact_id="skill-a",
                revision=7,
                content=SkillContent(
                    name="safe-publication",
                    description="Publish one exact managed Skill safely.",
                    instructions="Use the exact reviewed instructions.",
                    validation=("The exact revision is preserved.",),
                ),
            )
            runtime_skill = _SkillApplication(managed_skill)
            target_path = tmp_path / "private-host-path" / "skills"
            target = AgentSkillTarget(
                target_id="codex-project",
                agent_kind="codex",
                installation_scope="project",
                path=target_path,
                allow_managed_publish=True,
            )
            application = SimpleNamespace(skill=runtime_skill, external_skills=_ExternalSkillsApplication())
            bob_app = create_app(
                application=application,
                access_control=service,
                middleware=(Middleware(StaticBearerMiddleware, token="bob-token", principal=BOB),),  # noqa: S106
                agent_skill_targets=(target,),
            )
            payload = {
                "scope_id": "scope-a",
                "artifact": {"family": "skill", "artifact_id": "skill-a", "revision": 7},
            }
            async with _client(bob_app) as bob:
                targets = await bob.post(
                    "/v1/skills/publication-targets/list",
                    headers=_auth("bob-token"),
                    json=payload,
                )
                assert targets.status_code == 200, targets.json()
                assert targets.json()["targets"] == [
                    {
                        "target_id": "codex-project",
                        "agent_kind": "codex",
                        "installation_scope": "project",
                        "capabilities": ["publish"],
                    }
                ]
                assert str(target_path) not in targets.text

                missing = await bob.post(
                    "/v1/skills/publish",
                    headers=_auth("bob-token"),
                    json=payload | {"target_id": "unknown-target"},
                )
                assert missing.status_code == 404
                assert missing.json()["error"]["code"] == "skill_publication_target_not_found"
                assert str(target_path) not in missing.text

                published = await bob.post(
                    "/v1/skills/publish",
                    headers=_auth("bob-token"),
                    json=payload | {"target_id": "codex-project"},
                )
                assert published.status_code == 200, published.json()
                assert published.json() == {
                    "artifact": {"family": "skill", "artifact_id": "skill-a", "revision": 7},
                    "target_id": "codex-project",
                    "agent_kind": "codex",
                    "installation_scope": "project",
                    "state": "published",
                    "applied_revision": 7,
                }
                assert str(target_path) not in published.text
                assert target_path.joinpath("safe-publication", "SKILL.md").is_file()

            alice_app = create_app(
                application=application,
                access_control=service,
                middleware=(Middleware(StaticBearerMiddleware, token="alice-token", principal=ALICE),),  # noqa: S106
                agent_skill_targets=(target,),
            )
            calls_before = runtime_skill.get_calls
            async with _client(alice_app) as alice:
                denied = await alice.post(
                    "/v1/skills/publication-targets/list",
                    headers=_auth("alice-token"),
                    json=payload,
                )
                assert denied.status_code == 403
            assert runtime_skill.get_calls == calls_before

    asyncio.run(scenario())


def test_dashboard_scope_discovery_uses_the_same_principal_and_filters_before_response() -> None:
    async def scenario() -> None:
        async with SQLiteProfile.open(SQLiteConfig(), tables=ACCESS_TABLES) as profile:
            repository = RelationalAccessRepository(profile.database)
            service = AccessControlService(
                BuiltinAuthorizationProvider(repository, bootstrap_administrators=(ADMIN,)),
                relationships=repository,
                audit=repository,
            )
            await service.create_binding(
                ADMIN,
                CreateBinding(
                    subject=BOB,
                    resource=ResourceRef.scope("scope-visible"),
                    role=AccessRole.SCOPE_VIEWER,
                    idempotency_key="bob-dashboard-scope",
                ),
                context=AUDIT,
            )
            app = _app(service, principal=BOB, token="bob-token")  # noqa: S106 - test credential.
            mount_web_ui(
                app,
                scopes={"scope-visible": "Visible", "scope-hidden": "Hidden"},
                dashboard_enabled=True,
                authentication_required=True,
            )
            async with _client(app) as client:
                response = await client.get("/dashboard/scopes", headers=_auth("bob-token"))
                assert response.status_code == 200
                assert response.json() == [{"scope_id": "scope-visible", "display_name": "Visible"}]
                assert "scope-hidden" not in response.text

    asyncio.run(scenario())


def _app(service: AccessControlService, *, principal: PrincipalRef, token: str, application=None):
    return create_app(
        application=application,
        access_control=service,
        middleware=(Middleware(StaticBearerMiddleware, token=token, principal=principal),),
    )


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
