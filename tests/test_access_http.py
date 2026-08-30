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

import httpx
from starlette.middleware import Middleware

from powercontext.builtin.persistence.sqlite import SQLiteConfig, SQLiteProfile
from powercontext.server.app import create_app
from powercontext.server.authz import AccessControlService, BuiltinAuthorizationProvider, PrincipalRef
from powercontext.server.authz.repository import ACCESS_TABLES, RelationalAccessRepository
from powercontext.server.middleware import StaticBearerMiddleware

ADMIN = PrincipalRef(type="user", issuer="https://identity.example", id="admin")
BOB = PrincipalRef(type="user", issuer="https://identity.example", id="bob")


def test_access_api_and_handoff_pep_enforce_exact_receiver_visibility() -> None:
    async def scenario() -> None:
        async with SQLiteProfile.open(SQLiteConfig(), tables=ACCESS_TABLES) as profile:
            repository = RelationalAccessRepository(profile.database)
            service = AccessControlService(
                BuiltinAuthorizationProvider(repository, bootstrap_administrators=(ADMIN,)),
                relationships=repository,
                audit=repository,
            )
            admin_app = _app(service, principal=ADMIN, token="admin-token")  # noqa: S106 - test credential.
            async with _client(admin_app) as admin:
                principal = await admin.get("/v1/access/me", headers=_auth("admin-token"))
                assert principal.status_code == 200
                assert principal.json() == {
                    "type": "user",
                    "issuer": "https://identity.example",
                    "id": "admin",
                }
                created = await admin.post(
                    "/v1/access/bindings/create",
                    headers=_auth("admin-token"),
                    json={
                        "subject": {"type": "user", "issuer": "https://identity.example", "id": "bob"},
                        "resource": {
                            "type": "handoff",
                            "scope_id": "scope-a",
                            "family": "handoff",
                            "artifact_id": "handoff-a",
                            "revision": 3,
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
                    "type": "handoff",
                    "scope_id": "scope-a",
                    "family": "handoff",
                    "artifact_id": "handoff-a",
                    "revision": 3,
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
                    json={"action": "handoff.read", "resource_type": "handoff"},
                )
                assert resources.status_code == 200
                assert resources.json()["items"] == [exact]

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


def _app(service: AccessControlService, *, principal: PrincipalRef, token: str):
    return create_app(
        access_control=service,
        middleware=(Middleware(StaticBearerMiddleware, token=token, principal=principal),),
    )


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
