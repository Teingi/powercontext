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
import json
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr

from powercontext.builtin.persistence.sqlite import SQLiteConfig, SQLiteProfile
from powercontext.server.authz import (
    AccessAction,
    AccessAuditContext,
    AccessControlService,
    AccessProviderCapabilities,
    AccessRequest,
    AccessResourceType,
    AccessRole,
    AccessUnavailableError,
    AuthZenAuthorizationProvider,
    BuiltinAuthorizationProvider,
    CasbinAuthorizationProvider,
    CreateBinding,
    MemoryEntrySelector,
    PrincipalRef,
    ResourceRef,
    ResourceSearchRequest,
)
from powercontext.server.authz.composition import open_casbin_access_control
from powercontext.server.authz.repository import ACCESS_TABLES, RelationalAccessRepository

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)
ADMIN = PrincipalRef(type="user", issuer="https://identity.example", id="admin")
BOB = PrincipalRef(type="user", issuer="https://identity.example", id="bob")
ALICE = PrincipalRef(type="user", issuer="https://identity.example", id="alice")
CAROL = PrincipalRef(type="user", issuer="https://identity.example", id="carol")
AUDIT = AccessAuditContext(transport="http", operation="adapter-conformance", request_id="req-adapter")


def test_builtin_and_casbin_adapters_share_the_same_access_semantics() -> None:
    async def scenario() -> None:
        async with SQLiteProfile.open(SQLiteConfig(), tables=ACCESS_TABLES) as profile:
            repository = RelationalAccessRepository(profile.database)
            builtin_provider = BuiltinAuthorizationProvider(
                repository,
                bootstrap_administrators=(ADMIN,),
                clock=lambda: NOW,
            )
            casbin_provider = CasbinAuthorizationProvider(
                repository,
                bootstrap_administrators=(ADMIN,),
                clock=lambda: NOW,
            )
            casbin_service = AccessControlService(
                casbin_provider,
                relationships=casbin_provider,
                audit=repository,
                clock=lambda: NOW,
            )
            exact = ResourceRef.artifact("scope-a", family="handoff", artifact_id="handoff-a", revision=3)
            sibling = ResourceRef.artifact("scope-a", family="handoff", artifact_id="handoff-a", revision=4)
            binding = await casbin_service.create_binding(
                ADMIN,
                CreateBinding(
                    subject=BOB,
                    resource=exact,
                    role=AccessRole.HANDOFF_RECEIVER,
                    idempotency_key="casbin-handoff-receiver",
                ),
                context=AUDIT,
            )
            await casbin_service.create_binding(
                ADMIN,
                CreateBinding(
                    subject=ALICE,
                    resource=ResourceRef.server(),
                    role=AccessRole.SERVER_OBSERVER,
                    idempotency_key="casbin-server-observer",
                ),
                context=AUDIT,
            )
            await casbin_service.create_binding(
                ADMIN,
                CreateBinding(
                    subject=CAROL,
                    resource=ResourceRef.server(),
                    role=AccessRole.SERVER_ADMIN,
                    idempotency_key="casbin-server-admin",
                ),
                context=AUDIT,
            )

            vectors = _handoff_conformance_vectors(exact, sibling)
            for action, resource, expected in vectors:
                request = AccessRequest(subject=BOB, action=action, resource=resource, context=AUDIT)
                builtin = await builtin_provider.check(request)
                casbin = await casbin_provider.check(request)
                assert builtin.allowed is casbin.allowed is expected
                assert builtin.policy_revision == casbin.policy_revision

            administrative_vectors = (
                (ALICE, AccessAction.SERVER_OBSERVE, ResourceRef.server(), True),
                (ALICE, AccessAction.SERVER_ADMIN, ResourceRef.server(), False),
                (ALICE, AccessAction.SCOPE_READ, ResourceRef.scope("scope-a"), False),
                (CAROL, AccessAction.SERVER_OBSERVE, ResourceRef.server(), True),
                (CAROL, AccessAction.SERVER_ADMIN, ResourceRef.server(), True),
                (CAROL, AccessAction.SCOPE_ADMIN, ResourceRef.scope("scope-a"), True),
                (
                    CAROL,
                    AccessAction.SKILL_PUBLISH,
                    ResourceRef.artifact(
                        "scope-a",
                        family="skill",
                        artifact_id="skill-a",
                        revision=1,
                    ),
                    True,
                ),
            )
            for subject, action, resource, expected in administrative_vectors:
                request = AccessRequest(subject=subject, action=action, resource=resource, context=AUDIT)
                builtin = await builtin_provider.check(request)
                casbin = await casbin_provider.check(request)
                assert builtin.allowed is casbin.allowed is expected

            builtin_filter = await builtin_provider.resolve_resource_filter(
                _search_request(BOB, AccessAction.ARTIFACT_READ, family="handoff")
            )
            casbin_filter = await casbin_provider.resolve_resource_filter(
                _search_request(BOB, AccessAction.ARTIFACT_READ, family="handoff")
            )
            assert builtin_filter == casbin_filter

            revoked = await casbin_service.revoke_binding(
                ADMIN,
                binding.binding_id,
                expected_version=binding.version,
                context=AUDIT,
            )
            assert revoked.version == 2
            denied = AccessRequest(subject=BOB, action=AccessAction.ARTIFACT_READ, resource=exact, context=AUDIT)
            assert (await builtin_provider.check(denied)).allowed is False
            assert (await casbin_provider.check(denied)).allowed is False

    asyncio.run(scenario())


def test_casbin_composition_opens_a_writable_access_service() -> None:
    async def scenario() -> None:
        async with open_casbin_access_control(
            SQLiteConfig(),
            bootstrap_administrators=(ADMIN,),
        ) as service:
            exact = ResourceRef.artifact("scope-a", family="experience", artifact_id="experience-a", revision=1)
            await service.create_binding(
                ADMIN,
                CreateBinding(
                    subject=BOB,
                    resource=exact,
                    role=AccessRole.ARTIFACT_VIEWER,
                    idempotency_key="casbin-composition-viewer",
                ),
                context=AUDIT,
            )
            assert (await service.require(BOB, AccessAction.ARTIFACT_READ, exact, context=AUDIT)).allowed

    asyncio.run(scenario())


def test_authzen_adapter_matches_the_exact_resource_conformance_vector() -> None:
    exact = ResourceRef.artifact("scope-a", family="handoff", artifact_id="handoff-a", revision=3)
    sibling = ResourceRef.artifact("scope-a", family="handoff", artifact_id="handoff-a", revision=4)
    vectors = _handoff_conformance_vectors(exact, sibling)
    expected = {(action.value, resource.key): allowed for action, resource, allowed in vectors}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        decisions = [
            {
                "decision": expected[
                    (
                        evaluation["action"]["name"],
                        evaluation["resource"]["id"],
                    )
                ]
            }
            for evaluation in payload["evaluations"]
        ]
        return httpx.Response(200, json={"evaluations": decisions})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = AuthZenAuthorizationProvider("http://127.0.0.1:9876", http_client=client)
            requests = tuple(
                AccessRequest(subject=BOB, action=action, resource=resource, context=AUDIT)
                for action, resource, _expected in vectors
            )
            decisions = await provider.check_batch(requests)
            assert [decision.allowed for decision in decisions] == [value for _action, _resource, value in vectors]

    asyncio.run(scenario())


def test_authzen_adapter_uses_standard_point_and_boxcar_shapes_and_fails_closed() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer provider-token"
        payload = json.loads(request.content)
        seen.append(payload)
        if request.url.path.endswith("/evaluation"):
            return httpx.Response(200, json={"decision": True, "context": {"policy_revision": "pdp-42"}})
        evaluations = payload["evaluations"]
        return httpx.Response(
            200,
            json={
                "evaluations": [
                    {"decision": evaluation["action"]["name"] == "artifact.read"} for evaluation in evaluations
                ]
            },
        )

    async def scenario() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            provider = AuthZenAuthorizationProvider(
                "http://127.0.0.1:9876",
                token=SecretStr("provider-token"),
                http_client=client,
            )
            resource = ResourceRef.artifact(
                "scope-a",
                family="memory",
                artifact_id="memory-a",
                revision=4,
                selector=MemoryEntrySelector(entry_id="entry-a", entry_version_id="entry-version-2"),
            )
            read = AccessRequest(subject=BOB, action=AccessAction.ARTIFACT_READ, resource=resource, context=AUDIT)
            publish = AccessRequest(subject=BOB, action=AccessAction.SKILL_PUBLISH, resource=resource, context=AUDIT)
            point = await provider.check(read)
            batch = await provider.check_batch((read, publish))

            assert point.allowed is True
            assert point.policy_revision == "pdp-42"
            assert [decision.allowed for decision in batch] == [True, False]
            assert seen[0] == {
                "subject": {
                    "type": "user",
                    "id": "bob",
                    "properties": {"issuer": "https://identity.example"},
                },
                "action": {"name": "artifact.read"},
                "resource": {
                    "type": "artifact",
                    "id": resource.key,
                    "properties": {
                        "scope_id": "scope-a",
                        "reference": {"family": "memory", "artifact_id": "memory-a", "revision": 4},
                        "selector": {
                            "type": "memory_entry",
                            "entry_id": "entry-a",
                            "entry_version_id": "entry-version-2",
                        },
                    },
                },
                "context": {
                    "request_id": "req-adapter",
                    "transport": "http",
                    "operation": "adapter-conformance",
                },
            }
            assert seen[1]["options"] == {"evaluations_semantic": "execute_all"}
            with pytest.raises(AccessUnavailableError, match="filtering"):
                await provider.resolve_resource_filter(
                    _search_request(BOB, AccessAction.ARTIFACT_READ, family="memory")
                )

        malformed = httpx.MockTransport(lambda _request: httpx.Response(200, json={"decision": "allow"}))
        async with httpx.AsyncClient(transport=malformed) as client:
            provider = AuthZenAuthorizationProvider("http://127.0.0.1:9876", http_client=client)
            with pytest.raises(AccessUnavailableError):
                await provider.check(read)

    asyncio.run(scenario())


def test_authzen_adapter_enforces_the_policy_revision_contract_boundary() -> None:
    request = AccessRequest(
        subject=BOB,
        action=AccessAction.SERVER_OBSERVE,
        resource=ResourceRef.server(),
        context=AUDIT,
    )

    async def evaluate(revision: str):
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={"decision": True, "context": {"policy_revision": revision}},
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            provider = AuthZenAuthorizationProvider("http://127.0.0.1:9876", http_client=client)
            return await provider.check(request)

    accepted = asyncio.run(evaluate("r" * 64))
    assert accepted.policy_revision == "r" * 64
    with pytest.raises(AccessUnavailableError):
        asyncio.run(evaluate("r" * 65))


def test_authzen_adapter_rejects_credential_urls_and_relationship_claims() -> None:
    with pytest.raises(ValueError, match="credential-free"):
        AuthZenAuthorizationProvider("https://user:secret@pdp.example")
    with pytest.raises(ValueError, match="credential-free"):
        AuthZenAuthorizationProvider("http://pdp.example")

    async def scenario() -> None:
        repository_profile = SQLiteProfile.open(SQLiteConfig(), tables=ACCESS_TABLES)
        async with repository_profile as profile:
            repository = RelationalAccessRepository(profile.database)
            transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"decision": True}))
            async with httpx.AsyncClient(transport=transport) as client:
                provider = AuthZenAuthorizationProvider("http://127.0.0.1:9876", http_client=client)
                service = AccessControlService(
                    provider,
                    relationships=None,
                    audit=repository,
                    provider_capabilities=AccessProviderCapabilities(
                        safe_resource_filtering=False,
                        multi_requirement_check=True,
                        relationship_management=False,
                    ),
                )
                with pytest.raises(AccessUnavailableError, match="relationship"):
                    await service.create_binding(
                        ADMIN,
                        CreateBinding(
                            subject=BOB,
                            resource=ResourceRef.scope("scope-a"),
                            role=AccessRole.SCOPE_VIEWER,
                            idempotency_key="unsupported-relationship",
                        ),
                        context=AUDIT,
                    )

    asyncio.run(scenario())


def _search_request(subject: PrincipalRef, action: AccessAction, *, family: str) -> ResourceSearchRequest:
    return ResourceSearchRequest(
        subject=subject,
        action=action,
        resource_type=AccessResourceType.ARTIFACT,
        family=family,
        context=AUDIT,
    )


def _handoff_conformance_vectors(
    exact: ResourceRef,
    sibling: ResourceRef,
) -> tuple[tuple[AccessAction, ResourceRef, bool], ...]:
    return (
        (AccessAction.ARTIFACT_READ, exact, True),
        (AccessAction.HANDOFF_EVIDENCE_READ, exact, True),
        (AccessAction.HANDOFF_ACKNOWLEDGE, exact, True),
        (AccessAction.ARTIFACT_READ, sibling, False),
        (AccessAction.SCOPE_READ, ResourceRef.scope("scope-a"), False),
        (AccessAction.SERVER_OBSERVE, ResourceRef.server(), False),
    )
