---
title: Prepare standard context text
description: Choose Memory, Experience, and Profile sections, order, limits, and visible metadata for prepared context.
---

# Prepare standard context text

Add `assembly` to `POST /v1/context/prepare` to receive Markdown organized by Artifact family. You can select Memory,
approved Experience, and committed Profile snapshots, arrange their sections, set entry limits, and display retrieval
rank and confidence status.
Use an existing Scope that you can read; reading referenced Scopes also requires permission.

## Select and order sections

Save this request as `prepare.json`, replacing `scope_id` with your Scope ID:

```json
{
  "scope_id": "project:demo",
  "query": "How should we fix a client mismatch after an OpenAPI change?",
  "max_bytes": 8000,
  "assembly": {
    "format": "markdown",
    "sections": [
      {"family": "experience", "limit": 2},
      {"family": "memory", "limit": 5}
    ],
    "show": ["confidence", "recall_rank"]
  }
}
```

Export the actual text from an unauthenticated local Server:

```bash
curl --fail-with-body -sS http://127.0.0.1:8000/v1/context/prepare \
  -H 'Content-Type: application/json' --data-binary @prepare.json \
  | jq -j '.content // empty' > context.md
```

Authenticated Servers require the same Authorization header as other API calls. The HTTP envelope still has four
fields: `schema`, `status`, `content`, and `content_bytes`. Write or inject `content` directly. It is already the
final text, including the historical-evidence notice, section headings, literal bodies, exact citations, and
truncation flags. An empty result has `status: "empty"`, `content: null`, and `content_bytes: 0`.

The equivalent Python request uses the shared Client:

```python
import asyncio
import json
from pathlib import Path

from powercontext.client import PowerContextClient
from powercontext.http import PrepareContextRequest

async def export_context() -> None:
    request = PrepareContextRequest.model_validate(json.loads(Path("prepare.json").read_text(encoding="utf-8")))
    async with PowerContextClient("http://127.0.0.1:8000") as client:
        prepared = await client.prepare_context(request)
    Path("context.md").write_text(prepared.content or "", encoding="utf-8")

asyncio.run(export_context())
```

## Choose the output policy

| Setting | Behavior |
| --- | --- |
| Omit `assembly` | Preserve legacy output and selection. |
| `"assembly": {}` | Markdown, Memory up to 6 entries followed by Experience up to 2, no optional metadata. |
| `"assembly": {"sections": []}` | Return an empty result after request and current-Scope checks; perform no candidate recall. |
| One `memory` section | Recall only Memory; its limit is 1–8. |
| One `experience` section | Recall only approved Experience; its limit is 1–2. |
| One `profile` section | Read the latest committed Profile snapshot from each selected Scope; its limit is 1–8. |
| Two or three sections | Their order controls both presentation and byte-budget priority. Limits must total at most 8. |
| `show: ["recall_rank"]` | Display each entry's position in its family's deduplicated candidate list. |
| `show: ["confidence"]` | Display `unknown (not assessed)`; no numerical confidence has been assessed. |

Entries retain retrieval order within a family. Existing Memory reranking remains authoritative. Rank can have gaps
when an earlier entry cannot fit. An excluded family is not recalled. Duplicate families, invalid limits, unsupported
fields such as `sort_by` or `min_confidence`, and explicit `assembly: null` return HTTP 422.

`max_bytes` is the UTF-8 budget for the complete server text: 512–32768, default 8000. Each body is capped at 2000
bytes. When space is insufficient, the Server shortens a body or skips it while retaining complete citations and
boundaries. It may return fewer entries than requested. Hosts must validate the envelope and budget and preserve
the returned text; they must not trim it again. Hosts may add their own notice outside it.

## Include Profile snapshots

Select Profile explicitly to put the current Scope's preferences before task memories:

```json
{
  "sections": [
    {"family": "profile", "limit": 1},
    {"family": "memory", "limit": 6}
  ]
}
```

Use this object as `assembly` or as a plugin's context assembly setting. Profile is excluded when `assembly` is
omitted or `{}`. Each Profile item is one complete Scope snapshot before the usual body and total-byte limits
are applied. `limit` counts snapshots, not individual preferences. A missing snapshot contributes no item;
`limit: 1` selects the first available snapshot in current-Scope then direct-Context-Reference order.

The Server reads the latest committed `family=profile, artifact_id=profile` revision in each selected Scope.
It does not generate a new Profile, search it using `query`, or include pending/rejected Candidates. It does not
traverse indirect references or subject bindings. Every referenced Scope requires read permission. Revision
citations remain exact after replacements, and a truncated snapshot is marked `Truncated: yes`.
`recall_rank` is its position in the Profile candidate list, not a relevance or confidence score.

## Enable automatic plugin recall

For Codex, set the JSON object before starting a new session:

```bash
export POWERCONTEXT_CODEX_CONTEXT_ASSEMBLY='{"sections":[{"family":"experience","limit":2},{"family":"memory","limit":5}],"show":["confidence","recall_rank"]}'
codex
```

The same request object is available through these integration settings:

| Integration | Setting |
| --- | --- |
| Codex | `POWERCONTEXT_CODEX_CONTEXT_ASSEMBLY` |
| Claude Code | `POWERCONTEXT_CLAUDE_CONTEXT_ASSEMBLY` |
| WorkBuddy | `POWERCONTEXT_WORKBUDDY_CONTEXT_ASSEMBLY` |
| DeepSeek Harness | `POWERCONTEXT_DSH_CONTEXT_ASSEMBLY` or plugin `contextAssembly` |
| OpenCode | `POWERCONTEXT_OPENCODE_CONTEXT_ASSEMBLY` |
| Pi | `POWERCONTEXT_PI_CONTEXT_ASSEMBLY` |
| Hermes | `POWERCONTEXT_HERMES_CONTEXT_ASSEMBLY` or provider `context_assembly` |
| LangChain | `POWERCONTEXT_LANGCHAIN_CONTEXT_ASSEMBLY` or settings `context_assembly` |
| LangGraph | `POWERCONTEXT_LANGGRAPH_CONTEXT_ASSEMBLY` or settings `context_assembly` |
| Pydantic AI | `POWERCONTEXT_PYDANTIC_AI_CONTEXT_ASSEMBLY` or settings `context_assembly` |
| Bub | `POWERCONTEXT_BUB_CONTEXT_ASSEMBLY` or settings `context_assembly` |
| OpenClaw | `plugins.entries.memory-powercontext.config.contextAssembly` as an object |

Environment values are JSON strings; object settings take the equivalent object. Remove the setting to return to
legacy output. Upgrade the Server and relevant integration before enabling it. Older Servers reject `assembly`;
plugins report the failure through their existing diagnostics and do not retry with a broader selection.

The LangChain, LangGraph, and Pydantic AI adapters can use `powercontext==0.2.0` for legacy recall when
`context_assembly` is unset. Enabling it requires a core Client and Server that support text assembly; an older
Client raises a settings validation error. From a checkout containing this feature, install the core and the adapter
together, choosing the adapter directory you use:

```bash
uv pip install ".[client]" ./integrations/langchain
uv pip install ".[client]" ./integrations/langgraph
uv pip install ".[client]" ./integrations/pydantic-ai
```

Hermes applies the configured assembly to automatic recall, the `powercontext_prepare_context` tool, and
`/pc call prepare_context`. Explicit request values override the configured defaults.

LangGraph and Hermes include assembly settings and the byte budget in cache identity. Changing the policy cannot
reuse a prepared result from a different selection or budget. The feature adds no database table or HTTP endpoint.
