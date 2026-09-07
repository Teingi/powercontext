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

"""Client-to-storage acceptance for request-local context assembly."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest

from powercontext.builtin.artifacts.memory import MemoryService
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.client import PowerContextClient
from powercontext.http import (
    ApproveArtifactCandidateRequest,
    CaptureContentSourceRequest,
    CreateScopeRequest,
    ExperienceProposal,
    GetMemoryEntryRequest,
    PrepareContextRequest,
    ProposeExperienceRequest,
    RememberMemoryRequest,
    ReviseMemoryEntryRequest,
)
from powercontext.server.factory import create_server_app
from powercontext.server.settings import McpConfig, MetricsConfig, ServerSettings


@asynccontextmanager
async def _server(tmp_path):
    app = create_server_app(
        settings=ServerSettings(
            database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'assembly.db'}"),
            mcp=McpConfig(enabled=False),
            metrics=MetricsConfig(enabled=False),
        ),
        scheduler_path=tmp_path / "scheduler.db",
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as transport,
    ):
        yield (
            app.state.application,
            transport,
            PowerContextClient(
                "http://testserver",
                http_client=transport,
                trust_transport_security=True,
            ),
        )


def test_client_assembles_approved_evidence_and_preserves_exact_memory_versions(tmp_path, monkeypatch):
    async def scenario():
        async with _server(tmp_path) as (_, transport, client):
            scope = await client.create_scope(
                CreateScopeRequest(
                    title="Assembly",
                    summary="Context delivery",
                    idempotency_key="assembly",
                )
            )
            scope_id = scope.scope_id
            remembered = await client.remember_memory(
                RememberMemoryRequest(
                    scope_id=scope_id,
                    kind="constraint",
                    text="Regenerate the OpenAPI client before contract tests.",
                )
            )
            assert remembered.entry is not None
            citation = remembered.entry.citation
            source = await client.capture_content_source(
                CaptureContentSourceRequest(
                    scope_id=scope_id,
                    source_id="verified-task",
                    content="OpenAPI regeneration repaired the client.",
                )
            )
            candidate = await client.propose_experience(
                ProposeExperienceRequest(
                    scope_id=scope_id,
                    proposal=ExperienceProposal(
                        situation="The OpenAPI client was stale.",
                        action="Regenerate the OpenAPI client.",
                        outcome="The OpenAPI contract tests passed.",
                        lesson="Regenerate the client before contract tests.",
                    ),
                    source_refs=[source.source],
                    artifact_refs=[],
                )
            )
            request = PrepareContextRequest.model_validate({
                "scope_id": scope_id,
                "query": "OpenAPI client",
                "assembly": {
                    "sections": [{"family": "experience", "limit": 2}, {"family": "memory", "limit": 5}],
                },
            })
            pending = await client.prepare_context(request)
            assert pending.content is not None
            assert "## Experience" not in pending.content
            await client.approve_artifact_candidate(
                ApproveArtifactCandidateRequest(
                    scope_id=scope_id,
                    candidate_id=candidate.candidate_id,
                    expected_version=candidate.version,
                )
            )
            prepared = await client.prepare_context(request)
            assert prepared.content is not None
            assert prepared.content.index("## Experience") < prepared.content.index("## Memory")
            assert citation.entry_version_id in prepared.content
            assert prepared.content_bytes == len(prepared.content.encode("utf-8")) <= request.max_bytes

            await client.revise_memory_entry(
                ReviseMemoryEntryRequest(
                    scope_id=scope_id,
                    citation=citation,
                    kind="constraint",
                    text="OpenAPI validation now also includes generated JS.",
                )
            )
            exact = await client.get_memory_entry(GetMemoryEntryRequest(scope_id=scope_id, citation=citation))
            assert exact.text == remembered.entry.text

            legacy = await client.prepare_context(PrepareContextRequest(scope_id=scope_id, query="OpenAPI client"))
            assert legacy.content is not None
            assert '"items":[' in legacy.content
            assert "BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1" in legacy.content
            empty = await transport.post(
                "/v1/context/prepare",
                json={
                    "scope_id": scope_id,
                    "query": "OpenAPI",
                    "assembly": {"sections": []},
                },
            )
            assert empty.json() == {
                "schema": "powercontext.prepared-context.v1",
                "status": "empty",
                "content": None,
                "content_bytes": 0,
            }

            async def unavailable_memory(*args, **kwargs):
                raise RuntimeError("Excluded Memory backend is unavailable")  # noqa: TRY003

            monkeypatch.setattr(MemoryService, "search", unavailable_memory)
            experience_only = await client.prepare_context(
                PrepareContextRequest.model_validate({
                    "scope_id": scope_id,
                    "query": "OpenAPI client",
                    "assembly": {"sections": [{"family": "experience", "limit": 2}]},
                })
            )
            assert experience_only.content is not None
            assert "## Experience" in experience_only.content and "## Memory" not in experience_only.content

    asyncio.run(scenario())


def test_excluded_recall_source_failure_does_not_affect_selected_memory(tmp_path, monkeypatch):
    async def scenario():
        async with _server(tmp_path) as (runtime, transport, client):
            scope = await client.create_scope(
                CreateScopeRequest(
                    title="Assembly",
                    summary="Source exclusion",
                    idempotency_key="exclude",
                )
            )
            await client.remember_memory(
                RememberMemoryRequest(
                    scope_id=scope.scope_id,
                    kind="fact",
                    text="OpenAPI contract evidence.",
                )
            )

            async def unavailable(*args):
                raise RuntimeError("Excluded Experience backend is unavailable")  # noqa: TRY003

            monkeypatch.setattr(runtime, "_experience_recall", unavailable)
            result = await client.prepare_context(
                PrepareContextRequest.model_validate({
                    "scope_id": scope.scope_id,
                    "query": "OpenAPI",
                    "assembly": {
                        "sections": [{"family": "memory", "limit": 8}],
                    },
                })
            )
            assert result.content is not None and "OpenAPI contract evidence." in result.content
            assert "## Experience" not in result.content

            async def no_memory(*args, **kwargs):
                raise RuntimeError("Excluded Memory backend is unavailable")  # noqa: TRY003

            monkeypatch.setattr(MemoryService, "search", no_memory)
            empty = await transport.post(
                "/v1/context/prepare",
                json={
                    "scope_id": scope.scope_id,
                    "query": "OpenAPI",
                    "assembly": {"sections": []},
                },
            )
            assert empty.status_code == 200 and empty.json()["status"] == "empty"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "assembly",
    [
        None,
        {"sections": [{"family": "experience", "limit": 3}]},
        {"sections": [{"family": "memory", "limit": 1}, {"family": "memory", "limit": 1}]},
        {"sections": [{"family": "memory", "limit": 8}, {"family": "experience", "limit": 1}]},
        {"show": ["confidence", "confidence"]},
        {"show": ["score"]},
        {"format": "json"},
        {"sort_by": "confidence"},
    ],
)
def test_http_rejects_invalid_assembly_without_echoing_inputs(tmp_path, assembly):
    async def scenario():
        async with _server(tmp_path) as (_, transport, client):
            scope = await client.create_scope(
                CreateScopeRequest(
                    title="Assembly",
                    summary="Request validation",
                    idempotency_key="invalid",
                )
            )
            response = await transport.post(
                "/v1/context/prepare",
                json={
                    "scope_id": scope.scope_id,
                    "query": "private-query-text",
                    "assembly": assembly,
                },
            )
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "invalid_request"
            assert "private-query-text" not in response.text

    asyncio.run(scenario())
