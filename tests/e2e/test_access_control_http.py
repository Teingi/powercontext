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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from starlette.middleware import Middleware

from powercontext.builtin.artifacts.handoff import HandoffDraft, HandoffGenerationRequest, HandoffStatement
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.client import ForbiddenResponseError, PowerContextClient
from powercontext.http import (
    AccessAction,
    AccessResourceType,
    AcknowledgeHandoffRequest,
    ActivateHandoffRequest,
    CaptureContentSourceRequest,
    CommitHandoffRequest,
    ContinueHandoffRequest,
    CreateAccessBindingRequest,
    FinalizeHandoffRequest,
    HandoffSelection,
    ListAccessResourcesRequest,
    RevokeAccessBindingRequest,
)
from powercontext.server.authz import AccessControlService, PrincipalRef
from powercontext.server.authz.composition import open_builtin_access_control
from powercontext.server.factory import create_server_app
from powercontext.server.middleware import StaticBearerMiddleware
from powercontext.server.settings import (
    AccessControlConfig,
    DashboardConfig,
    McpConfig,
    MetricsConfig,
    ServerSettings,
)

ADMIN = PrincipalRef(type="user", issuer="https://identity.example", id="admin")
RECEIVER = PrincipalRef(type="user", issuer="https://identity.example", id="bob")
DEPLOYMENT_ID = "access-control-http-e2e"


class _DeterministicHandoffPipeline:
    async def generate(self, request: HandoffGenerationRequest, /) -> HandoffDraft:
        citations = tuple(item.citation for item in request.evidence)
        return HandoffDraft(
            objective=request.objective,
            state=(HandoffStatement(text="The exact Handoff is ready for its receiver.", citations=citations),),
            disposition="continuable",
            next_action=HandoffStatement(text="Acknowledge only this committed Revision.", citations=citations),
        )


def test_exact_handoff_grant_and_revoke_cross_the_public_server_boundary(tmp_path: Path) -> None:
    async def scenario() -> None:
        database = SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}")
        async with open_builtin_access_control(
            database,
            bootstrap_administrators=(ADMIN,),
            deployment_id=DEPLOYMENT_ID,
        ) as access_control:
            async with _client(
                _app(database, access_control, ADMIN, "admin-token", tmp_path / "admin-scheduler.db"),
                "admin-token",
            ) as admin:
                captured = await admin.capture_content_source(
                    CaptureContentSourceRequest(
                        scope_id="access-e2e",
                        source_id="handoff-boundary",
                        content="The receiver must see only one explicitly shared Handoff Revision.",
                    )
                )
                activation = await admin.activate_handoff(
                    ActivateHandoffRequest(
                        scope_id="access-e2e",
                        boundary_source=captured.source,
                        objective="Transfer one exact committed Handoff.",
                    )
                )
                assert activation.draft is not None
                prepared = await admin.finalize_handoff(
                    FinalizeHandoffRequest(scope_id="access-e2e", draft=activation.draft)
                )
                committed = await admin.commit_handoff(CommitHandoffRequest(scope_id="access-e2e", handoff=prepared))
                resource = {
                    "type": "artifact",
                    "scope_id": "access-e2e",
                    "reference": committed.reference.model_dump(mode="json"),
                    "selector": None,
                }
                binding = await admin.create_access_binding(
                    CreateAccessBindingRequest.model_validate({
                        "subject": {
                            "type": RECEIVER.type,
                            "issuer": RECEIVER.issuer,
                            "id": RECEIVER.id,
                        },
                        "resource": resource,
                        "role": "handoff.receiver",
                        "idempotency_key": "share-exact-handoff-with-bob",
                    })
                )

            async with _client(
                _app(database, access_control, RECEIVER, "receiver-token", tmp_path / "receiver-scheduler.db"),
                "receiver-token",
            ) as receiver:
                exact = await receiver.continue_handoff(
                    ContinueHandoffRequest(
                        scope_id="access-e2e",
                        selection=HandoffSelection.EXACT,
                        revision=committed.reference,
                    )
                )
                assert exact.selected_revision == committed.reference
                receipt = await receiver.acknowledge_handoff(
                    AcknowledgeHandoffRequest.model_validate({
                        "scope_id": "access-e2e",
                        "source_id": "receiver-acknowledgement",
                        "receiver": RECEIVER.id,
                        "status": "accepted",
                        "selection": "exact",
                        "receiver_checks": {
                            "live_state": "confirmed",
                            "capability": "confirmed",
                            "authorization": "confirmed",
                        },
                        "revision": committed.reference,
                    })
                )
                assert receipt.resolution.selected_revision == committed.reference

                with pytest.raises(ForbiddenResponseError):
                    await receiver.continue_handoff(
                        ContinueHandoffRequest(scope_id="access-e2e", selection=HandoffSelection.LATEST)
                    )
                visible = await receiver.list_access_resources(
                    ListAccessResourcesRequest(
                        action=AccessAction.ARTIFACT_READ,
                        resource_type=AccessResourceType.ARTIFACT,
                        family="handoff",
                    )
                )
                assert visible.total == 1
                assert visible.items[0].model_dump(mode="json") == resource

            async with _client(
                _app(database, access_control, ADMIN, "admin-token", tmp_path / "revoke-scheduler.db"),
                "admin-token",
            ) as admin:
                revoked = await admin.revoke_access_binding(
                    RevokeAccessBindingRequest(binding_id=binding.binding_id, expected_version=binding.version)
                )
                assert revoked.state == "revoked"

            async with _client(
                _app(database, access_control, RECEIVER, "receiver-token", tmp_path / "denied-scheduler.db"),
                "receiver-token",
            ) as receiver:
                with pytest.raises(ForbiddenResponseError):
                    await receiver.continue_handoff(
                        ContinueHandoffRequest(
                            scope_id="access-e2e",
                            selection=HandoffSelection.EXACT,
                            revision=committed.reference,
                        )
                    )
                visible = await receiver.list_access_resources(
                    ListAccessResourcesRequest(
                        action=AccessAction.ARTIFACT_READ,
                        resource_type=AccessResourceType.ARTIFACT,
                        family="handoff",
                    )
                )
                assert visible.total == 0
                assert visible.items == []

    asyncio.run(scenario())


def _app(
    database: SQLiteConfig,
    access_control: AccessControlService,
    principal: PrincipalRef,
    token: str,
    scheduler_path: Path,
):
    return create_server_app(
        settings=ServerSettings(
            database=database,
            access=AccessControlConfig(
                mode="enforced",
                bootstrap_static_principal=False,
                deployment_id=DEPLOYMENT_ID,
            ),
            dashboard=DashboardConfig(enabled=False),
            metrics=MetricsConfig(enabled=False),
            mcp=McpConfig(enabled=False),
        ),
        scheduler_path=scheduler_path,
        handoff_pipeline=_DeterministicHandoffPipeline(),
        access_control=access_control,
        middleware=(Middleware(StaticBearerMiddleware, token=token, principal=principal),),
    )


@asynccontextmanager
async def _client(app, token: str) -> AsyncIterator[PowerContextClient]:
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as transport,
        PowerContextClient(
            "http://testserver",
            token=token,
            http_client=transport,
            trust_transport_security=True,
        ) as client,
    ):
        yield client
