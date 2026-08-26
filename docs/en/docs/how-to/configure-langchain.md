---
title: Configure LangChain middleware
description: Add bounded PowerContext recall and completed-turn Source capture to a LangChain agent.
---

# Configure LangChain middleware

`PowerContextMiddleware` connects a LangChain `create_agent` agent to a separately running PowerContext Server. Before
each model call it requests one bounded `PreparedContext` for the latest user message. After a successful agent run it
captures the latest user message and final assistant response as one Content Source.

The middleware uses LangChain's public `AgentMiddleware` API. Recalled content modifies only the current
`ModelRequest`; it never enters agent state or a checkpointer.

## Install

The middleware ships in the standalone `powercontext-langchain` distribution and requires LangChain 1.3 or later:

```bash
uv pip install "powercontext-langchain @ git+https://github.com/oceanbase/powercontext.git#subdirectory=integrations/langchain"
powercontext server run
```

From a repository checkout, install it with `uv pip install ./integrations/langchain`.

The package owns its Scope, Settings, Client wiring, and Middleware implementation. It does not import or depend on
the separate `powercontext-langgraph` adapter. LangChain itself uses LangGraph internally, so LangGraph can still
appear as LangChain's transitive dependency.

## Add the middleware

```python
from langchain.agents import create_agent
from powercontext_langchain import PowerContextMiddleware, PowerContextScope

agent = create_agent(
    model,
    tools=application_tools,
    middleware=[PowerContextMiddleware()],
    context_schema=PowerContextScope,
)

result = await agent.ainvoke(
    {"messages": [{"role": "user", "content": "How should we deploy this service?"}]},
    context=PowerContextScope(scope_id="git:github.com/acme/api"),
)
```

The middleware supports synchronous `invoke` and `stream`; an async application must use the async agent methods
instead of calling a synchronous method inside its event loop.

## Recall lifecycle

For every model step, the middleware:

1. reads the latest human message without changing state;
2. calls `/v1/context/prepare` with the resolved scope and configured byte limit;
3. appends a separate text block to the current system message;
4. labels the entire block as untrusted historical evidence.

Tool loops can therefore receive fresh context on later model steps, including Memory explicitly written by a tool
during the same run. The override is local to each model request and cannot accumulate in checkpointed message history.

## Completed-turn capture

`PowerContextMiddleware()` enables `auto_capture` by default. Once an agent completes successfully, it captures the
latest user message and final non-empty assistant response through `/v1/sources/content`. It does not store the recalled
system block, tool outputs, or intermediate tool-calling model messages.

Capture creates Source evidence, not an inferred Memory entry. The configured scheduler or an explicit
`flush_memory` operation performs the normal Source-to-Memory extraction later. This keeps lineage intact and avoids
treating raw model output as an already reviewed durable fact.

Disable capture when the application has its own transcript policy:

```python
middleware = PowerContextMiddleware(auto_capture=False)
```

LangChain does not run `after_agent` when a model or tool aborts the run, so a failed run without a final response is
not captured.

## Configure connection and scope

The middleware owns `PowerContextScope` and uses its own `POWERCONTEXT_LANGCHAIN_*` settings; it does not reuse the
LangGraph adapter's scope or environment prefix:

| Variable | Default | Purpose |
| --- | --- | --- |
| `POWERCONTEXT_LANGCHAIN_BASE_URL` | `http://127.0.0.1:8000` | PowerContext Server URL |
| `POWERCONTEXT_LANGCHAIN_TOKEN` | unset | Bare bearer token passed to the Client |
| `POWERCONTEXT_LANGCHAIN_SCOPE_ID` | derived | Durable scope shared across runs |
| `POWERCONTEXT_LANGCHAIN_TIMEOUT` | `10` | Client timeout in seconds |
| `POWERCONTEXT_LANGCHAIN_MAX_BYTES` | `8000` | Prepared-context size limit |

An explicit `PowerContextScope` value wins over environment configuration. If no explicit scope exists, PowerContext
derives one from the current Git remote; if neither is available, recall and capture fail open without interrupting the
agent. The token remains in Client configuration and never enters agent state or message content.

## Failure behavior

Recall and capture are best-effort. Server unavailability, an invalid response, or request validation failure does not
replace the model response or stop the agent. HTTP 401 and 403 are logged once at error level without content or token
values; transient and unexpected failures are available at debug level.
