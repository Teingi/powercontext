# PowerContext for LangChain

`powercontext-langchain` connects a LangChain `create_agent` application to a separately running PowerContext Server.
It provides `PowerContextMiddleware`, which recalls bounded context before each model call and captures the completed
user/assistant turn as Source evidence after a successful agent run.

## Install

```bash
uv pip install "powercontext-langchain @ git+https://github.com/oceanbase/powercontext.git#subdirectory=integrations/langchain"
powercontext server run
```

From a checkout, use `uv pip install ./integrations/langchain`.

This package owns its Scope, Settings, Client wiring, and Middleware implementation. It neither imports nor depends on
the separate `powercontext-langgraph` adapter. LangChain itself uses LangGraph internally, so installing LangChain may
still install LangGraph as a transitive dependency.

## Use

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

The middleware changes only the current model request, so recalled context never enters agent state or a checkpointer.
Automatic capture can be disabled with `PowerContextMiddleware(auto_capture=False)`.

Configuration uses `POWERCONTEXT_LANGCHAIN_BASE_URL`, `POWERCONTEXT_LANGCHAIN_TOKEN`,
`POWERCONTEXT_LANGCHAIN_SCOPE_ID`, `POWERCONTEXT_LANGCHAIN_TIMEOUT`, and `POWERCONTEXT_LANGCHAIN_MAX_BYTES`.
