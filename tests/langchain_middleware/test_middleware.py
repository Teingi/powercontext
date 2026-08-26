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

"""Observable behavior tests for the PowerContext LangChain middleware."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
from fastapi import FastAPI
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from powercontext_langchain import PowerContextMiddleware, PowerContextScope
from powercontext_langchain.client import shared_http_client
from pydantic import Field

from powercontext.builtin.artifacts.memory import MemoryCandidateRequest, MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import InferenceConfig
from powercontext.builtin.sources import ContentSource
from powercontext.client import PowerContextClient
from powercontext.http import FlushMemoryRequest, ListMemoryEntriesRequest, RememberMemoryRequest
from powercontext.server.factory import create_server_app
from powercontext.server.settings import McpConfig, ServerSettings

SCOPE = "project:langchain-middleware-test"
MEMORY_TEXT = "Run database migrations before deploying the application."
FINAL_ANSWER = "Apply the migrations first, then deploy the application."
UNTRUSTED_LABEL = "untrusted historical evidence"


class _ContentCandidatePipeline:
    async def extract(self, request: MemoryCandidateRequest, /) -> tuple[MemoryEntryInput, ...]:
        return tuple(
            MemoryEntryInput(kind="agent-turn", text=source.content, sources=(source,))
            for source in request.sources
            if isinstance(source, ContentSource)
        )


class _RecordingModel(BaseChatModel):
    inputs: list[list[BaseMessage]] = Field(default_factory=list)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:  # type: ignore[no-untyped-def]
        self.inputs.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=FINAL_ANSWER))])

    @property
    def _llm_type(self) -> str:
        return "recording"


def _server_app(tmp_path: Path) -> FastAPI:
    return create_server_app(
        settings=ServerSettings(
            database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"),
            inference=InferenceConfig(generation_model="test"),
            mcp=McpConfig(enabled=False),
        ),
        candidate_pipeline=_ContentCandidatePipeline(),
    )


def _run(app: FastAPI, scenario: Callable[[PowerContextClient], Awaitable[None]]) -> None:
    async def driver() -> None:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as transport,
        ):
            client = PowerContextClient("http://testserver", http_client=transport)
            with shared_http_client(transport):
                await scenario(client)

    asyncio.run(driver())


def _system_texts(messages: list[BaseMessage]) -> list[str]:
    return [message.text for message in messages if message.type == "system"]


def test_middleware_injects_recall_without_persisting_it(tmp_path: Path) -> None:
    model = _RecordingModel()
    agent = create_agent(
        model,
        tools=[],
        middleware=[PowerContextMiddleware(auto_capture=False)],
        context_schema=PowerContextScope,
    )
    app = _server_app(tmp_path)

    async def scenario(client: PowerContextClient) -> None:
        await client.remember_memory(RememberMemoryRequest(scope_id=SCOPE, kind="decision", text=MEMORY_TEXT))

        result = await agent.ainvoke(
            {"messages": [HumanMessage(content="How should we deploy the application and its migrations?")]},
            context=PowerContextScope(scope_id=SCOPE),
        )

        system_texts = _system_texts(model.inputs[-1])
        assert len(system_texts) == 1
        assert UNTRUSTED_LABEL in system_texts[0]
        assert MEMORY_TEXT in system_texts[0]
        assert _system_texts(result["messages"]) == []

    _run(app, scenario)


def test_middleware_captures_completed_turn_as_source(tmp_path: Path) -> None:
    model = _RecordingModel()
    agent = create_agent(
        model,
        tools=[],
        middleware=[PowerContextMiddleware()],
        context_schema=PowerContextScope,
    )
    app = _server_app(tmp_path)
    user_text = "What is the safe deployment order?"

    async def scenario(client: PowerContextClient) -> None:
        await agent.ainvoke(
            {"messages": [HumanMessage(content=user_text)]},
            context=PowerContextScope(scope_id=SCOPE),
        )

        flushed = await client.flush_memory(FlushMemoryRequest(scope_id=SCOPE))
        entries = await client.list_memory_entries(ListMemoryEntriesRequest(scope_id=SCOPE))

        assert flushed.memory is not None
        assert len(entries.entries) == 1
        captured = entries.entries[0]
        assert captured.text == f"User:\n{user_text}\n\nAssistant:\n{FINAL_ANSWER}"
        assert len(captured.source_refs) == 1
        assert captured.source_refs[0].source_id.startswith("langchain-agent-turn-")
        assert UNTRUSTED_LABEL not in captured.text

    _run(app, scenario)


def test_async_agent_reaches_end_when_server_unreachable() -> None:
    model = _RecordingModel()
    agent = create_agent(
        model,
        tools=[],
        middleware=[PowerContextMiddleware(auto_capture=False)],
        context_schema=PowerContextScope,
    )

    async def driver() -> None:
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content="Continue without memory.")]},
            context=PowerContextScope(scope_id=SCOPE, base_url="http://127.0.0.1:9", timeout=0.2),
        )
        assert result["messages"][-1].text == FINAL_ANSWER
        assert _system_texts(model.inputs[-1]) == []

    asyncio.run(driver())


def test_sync_agent_reaches_end_when_server_unreachable() -> None:
    model = _RecordingModel()
    agent = create_agent(
        model,
        tools=[],
        middleware=[PowerContextMiddleware(auto_capture=False)],
        context_schema=PowerContextScope,
    )

    result = agent.invoke(
        {"messages": [HumanMessage(content="Continue without memory.")]},
        context=PowerContextScope(scope_id=SCOPE, base_url="http://127.0.0.1:9", timeout=0.2),
    )

    assert result["messages"][-1].text == FINAL_ANSWER
    assert _system_texts(model.inputs[-1]) == []
