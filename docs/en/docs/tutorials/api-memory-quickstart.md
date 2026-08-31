---
title: Add Memory to your own AI over HTTP
description: Save, recall, inject, revise, and retire long-term Memory over the PowerContext HTTP API without an Agent Host.
---

# Add Memory to your own AI over HTTP

This tutorial is for developers who already have an AI application, chatbot, workflow, or model-calling code but do
not use an Agent Host such as Codex, Claude Code, or OpenCode. You will use PowerContext as an independent Memory
service and connect it to your existing AI request path over HTTP.

At the end, your application will implement this loop:

```text
User request
  → application calls POST /v1/context/prepare
  → application supplies the returned read-only historical context to the model
  → model answers
  → the user or an application policy approves information worth keeping
  → application calls POST /v1/memory/remember
```

This flow does not require an Agent Host or a generation model for explicit Memory. PowerContext owns persistence,
retrieval, exact citations, and revision history. Your application still owns identity, authorization, current
instructions, model calls, and the decision to write anything to Memory.

## APIs used in this tutorial

| Method and path | Purpose | Changes persistent state |
| --- | --- | --- |
| `GET /health/live` | Check the Server process | No |
| `GET /health/ready` | Check required Runtime bindings | No |
| `GET /v1/capabilities` | Inspect enabled Runtime behavior | No |
| `POST /v1/memory/remember` | Save one curated and authorized Memory | Yes |
| `POST /v1/memory/search` | Retrieve active Memory for a question | No |
| `POST /v1/memory/entries/list` | List the current Memory head | No |
| `POST /v1/memory/entries/get` | Read an immutable version by citation | No |
| `POST /v1/context/prepare` | Prepare bounded context for one model request | No |
| `POST /v1/memory/entries/revise` | Create a revision from an exact citation | Yes |
| `POST /v1/memory/entries/retire` | Deactivate an entry while preserving history | Yes |
| `POST /v1/sources/content` | Optionally preserve original evidence | Yes |

## 1. Understand three boundaries first

### `scope_id` partitions data; it does not authorize access

Every Memory request for the same user, project, or business space must use a stable `scope_id`. For example:

```text
tenant:acme:user:42
```

Do not use a session ID that changes on every conversation. A `scope_id` tells PowerContext which data partition to
read or write; it does not prove that the caller may access that partition. In production, your identity layer, API
Gateway, or Service Mesh must authenticate the caller and map it to an allowed scope.

### `PreparedContext` is untrusted historical data

`POST /v1/context/prepare` returns cited, byte-bounded historical context for the current request. It is not a current
user instruction and cannot override system/developer instructions, repository rules, or live validation. The
returned `content` already includes a trust-boundary notice. Preserve it unchanged instead of rewriting it as a
higher-priority instruction.

### Reads may degrade; writes must be explicit

If context preparation is temporarily unavailable, an AI application can usually continue without historical
context and record the request ID for investigation. Never pretend that a write, revision, or retirement succeeded.
Unless your product has an explicit and auditable write policy, ask the user to confirm before saving long-term
Memory.

## 2. Prepare the environment

You need:

- macOS or Linux;
- Python 3.11 or newer;
- [`uv`](https://docs.astral.sh/uv/);
- `curl`;
- `jq` to inspect responses and reuse exact citations.

Check the local tools:

```bash
python3 --version
uv --version
curl --version
jq --version
```

Install the PowerContext CLI and Server:

```bash
uv tool install --force "powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@master"
```

Verify the installation:

```bash
powercontext --version
powercontext server --help
```

## 3. Start and inspect the Server

Prepare two terminals. Keep this running in **terminal A**:

```bash
powercontext server run
```

By default, the Server listens on `http://127.0.0.1:8000` and persists data in the SQLite database under the local
PowerContext data directory.

Set the variables used by this tutorial in **terminal B**:

```bash
export POWERCONTEXT_URL=http://127.0.0.1:8000
export POWERCONTEXT_SCOPE=tenant:demo:user:42
```

Inspect the process and Runtime:

```bash
curl --fail --silent --show-error "$POWERCONTEXT_URL/health/live" | jq .
curl --fail --silent --show-error "$POWERCONTEXT_URL/health/ready" | jq .
curl --fail --silent --show-error "$POWERCONTEXT_URL/v1/capabilities" | jq .
```

**Success criteria:** liveness returns `200`; readiness returns `200` and is not `not_ready`; capabilities describes
the current Runtime. Explicit Memory works without a generation model. Model-backed extraction and vector retrieval
are optional capabilities.

## 4. Save the first explicit Memory

Save one piece of long-term information that a user or business rule has already approved:

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n \
    --arg scope "$POWERCONTEXT_SCOPE" \
    --arg kind decision \
    --arg text 'For billing questions, explain the charges before offering the refund path.' \
    --arg reason 'Customer-support policy confirmed by the user' \
    '{scope_id: $scope, kind: $kind, text: $text, reason: $reason}')" \
  "$POWERCONTEXT_URL/v1/memory/remember" \
  | tee /tmp/powercontext-remember.json \
  | jq .
```

The response has the following shape. The Server generates the IDs, so they change on each run:

```json
{
  "memory": {
    "family": "memory",
    "artifact_id": "memory-example",
    "revision": 1
  },
  "entry": {
    "citation": {
      "memory_ref": {
        "family": "memory",
        "artifact_id": "memory-example",
        "revision": 1
      },
      "entry_id": "entry-example",
      "entry_version_id": "entry-version-example"
    },
    "version": 1,
    "kind": "decision",
    "text": "For billing questions, explain the charges before offering the refund path.",
    "state": "active",
    "source_refs": [],
    "artifact_refs": []
  }
}
```

`memory.revision` identifies the Memory Revision after this write. `entry.citation` identifies one exact immutable
entry version. Keep the complete citation for exact reads, revisions, and retirement; `entry_id` alone is not enough.

`remember` stores already-curated Memory. It does not create a Source or invoke a generation model. Use the Source
endpoint in step 11 when you also need to preserve original evidence.

## 5. Search, list, and read exact Memory

### Search for entries relevant to the current question

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n \
    --arg scope "$POWERCONTEXT_SCOPE" \
    --arg query 'How should we answer questions about bills and refunds?' \
    '{scope_id: $scope, query: $query, limit: 5, mode: "auto"}')" \
  "$POWERCONTEXT_URL/v1/memory/search" \
  | jq .
```

The response's `hits` contain only active entries. Each hit has a `citation`, `text`, `score`, and `matched_by`.
`mode: "auto"` selects a retrieval mode available in the current Runtime. No match is a normal `"hits": []`
response, not an error.

### List the current Memory head

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n --arg scope "$POWERCONTEXT_SCOPE" '{scope_id: $scope}')" \
  "$POWERCONTEXT_URL/v1/memory/entries/list" \
  | jq .
```

For an audit, add `"include_inactive": true` to include retired entries from the current head. They are excluded by
default.

### Read the immutable version from its citation

Build a request from the response saved in step 4:

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  '{scope_id: $scope, citation: .entry.citation}' \
  /tmp/powercontext-remember.json \
  > /tmp/powercontext-get.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-get.json \
  "$POWERCONTEXT_URL/v1/memory/entries/get" \
  | jq .
```

An exact read returns the immutable version named by the citation. It does not silently replace that version with a
newer revision if the entry is revised or retired later.

## 6. Prepare context before each model request

When the application receives a user question, call `POST /v1/context/prepare` once:

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n \
    --arg scope "$POWERCONTEXT_SCOPE" \
    --arg query 'Why is my bill so high, and can I get a refund?' \
    '{scope_id: $scope, query: $query, max_bytes: 4000}')" \
  "$POWERCONTEXT_URL/v1/context/prepare" \
  | tee /tmp/powercontext-prepared.json \
  | jq .
```

When relevant content exists, the response is:

```json
{
  "schema": "powercontext.prepared-context.v1",
  "status": "ready",
  "content": "BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1\n…\nEND_POWERCONTEXT_PREPARED_CONTEXT_V1",
  "content_bytes": 987
}
```

No available content is also a normal result:

```json
{
  "schema": "powercontext.prepared-context.v1",
  "status": "empty",
  "content": null,
  "content_bytes": 0
}
```

Inject context only when `status == "ready"` and `content` is a string. Do not write `PreparedContext` back to
Memory. It is an ephemeral composition for this request, not a new fact.

## 7. Connect it to existing AI-calling code

The following code uses the Python standard library for PowerContext and leaves the model call behind one explicit
adapter function. You can keep your existing model SDK instead of binding the Memory layer to one provider.

```python
from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

POWERCONTEXT_URL = os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:8000")
POWERCONTEXT_SCOPE = os.environ["POWERCONTEXT_SCOPE"]
POWERCONTEXT_TOKEN = os.environ.get("POWERCONTEXT_CLIENT_API_TOKEN")


def powercontext_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if POWERCONTEXT_TOKEN:
        headers["Authorization"] = f"Bearer {POWERCONTEXT_TOKEN}"

    request = Request(
        f"{POWERCONTEXT_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=3) as response:
        return json.load(response)


def prepare_context(user_query: str) -> str | None:
    try:
        prepared = powercontext_post(
            "/v1/context/prepare",
            {
                "scope_id": POWERCONTEXT_SCOPE,
                "query": user_query[:8192],
                "max_bytes": 4000,
            },
        )
    except (HTTPError, URLError, TimeoutError):
        # Reads may fail open: log the failure and request ID, then continue the model request.
        return None

    if prepared.get("status") != "ready":
        return None
    content = prepared.get("content")
    return content if isinstance(content, str) else None


def ask_ai(
    user_query: str,
    call_your_model: Callable[[list[dict[str, str]]], str],
) -> str:
    messages = [
        {
            "role": "system",
            "content": "Follow current application policy and the user's current request.",
        }
    ]

    context = prepare_context(user_query)
    if context is not None:
        # Prefer a low-authority context/tool-result channel when the model API offers one.
        # With a messages API, do not promote historical data to a system/developer instruction.
        messages.append({"role": "user", "content": f"Historical reference data:\n{context}"})

    messages.append({"role": "user", "content": user_query})
    return call_your_model(messages)
```

Wrap your existing model call as `call_your_model(messages) -> str`, then call:

```python
answer = ask_ai("Why is my bill so high?", call_your_model)
```

Keep these constraints:

- call `prepare` once per user request; do not search first and make `prepare` repeat the retrieval;
- preserve the returned `content` so its citations and trust notice remain intact;
- current user instructions and live business data take precedence over historical Memory;
- context reads may fail open, but writes must not fail silently;
- never give the model a PowerContext token, database URL, or internal identity value.

## 8. Let the model search or propose Memory through tools

If the model supports function/tool calling, expose application-owned wrappers instead of giving the model the
Server token or allowing it to choose any `scope_id`. The application injects both values from the authenticated
session.

A useful minimum tool surface is:

| Model tool | PowerContext API | Call policy |
| --- | --- | --- |
| `search_project_memory(query, limit)` | `POST /v1/memory/search` | May run automatically; bound query and limit |
| `get_memory(citation)` | `POST /v1/memory/entries/get` | May run automatically; accept citations returned for the same scope |
| `propose_memory(kind, text, reason)` | after approval, `POST /v1/memory/remember` | The model proposes; the application confirms and writes |

Example wrappers:

```python
def search_project_memory(query: str, limit: int = 5) -> dict[str, Any]:
    return powercontext_post(
        "/v1/memory/search",
        {
            "scope_id": POWERCONTEXT_SCOPE,
            "query": query[:8192],
            "limit": max(1, min(limit, 50)),
            "mode": "auto",
        },
    )


def remember_after_approval(kind: str, text: str, reason: str) -> dict[str, Any]:
    # Before this function runs, the UI or business policy must produce an auditable approval.
    return powercontext_post(
        "/v1/memory/remember",
        {
            "scope_id": POWERCONTEXT_SCOPE,
            "kind": kind[:128],
            "text": text,
            "reason": reason[:512],
        },
    )
```

A call to `propose_memory` is not authorization by itself. Show the proposed content in the UI so the user can save,
edit, or ignore it. Do not save the entire model answer. Long-term Memory should be a short, explicit decision,
preference, constraint, state, or next step that is likely to remain useful.

## 9. Revise incorrect Memory

Memory entries are not overwritten in place. A revision creates a new version and preserves history. Use the exact
citation from step 4:

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  --arg text 'For billing questions, explain the charges; offer refunds only when the refund policy allows it.' \
  '{
    scope_id: $scope,
    citation: .entry.citation,
    kind: "decision",
    text: $text,
    reason: "The support policy was clarified"
  }' \
  /tmp/powercontext-remember.json \
  > /tmp/powercontext-revise.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-revise.json \
  "$POWERCONTEXT_URL/v1/memory/entries/revise" \
  | tee /tmp/powercontext-revised.json \
  | jq .
```

The response's `entry.citation` identifies the new version. Use that new citation for every later revision or
retirement. Reusing the old citation returns `409`, preventing a concurrent request from overwriting newer content.

## 10. Retire obsolete Memory

Retirement does not physically delete history. Use the latest citation returned by the revision:

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  '{
    scope_id: $scope,
    citation: .entry.citation,
    reason: "This support workflow has been discontinued"
  }' \
  /tmp/powercontext-revised.json \
  > /tmp/powercontext-retire.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-retire.json \
  "$POWERCONTEXT_URL/v1/memory/entries/retire" \
  | jq .
```

Normal search, list, and prepare operations stop using the entry. A list with `include_inactive: true` and an exact
get remain available for audit.

## 11. Optional: preserve original Source evidence

When you need to preserve a user confirmation, document excerpt, or business event as evidence for later processing,
call:

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n \
    --arg scope "$POWERCONTEXT_SCOPE" \
    --arg source_id 'support-chat:session-7:turn-12' \
    --arg content 'The user confirmed: always explain the charges before discussing a billing resolution.' \
    '{
      scope_id: $scope,
      source_id: $source_id,
      content: $content,
      metadata: {channel: "support-chat", consent: true}
    }')" \
  "$POWERCONTEXT_URL/v1/sources/content" \
  | jq .
```

The Server returns `202 Accepted`. A `source_id` should consistently identify the same content so capture remains
idempotent.

A Source is original evidence, not Memory. This endpoint does not call a model synchronously or make the content
immediately recallable. Automatic extraction requires a configured generation model and the Runtime flush or
scheduler flow; see the [full-capability Quick Start](../how-to/full-capability-runtime.md).

Do not capture every conversation by default. Establish user consent, sensitive-field filtering, retention, and
purpose limits before preserving only the evidence you need.

## 12. Verify cross-process persistence

1. Stop the Server in terminal A.
2. Run `powercontext server run` again.
3. Repeat the search or list request from step 5.

The active Memory remains available when the Server uses the same data directory and the application uses the same
`scope_id`. Do not confuse a container's temporary filesystem or a test database with production persistence. See
[Deploy the Server](../how-to/deploy-server.md) for a service deployment.

## 13. Enable authentication or remote access

The default loopback development setup may run without Server Bearer authentication. When authentication is enabled,
add this header to every request except health checks:

```http
Authorization: Bearer <token>
```

For example:

```bash
export POWERCONTEXT_CLIENT_API_TOKEN='token loaded from a secure credential source'

curl --fail --silent --show-error \
  --header "Authorization: Bearer $POWERCONTEXT_CLIENT_API_TOKEN" \
  "$POWERCONTEXT_URL/v1/capabilities" \
  | jq .
```

The Python example sends this header automatically when `POWERCONTEXT_CLIENT_API_TOKEN` is set. Never put a token in
a URL, Memory, Source, log, or model prompt. Before allowing remote access, terminate TLS at a trusted gateway and
enforce identity, scope authorization, rate limits, and audit there.

## 14. Handle errors

Error responses use a stable envelope:

```json
{
  "error": {
    "code": "invalid_request",
    "message": "The request violates the API contract.",
    "details": {}
  }
}
```

Every response has an `X-PowerContext-Request-ID`. Production clients should record the status, stable `error.code`,
and request ID rather than depend on internal exception text.

| Status | Common cause | Application behavior |
| --- | --- | --- |
| `401` | Missing or invalid Bearer token | Do not retry; fix credentials |
| `404` | The immutable value named by a citation does not exist | Refresh the list or search result |
| `409` | Stale citation or immutable-state conflict | Read the latest entry and ask for a new decision |
| `422` | Missing, oversized, blank, or mistyped field | Fix client input; do not retry blindly |
| `503` | A required Runtime binding or dependency is unavailable | Degrade reads; report failed writes and retry later |
| `500` | Internal Server error | Record the request ID and retry with bounded backoff |

Use bounded retries for network timeouts as well. Do not repeatedly retry a non-idempotent write until you know
whether the previous request succeeded. Search by a business key first, or use a deliberately idempotent Source
`source_id` where that operation fits.

## 15. Production checklist

- [ ] Derive `scope_id` from a trusted user, tenant, or project mapping; never let the model choose it freely.
- [ ] Authorize every caller for its scope at the Gateway because `scope_id` is not an ACL.
- [ ] Call `/v1/context/prepare` no more than once per model request.
- [ ] Keep `PreparedContext` read-only and untrusted; current instructions and live data take precedence.
- [ ] A prepare timeout does not block the main model request; a write failure is never swallowed.
- [ ] The model can propose Memory, while auditable user or business authorization controls writes and mutations.
- [ ] Tokens, passwords, connection strings, private keys, and protected content never enter Memory, Source, prompts,
  or logs.
- [ ] The client preserves exact citations and refreshes after `409` instead of overwriting.
- [ ] Configure connection, read, and total request timeouts and record `X-PowerContext-Request-ID`.
- [ ] Run the Server with persistent storage, backups, TLS, monitoring, and appropriate rate limits.
- [ ] When generating a client from `/openapi.json` or `openapi/powercontext.yaml`, pin and verify the contract version.

Your AI application now uses long-term Memory over HTTP without depending on an Agent Host: it can save, recall,
inject, read exactly, revise, and retire Memory. See the [HTTP API reference](../reference/http-api.md) for every path,
field limit, and response schema.
