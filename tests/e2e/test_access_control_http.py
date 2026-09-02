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
from pydantic import SecretStr

from powercontext.builtin.artifacts.handoff import HandoffDraft, HandoffGenerationRequest, HandoffStatement
from powercontext.builtin.artifacts.memory import MemoryCandidateRequest, MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime.config import RuntimeConfig
from powercontext.builtin.sources import ContentSource
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
    ListMemoryEntriesRequest,
    RevokeAccessBindingRequest,
)
from powercontext.server.authentication import StaticBearerAuthenticationProvider
from powercontext.server.authz import AccessControlService, PrincipalRef
from powercontext.server.authz.composition import open_builtin_access_control
from powercontext.server.factory import create_server_app
from powercontext.server.settings import (
    AccessControlConfig,
    AuthenticationConfig,
    DashboardConfig,
    McpConfig,
    MetricsConfig,
    ServerSettings,
)

ADMIN = PrincipalRef(type="service", id="admin")
RECEIVER = PrincipalRef(type="user", id="bob")
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


class _ContentMemoryPipeline:
    async def extract(self, request: MemoryCandidateRequest, /) -> tuple[MemoryEntryInput, ...]:
        return tuple(
            MemoryEntryInput(kind="fact", text=source.content, sources=(source,))
            for source in request.sources
            if isinstance(source, ContentSource)
        )


def test_logical_handoff_grant_and_revoke_cross_the_public_server_boundary(tmp_path: Path) -> None:
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
                        content="The receiver may read every Revision of one explicitly shared logical Handoff.",
                    )
                )
                activation = await admin.activate_handoff(
                    ActivateHandoffRequest(
                        scope_id="access-e2e",
                        boundary_source=captured.source,
                        objective="Transfer one committed logical Handoff.",
                    )
                )
                assert activation.draft is not None
                prepared = await admin.finalize_handoff(
                    FinalizeHandoffRequest(scope_id="access-e2e", draft=activation.draft)
                )
                first_committed = await admin.commit_handoff(
                    CommitHandoffRequest(scope_id="access-e2e", handoff=prepared)
                )
                resource = {
                    "type": "artifact",
                    "scope_id": "access-e2e",
                    "identity": {
                        "family": first_committed.reference.family,
                        "artifact_id": first_committed.reference.artifact_id,
                    },
                    "selector": None,
                }
                binding = await admin.create_access_binding(
                    CreateAccessBindingRequest.model_validate({
                        "subject": {
                            "type": RECEIVER.type,
                            "id": RECEIVER.id,
                        },
                        "resource": resource,
                        "role": "handoff.receiver",
                        "idempotency_key": "share-logical-handoff-with-bob",
                    })
                )
                revised_draft = activation.draft.model_copy(
                    update={"objective": "Transfer the next Revision through the existing logical share."}
                )
                revised_prepared = await admin.finalize_handoff(
                    FinalizeHandoffRequest(scope_id="access-e2e", draft=revised_draft)
                )
                committed = await admin.commit_handoff(
                    CommitHandoffRequest(scope_id="access-e2e", handoff=revised_prepared)
                )
                assert committed.reference.revision == first_committed.reference.revision + 1

            async with _client(
                _app(database, access_control, RECEIVER, "receiver-token", tmp_path / "receiver-scheduler.db"),
                "receiver-token",
            ) as receiver:
                exact = await receiver.continue_handoff(
                    ContinueHandoffRequest(
                        scope_id="access-e2e",
                        selection=HandoffSelection.EXACT,
                        revision=first_committed.reference,
                    )
                )
                assert exact.selected_revision == first_committed.reference
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
                        "revision": first_committed.reference,
                    })
                )
                assert receipt.resolution.selected_revision == first_committed.reference

                latest = await receiver.continue_handoff(
                    ContinueHandoffRequest(scope_id="access-e2e", selection=HandoffSelection.LATEST)
                )
                assert latest.selected_revision == committed.reference
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
                    RevokeAccessBindingRequest(
                        binding_id=binding.binding_id,
                        expected_version=binding.version,
                        idempotency_key="revoke-receiver-binding",
                    )
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


def test_scheduled_memory_processing_uses_the_static_service_principal_as_owner(tmp_path: Path) -> None:
    async def scenario() -> None:
        token = "scheduled-static-token"  # noqa: S105 - test credential.
        app = create_server_app(
            settings=ServerSettings(
                database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'scheduled-runtime.db'}"),
                runtime=RuntimeConfig(schedule_seconds=0.02),
                access=AccessControlConfig(
                    mode="enforced",
                    deployment_id="scheduled-access-e2e",
                ),
                auth=AuthenticationConfig(provider="static-bearer", token=SecretStr(token)),
                authorization_provider="builtin",
                dashboard=DashboardConfig(enabled=False),
                metrics=MetricsConfig(enabled=False),
                mcp=McpConfig(enabled=False),
            ),
            scheduler_path=tmp_path / "scheduled-access.db",
            candidate_pipeline=_ContentMemoryPipeline(),
        )
        async with _client(app, token) as client:
            await client.capture_content_source(
                CaptureContentSourceRequest(
                    scope_id="scheduled-access",
                    source_id="scheduled-source",
                    content="The scheduled service owns this extracted Memory entry.",
                )
            )
            for _ in range(100):
                entries = await client.list_memory_entries(ListMemoryEntriesRequest(scope_id="scheduled-access"))
                if entries.entries:
                    break
                await asyncio.sleep(0.02)
            assert len(entries.entries) == 1

            visible = await client.list_access_resources(
                ListAccessResourcesRequest(
                    action=AccessAction.ARTIFACT_READ,
                    resource_type=AccessResourceType.ARTIFACT,
                    family="memory",
                )
            )
            assert visible.total == 1
            resource = visible.items[0].model_dump(mode="json")
            assert resource["identity"]["family"] == "memory"
            assert resource["selector"]["entry_id"] == entries.entries[0].citation.entry_id

    asyncio.run(scenario())


def _app(
    database: SQLiteConfig,
    access_control: AccessControlService,
    principal: PrincipalRef,
    token: str,
    scheduler_path: Path,
):
    authentication = StaticBearerAuthenticationProvider(token, principal)
    return create_server_app(
        settings=ServerSettings(
            database=database,
            access=AccessControlConfig(
                mode="enforced",
                static_preset=False,
                deployment_id=DEPLOYMENT_ID,
            ),
            auth=AuthenticationConfig(provider="oidc"),
            authorization_provider="external",
            dashboard=DashboardConfig(enabled=False),
            metrics=MetricsConfig(enabled=False),
            mcp=McpConfig(enabled=False),
        ),
        scheduler_path=scheduler_path,
        handoff_pipeline=_DeterministicHandoffPipeline(),
        access_control=access_control,
        authentication_provider=authentication,
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
