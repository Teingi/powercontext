---
title: Complete PowerContext HTTP API tutorial
description: Use Source, Memory, PreparedContext, Work, Handoff, Experience, Skill, Review, Report, and Stats without an Agent Host.
---

# Complete PowerContext HTTP API tutorial

This tutorial is for developers who already have an AI application, chatbot, workflow, or model-calling code but do
not use an Agent Host such as Codex, Claude Code, or OpenCode. You will use PowerContext as an independent context
service and complete this HTTP API lifecycle:

```text
Inspect the Server and capabilities
  → capture Source evidence
  → save, retrieve, and maintain Memory
  → prepare context for each model request
  → record Work, Handoff, and Task Outcome
  → generate or propose an Experience Candidate from evidence
  → Review creates an approved Experience
  → incubate a managed Skill from Experience, Source, or usage
  → Review, read, and use an exact Skill Revision
  → operate the system with External Skill, Report, and Stats APIs
```

One self-built AI engineering assistant is used throughout the tutorial. The main path uses `curl` and JSON, requires
no Agent Host, and ends with a reusable Python integration boundary.

## 1. Understand the product boundaries

PowerContext does not automatically promote every record into a Skill. Each object has a distinct purpose and
authorization boundary:

| Object | What it stores | How it is produced | When it is available |
| --- | --- | --- | --- |
| Source | Original evidence such as input, task results, and document excerpts | Persisted immediately on capture | Exact evidence; not recalled directly |
| Memory | Durable facts, decisions, preferences, and constraints | Explicit write or model-backed extraction from Source | Active entries can participate in search and `PreparedContext` |
| PreparedContext | Cited, bounded historical context for one request | Prepared ephemerally by the Runtime | One model request only; never persisted |
| Work/Handoff | Objective, verified state, omissions, and next action | Explicitly recorded, prepared, acknowledged, and committed | Transfers work across sessions, models, applications, or workers |
| Experience | What was done in a situation, the outcome, and the lesson | Complete proposal or generated Candidate followed by Review | The approved current Revision may participate in `PreparedContext` |
| managed Skill | What to do next time and how to validate it | Candidate from Experience, Source, or usage followed by Review | Exact read or explicit publication; never automatically in `PreparedContext` |
| external Skill | An Agent-native Skill package already on this host | Scan an explicitly configured local target | Resolvable only while fingerprint and local binding match |

Three rules apply to every API family:

1. `scope_id` partitions business data; it is not authorization. A Gateway must authorize the caller for the scope.
2. A Candidate is an untrusted proposal. A model cannot approve its own Candidate or commit the final Artifact.
3. An approved Skill is governed content, not permission to use files, networks, secrets, tools, or publication.

## 2. Public API map

The current OpenAPI contract exposes 53 public operations:

| Domain | Path prefix | Operations covered here |
| --- | --- | --- |
| Health and capability | `/health/*`, `/v1/capabilities` | live, ready, capabilities |
| Source and Context | `/v1/sources/*`, `/v1/context/*` | capture, prepare |
| Work | `/v1/work/*` | contract, current Handoff, acknowledgement, outcome |
| Low-level Handoff | `/v1/handoff/*` | activate, prepare, finalize, commit, continue |
| Memory | `/v1/memory/*` | flush, remember, search, list, get, revise, retire, changes |
| Experience | `/v1/experience/*` | propose, generate, get |
| managed Skill | `/v1/skill/*` | propose, generate, get |
| Candidate Review | `/v1/artifact-candidates/*` | list, get, revise, approve, reject |
| External Skill | `/v1/external-skills/*` | scan, list, resolve, import/fork |
| Stats | `/v1/stats` | scoped inventory, model usage, recall estimates |
| Handoff Report | `/v1/handoff-reports/*` | Project, Workstream, Report, Activity, Workspace binding |

This tutorial explains ordering and workflows. Use
[`openapi/powercontext.yaml`](https://github.com/oceanbase/powercontext/blob/master/openapi/powercontext.yaml) for every
field limit, enum, and response schema.

## 3. Prepare the environment

You need macOS or Linux, Python 3.11+, `uv`, `curl`, and `jq`:

```bash
python3 --version
uv --version
curl --version
jq --version
```

Install the CLI and Server:

```bash
uv tool install --force "powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@master"
```

Verify the installation:

```bash
powercontext --version
powercontext server --help
```

Explicit Memory, Source, Work, Handoff, typed proposals, Review, and exact reads do not require a generation model.
`/experience/generate`, `/skill/generate`, external Skill import/fork, Source-to-Memory extraction, and vector behavior
require their configured providers.

## 4. Start the Server

Keep this running in **terminal A**:

```bash
powercontext server run
```

The default address is `http://127.0.0.1:8000`. Data is persisted in the SQLite database under the PowerContext user
data directory.

Set tutorial variables in **terminal B**:

```bash
export POWERCONTEXT_URL=http://127.0.0.1:8000
export POWERCONTEXT_SCOPE=tenant:demo:project:api-tutorial
```

Do not use a session ID that changes on every conversation. Source, Memory, Experience, Skill, and Handoff for one
project must reuse the same stable scope.

## 5. Inspect health, capabilities, and the contract

```bash
curl --fail --silent --show-error "$POWERCONTEXT_URL/health/live" | jq .
curl --fail --silent --show-error "$POWERCONTEXT_URL/health/ready" | jq .
curl --fail --silent --show-error "$POWERCONTEXT_URL/v1/capabilities" | jq .
```

Success criteria:

- liveness returns `200`;
- readiness returns `200` with `ready`, or `degraded` when the required base runtime remains usable;
- capabilities lists `artifact_families`, search modes, and generation switches.

The running process exposes:

- `/docs` for Swagger UI;
- `/redoc` for ReDoc;
- `/openapi.json` for the exact runtime OpenAPI JSON.

## 6. Authentication and common request rules

The default loopback development setup may run without Bearer authentication, so the main commands omit an
`Authorization` header. When authentication is enabled, add this to every request except health checks:

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

Never place a token in a URL, Memory, Source, model prompt, or log. Before remote access, terminate TLS at a trusted
Gateway or Service Mesh and enforce identity, scope authorization, rate limits, and audit there.

Every response includes `X-PowerContext-Request-ID`. To inspect headers and body together:

```bash
curl --silent --show-error \
  --dump-header /tmp/powercontext-headers.txt \
  "$POWERCONTEXT_URL/v1/capabilities" \
  | jq .

grep -i '^X-PowerContext-Request-ID:' /tmp/powercontext-headers.txt
```

## 7. Know the four exact reference shapes

Later requests reuse exact Server-returned references instead of fuzzy names:

```json
{
  "source_ref": {
    "name": "content",
    "source_id": "task:billing-api:result:1"
  },
  "artifact_ref": {
    "family": "experience",
    "artifact_id": "experience-example",
    "revision": 1
  },
  "memory_citation": {
    "memory_ref": {
      "family": "memory",
      "artifact_id": "memory-example",
      "revision": 1
    },
    "entry_id": "entry-example",
    "entry_version_id": "entry-version-example"
  },
  "candidate_identity": {
    "candidate_id": "candidate-example",
    "expected_version": 1
  }
}
```

- `SourceReference` identifies captured original evidence.
- `ArtifactReference` identifies an immutable Experience, Skill, Handoff, or Memory Revision.
- `MemoryCitation` further identifies an immutable entry version inside one Memory Revision.
- Candidate mutations use `candidate_id + expected_version` so Review cannot act on stale content.

The tutorial saves responses under `/tmp/powercontext-*.json` and uses `jq` to construct dependent requests.

## 8. Capture the first Source

Preserve one completed task result as common evidence for later Work, Experience, and Skill operations:

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n \
    --arg scope "$POWERCONTEXT_SCOPE" \
    '{
      scope_id: $scope,
      source_id: "task:billing-api:result:1",
      content: "Billing API integration completed. The client now explains line items before presenting a refund path. Contract tests passed.",
      metadata: {
        kind: "task-outcome",
        consent: true,
        producer: "tutorial-application"
      }
    }')" \
  "$POWERCONTEXT_URL/v1/sources/content" \
  | tee /tmp/powercontext-source.json \
  | jq .
```

Success is `202 Accepted` with `status: "accepted"`, an exact `source`, and a journal `position`.

The same `scope_id + source_id` must continue to identify the same content:

- replaying identical content is idempotent;
- different content under the same ID returns `409`;
- a Source does not synchronously become Memory, Experience, or Skill;
- do not capture whole conversations by default; apply consent, sensitive-field filtering, and retention policy.

## 9. Save explicit Memory

Select one durable decision from the task result:

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n \
    --arg scope "$POWERCONTEXT_SCOPE" \
    '{
      scope_id: $scope,
      kind: "decision",
      text: "For billing questions, explain each charge; offer a refund path only when the order meets current policy.",
      reason: "User-approved support policy"
    }')" \
  "$POWERCONTEXT_URL/v1/memory/remember" \
  | tee /tmp/powercontext-memory.json \
  | jq .
```

The response contains a new `memory` ArtifactReference and `entry.citation`. `remember` does not create a Source or
invoke a model.

### Search active Memory

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n \
    --arg scope "$POWERCONTEXT_SCOPE" \
    '{scope_id: $scope, query: "How should billing and refund questions be answered?", limit: 5, mode: "auto"}')" \
  "$POWERCONTEXT_URL/v1/memory/search" \
  | jq .
```

No match is a normal `"hits": []`. Modes are `auto`, `fts`, `vector`, and `hybrid`; actual availability comes from
capabilities.

### List the current Memory head

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n --arg scope "$POWERCONTEXT_SCOPE" '{scope_id: $scope}')" \
  "$POWERCONTEXT_URL/v1/memory/entries/list" \
  | jq .
```

Add `include_inactive: true` for an audit.

### Read the exact immutable entry version

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  '{scope_id: $scope, citation: .entry.citation}' \
  /tmp/powercontext-memory.json \
  > /tmp/powercontext-memory-get.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-memory-get.json \
  "$POWERCONTEXT_URL/v1/memory/entries/get" \
  | jq .
```

### Revise Memory

A revision creates a new entry version and preserves history:

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  '{
    scope_id: $scope,
    citation: .entry.citation,
    kind: "decision",
    text: "For billing questions, explain each line item; offer a refund path only after current eligibility passes.",
    reason: "Support policy clarified"
  }' \
  /tmp/powercontext-memory.json \
  > /tmp/powercontext-memory-revise.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-memory-revise.json \
  "$POWERCONTEXT_URL/v1/memory/entries/revise" \
  | tee /tmp/powercontext-memory-revised.json \
  | jq .
```

Use the new citation for every later mutation. Revising from the old citation returns `409`.

### Inspect Revision changes

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n --arg scope "$POWERCONTEXT_SCOPE" '{scope_id: $scope, since_revision: 0}')" \
  "$POWERCONTEXT_URL/v1/memory/changes" \
  | jq .
```

### Optional: retire obsolete Memory

Do not run the retirement command yet if you are following the continuous scenario: steps 11 and 12 still use this
Memory. Run it after completing those steps, or use it now only to test inactive-entry auditing.

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  '{scope_id: $scope, citation: .entry.citation, reason: "This workflow has been discontinued"}' \
  /tmp/powercontext-memory-revised.json \
  > /tmp/powercontext-memory-retire.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-memory-retire.json \
  "$POWERCONTEXT_URL/v1/memory/entries/retire" \
  | jq .
```

Retirement is not physical deletion. Normal search, list, and prepare exclude the entry; exact get and
`include_inactive: true` remain available for audit.

## 10. Extract Memory from pending Sources

With a generation model configured, `flush` processes one bounded Source window:

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n --arg scope "$POWERCONTEXT_SCOPE" '{scope_id: $scope}')" \
  "$POWERCONTEXT_URL/v1/memory/flush" \
  | jq .
```

The response is `status: "processed"` or the normal `status: "idle"`, with cursors and a processed count. Explicit
`remember` still works without a generation model.

## 11. Prepare context for a model request

Call once for each user request:

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n \
    --arg scope "$POWERCONTEXT_SCOPE" \
    '{scope_id: $scope, query: "Why is my bill so high, and can I get a refund?", max_bytes: 4000}')" \
  "$POWERCONTEXT_URL/v1/context/prepare" \
  | tee /tmp/powercontext-context.json \
  | jq .
```

A ready response has this shape:

```json
{
  "schema": "powercontext.prepared-context.v1",
  "status": "ready",
  "content": "BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1\n...\nEND_POWERCONTEXT_PREPARED_CONTEXT_V1",
  "content_bytes": 1024
}
```

No available context is normal:

```json
{
  "schema": "powercontext.prepared-context.v1",
  "status": "empty",
  "content": null,
  "content_bytes": 0
}
```

`content` is ephemeral, read-only, untrusted historical data. Preserve its trust notice and citations. Do not write it
back to Memory or let it override current system/developer instructions, the current request, live business data, or
live validation.

## 12. Connect your model

This standard-library Python code wraps PowerContext. Connect your existing model SDK through `call_your_model`:

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


def prepare_context(query: str) -> str | None:
    try:
        prepared = powercontext_post(
            "/v1/context/prepare",
            {"scope_id": POWERCONTEXT_SCOPE, "query": query[:8192], "max_bytes": 4000},
        )
    except (HTTPError, URLError, TimeoutError):
        # Reads may fail open. Production code should also record status, error.code, and request ID.
        return None
    content = prepared.get("content")
    return content if prepared.get("status") == "ready" and isinstance(content, str) else None


def ask_ai(
    query: str,
    call_your_model: Callable[[list[dict[str, str]]], str],
) -> str:
    messages = [
        {"role": "system", "content": "Follow current application policy and the current user request."}
    ]
    context = prepare_context(query)
    if context:
        # Prefer a low-authority context/tool-result channel when the model API has one.
        messages.append({"role": "user", "content": f"Historical reference data:\n{context}"})
    messages.append({"role": "user", "content": query})
    return call_your_model(messages)
```

`PreparedContext` reads may fail open. Memory, Candidate, and Handoff writes must never fail silently.

### Model tool calling

Expose application wrappers, not a Server token or model-selected `scope_id`:

| Model tool | Backend API | Authorization policy |
| --- | --- | --- |
| `search_project_memory(query)` | `/v1/memory/search` | May read automatically; bound query and limit |
| `get_memory(citation)` | `/v1/memory/entries/get` | Accept citations returned for the current scope |
| `propose_memory(kind, text)` | after user confirmation, `/v1/memory/remember` | Model proposes; it does not save |
| `propose_experience(...)` | `/v1/experience/propose` | Creates only a pending Candidate |
| `propose_skill(...)` | `/v1/skill/propose` | Creates only a pending Candidate |

Do not expose Reviewer operations to the identity that proposed the Candidate.

## 13. Record a Work Contract

A Work Contract persists delegation boundaries without granting execution authority:

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  --slurpfile source /tmp/powercontext-source.json \
  '{
    scope_id: $scope,
    source_id: "work-contract:billing-api:1",
    contract: {
      schema: "powercontext.work-contract.v1",
      trust: "untrusted_input",
      objective: "Validate the billing explanation and refund-path API integration",
      facts: [{
        text: "One successful task result exists",
        basis: "verified",
        evidence: [{kind: "source", source_ref: $source[0].source}]
      }],
      in_scope: ["Validate response content", "Run contract tests"],
      exclusions: ["Change the production refund policy"],
      completion_criteria: ["Contract tests pass", "No sensitive data is exposed"],
      authorization_notes: ["Read-only access to the test environment"],
      open_questions: []
    }
  }' \
  > /tmp/powercontext-work-contract-request.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-work-contract-request.json \
  "$POWERCONTEXT_URL/v1/work/contracts/create" \
  | tee /tmp/powercontext-work-contract.json \
  | jq .
```

Success is `202` with a `WorkSourceReceipt`. The `source_id` follows Source idempotency rules.

## 14. Complete the high-level Work/Handoff loop

### Prepare current work

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  --slurpfile source /tmp/powercontext-source.json \
  '{
    scope_id: $scope,
    source_id: "handoff-boundary:billing-api:1",
    handoff: {
      schema: "powercontext.current-work-handoff.v1",
      trust: "untrusted_input",
      objective: "Continue validating the billing API",
      state: [{
        text: "The billing explanation flow is implemented and contract-tested",
        basis: "verified",
        evidence: [{kind: "source", source_ref: $source[0].source}]
      }],
      disposition: "continuable",
      next_action: {
        text: "Validate the refund eligibility branch in the test environment",
        basis: "declared",
        evidence: [{kind: "source", source_ref: $source[0].source}]
      },
      omissions: ["Production traffic has not been validated"]
    }
  }' \
  > /tmp/powercontext-handoff-current-request.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-handoff-current-request.json \
  "$POWERCONTEXT_URL/v1/work/handoffs/prepare-current" \
  | tee /tmp/powercontext-handoff-prepared-work.json \
  | jq .
```

The response contains a durable `boundary` Source receipt and an ephemeral `handoff`. Preparation is not a durable
Handoff milestone.

### Commit the Handoff Revision

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  '{scope_id: $scope, handoff: .handoff}' \
  /tmp/powercontext-handoff-prepared-work.json \
  > /tmp/powercontext-handoff-commit-request.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-handoff-commit-request.json \
  "$POWERCONTEXT_URL/v1/handoff/commit" \
  | tee /tmp/powercontext-handoff-committed.json \
  | jq .
```

Keep the response's exact immutable `reference`.

### Continue exactly and acknowledge receipt

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  '{scope_id: $scope, selection: "exact", revision: .reference}' \
  /tmp/powercontext-handoff-committed.json \
  > /tmp/powercontext-handoff-continue-request.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-handoff-continue-request.json \
  "$POWERCONTEXT_URL/v1/handoff/continue" \
  | jq .
```

The receiver must independently confirm live state, capability, and authorization:

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  --slurpfile committed /tmp/powercontext-handoff-committed.json \
  '{
    scope_id: $scope,
    source_id: "handoff-receipt:billing-api:1",
    receiver: "billing-assistant-worker-2",
    status: "accepted",
    selection: "exact",
    revision: $committed[0].reference,
    receiver_checks: {
      live_state: "confirmed",
      capability: "confirmed",
      authorization: "confirmed"
    },
    message: "The test environment and permissions were checked independently."
  }' \
  > /tmp/powercontext-handoff-ack-request.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-handoff-ack-request.json \
  "$POWERCONTEXT_URL/v1/work/handoffs/acknowledge" \
  | tee /tmp/powercontext-handoff-ack.json \
  | jq .
```

`accepted` means the receiver can continue; it does not mean the task is complete. Other statuses are
`needs_clarification` and `declined`.

### Record Task Outcome

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  --slurpfile ack /tmp/powercontext-handoff-ack.json \
  --slurpfile source /tmp/powercontext-source.json \
  '{
    scope_id: $scope,
    source_id: "task-outcome:billing-api:2",
    outcome: {
      schema: "powercontext.task-outcome.v1",
      trust: "untrusted_observation",
      objective: "Validate the refund eligibility branch",
      status: "succeeded",
      summary: "The eligible and ineligible test branches passed.",
      handoff_receipt_ref: $ack[0].receipt.source,
      observations: [{
        text: "The eligibility branch returned the expected schema",
        basis: "verified",
        evidence: [{kind: "source", source_ref: $source[0].source}]
      }],
      checks: [{
        name: "billing contract tests",
        status: "passed",
        details: "All contract cases passed",
        basis: "verified",
        evidence: [{kind: "source", source_ref: $source[0].source}]
      }],
      produced_artifacts: [],
      remaining_work: []
    }
  }' \
  > /tmp/powercontext-task-outcome-request.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-task-outcome-request.json \
  "$POWERCONTEXT_URL/v1/work/outcomes/record" \
  | tee /tmp/powercontext-task-outcome.json \
  | jq .
```

A Task Outcome is Source evidence for one attempt. It never approves an Experience or Skill automatically.

## 15. Low-level Handoff APIs

Use the lower-level state machine for a custom UI or finer control:

| Operation | Key request fields | Result |
| --- | --- | --- |
| `/v1/handoff/activate` | boundary Source, objective, optional evidence | A Draft or an already-consumed `ignored` boundary |
| `/v1/handoff/prepare` | objective and at least one exact evidence item | Uncommitted `HandoffDraft` |
| `/v1/handoff/finalize` | Complete inspected Draft | Ephemeral `PreparedHandoff` |
| `/v1/handoff/commit` | PreparedHandoff | Immutable Handoff Revision |
| `/v1/handoff/continue` | `prepared`, `exact`, or `latest` selection | Untrusted HandoffResolution |

Minimal direct prepare:

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  --slurpfile source /tmp/powercontext-source.json \
  '{
    scope_id: $scope,
    objective: "Continue validating the billing API",
    evidence: [{kind: "source", source_ref: $source[0].source}],
    max_bytes: 4000
  }' \
  > /tmp/powercontext-handoff-prepare-request.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-handoff-prepare-request.json \
  "$POWERCONTEXT_URL/v1/handoff/prepare" \
  | tee /tmp/powercontext-handoff-draft.json \
  | jq .
```

Inspect and, when necessary, edit the complete Draft before finalize. Never treat a model-generated Draft as an
approved fact.

## 16. Create an Experience Candidate

Experience contains `situation`, `action`, `outcome`, and `lesson`. Both paths below create only a pending Candidate.

### No model: submit a complete proposal

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  --slurpfile outcome /tmp/powercontext-task-outcome.json \
  '{
    scope_id: $scope,
    proposal: {
      situation: "The billing API must explain charges and handle refund eligibility safely.",
      action: "Validate the line-item contract, then test eligible and ineligible refund branches independently.",
      outcome: "All contract cases passed and the response never promised a refund before eligibility.",
      lesson: "Separate charge explanation from eligibility validation to reduce incorrect promises."
    },
    source_refs: [$outcome[0].source],
    artifact_refs: [],
    reason: "Propose reusable experience from a verified Task Outcome"
  }' \
  > /tmp/powercontext-experience-propose-request.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-experience-propose-request.json \
  "$POWERCONTEXT_URL/v1/experience/propose" \
  | tee /tmp/powercontext-experience-candidate.json \
  | jq .
```

Success is `201` with `family: "experience"`, `status: "pending"`, and `version: 1`.

### With a model: generate from exact evidence

Configure a generation model, restart the Server, and confirm `experience_generation: true`:

```bash
export POWERCONTEXT_SERVER_INFERENCE_GENERATION_MODEL=provider:model-name
powercontext server run
```

Then call:

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  --slurpfile outcome /tmp/powercontext-task-outcome.json \
  '{
    scope_id: $scope,
    source_refs: [$outcome[0].source],
    artifact_refs: [],
    reason: "Extract reusable experience from the completed task"
  }' \
  > /tmp/powercontext-experience-generate-request.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-experience-generate-request.json \
  "$POWERCONTEXT_URL/v1/experience/generate" \
  | jq .
```

The response is either `status: "pending"` with a Candidate or the normal `status: "no_op"`. Generation does not
approve the result.

A Memory `memory` ArtifactReference can be Artifact evidence, but it identifies the whole Memory Revision. Prefer a
Task Outcome or another Source when the Experience needs precise evidence of what happened.

## 17. Review the Candidate

### List the Review Inbox

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n --arg scope "$POWERCONTEXT_SCOPE" \
    '{scope_id: $scope, status: "pending", family: "experience", limit: 50}')" \
  "$POWERCONTEXT_URL/v1/artifact-candidates/list" \
  | jq .
```

### Read the current Candidate head

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  '{scope_id: $scope, candidate_id: .candidate_id}' \
  /tmp/powercontext-experience-candidate.json \
  > /tmp/powercontext-candidate-get-request.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-candidate-get-request.json \
  "$POWERCONTEXT_URL/v1/artifact-candidates/get" \
  | jq .
```

The reviewer checks the complete proposal, every Source/Artifact lineage item, target, and reason.

### Revise the Candidate

A revision submits a complete replacement proposal and evidence set, not a partial patch:

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  '{
    scope_id: $scope,
    candidate_id: .candidate_id,
    expected_version: .version,
    proposal: (.proposal + {lesson: "Validate line items before refund eligibility to avoid incorrect promises and improve explainability."}),
    source_refs: .source_refs,
    artifact_refs: .artifact_refs,
    target: .target,
    reason: "Reviewer added the explainability requirement"
  }' \
  /tmp/powercontext-experience-candidate.json \
  > /tmp/powercontext-candidate-revise-request.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-candidate-revise-request.json \
  "$POWERCONTEXT_URL/v1/artifact-candidates/revise" \
  | tee /tmp/powercontext-experience-candidate-revised.json \
  | jq .
```

### Approve the version that was inspected

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  '{scope_id: $scope, candidate_id: .candidate_id, expected_version: .version}' \
  /tmp/powercontext-experience-candidate-revised.json \
  > /tmp/powercontext-candidate-approve-request.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-candidate-approve-request.json \
  "$POWERCONTEXT_URL/v1/artifact-candidates/approve" \
  | tee /tmp/powercontext-experience-approved.json \
  | jq .
```

Approval atomically writes an immutable Experience Revision and returns `result_artifact`. To decline publication,
call `/v1/artifact-candidates/reject` with `candidate_id`, current `expected_version`, and a non-empty `reason`.

On `409`, get the Candidate again. Never retry approval against a stale version.

## 18. Read and recall the approved Experience

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  '{scope_id: $scope, artifact: .result_artifact}' \
  /tmp/powercontext-experience-approved.json \
  > /tmp/powercontext-experience-get-request.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-experience-get-request.json \
  "$POWERCONTEXT_URL/v1/experience/get" \
  | tee /tmp/powercontext-experience.json \
  | jq .
```

The approved current Experience may participate in `PreparedContext` for the same scope. Selection still depends on
query relevance and the byte budget shared with Memory. Pending, rejected, and historical Experience Revisions do
not automatically enter recall.

Prepare again with an Experience-relevant query:

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n --arg scope "$POWERCONTEXT_SCOPE" \
    '{scope_id: $scope, query: "How should billing explanation and refund eligibility be validated safely?", max_bytes: 8000}')" \
  "$POWERCONTEXT_URL/v1/context/prepare" \
  | jq .
```

## 19. Create a managed Skill Candidate

A Skill proposal has `name`, `description`, `instructions`, and at least one `validation` item.

### No model: submit a complete Skill

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  --slurpfile approved /tmp/powercontext-experience-approved.json \
  '{
    scope_id: $scope,
    proposal: {
      name: "validate-billing-response",
      description: "Validate that billing explanations and refund eligibility responses are safe and complete.",
      instructions: "1. Read line items.\n2. Explain each charge.\n3. Check refund eligibility independently.\n4. Offer the refund path only after eligibility passes.\n5. Record validation results.",
      validation: [
        "The response explains every relevant charge.",
        "The refund path appears only after eligibility passes.",
        "Credentials never enter logs or model context."
      ]
    },
    source_refs: [],
    artifact_refs: [$approved[0].result_artifact],
    reason: "Turn the approved Experience into reusable operating instructions"
  }' \
  > /tmp/powercontext-skill-propose-request.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-skill-propose-request.json \
  "$POWERCONTEXT_URL/v1/skill/propose" \
  | tee /tmp/powercontext-skill-candidate.json \
  | jq .
```

### With a model: generate by origin

`/v1/skill/generate` enforces three provenance shapes:

| origin | Required evidence | Forbidden shape |
| --- | --- | --- |
| `experience` | One or more approved Experience ArtifactReferences | target or non-Experience artifacts |
| `source` | One or more SourceReferences | target or any artifact |
| `usage` | Usage Source, exact current Skill target, and target also in artifacts | missing target or Source |

Generate from the approved Experience:

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  --slurpfile approved /tmp/powercontext-experience-approved.json \
  '{
    scope_id: $scope,
    origin: "experience",
    source_refs: [],
    artifact_refs: [$approved[0].result_artifact],
    reason: "Turn reviewed experience into a reusable Skill"
  }' \
  > /tmp/powercontext-skill-generate-request.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-skill-generate-request.json \
  "$POWERCONTEXT_URL/v1/skill/generate" \
  | jq .
```

Generation still returns only a pending Candidate or `no_op`. Review Skill Candidates through the same operations in
step 17.

## 20. Approve, read, and use the Skill

Approve the manual Candidate from this tutorial:

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  '{scope_id: $scope, candidate_id: .candidate_id, expected_version: .version}' \
  /tmp/powercontext-skill-candidate.json \
  > /tmp/powercontext-skill-approve-request.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-skill-approve-request.json \
  "$POWERCONTEXT_URL/v1/artifact-candidates/approve" \
  | tee /tmp/powercontext-skill-approved.json \
  | jq .
```

Read the exact Revision:

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  '{scope_id: $scope, artifact: .result_artifact}' \
  /tmp/powercontext-skill-approved.json \
  > /tmp/powercontext-skill-get-request.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-skill-get-request.json \
  "$POWERCONTEXT_URL/v1/skill/get" \
  | tee /tmp/powercontext-skill.json \
  | jq .
```

Your application should select an exact Skill Revision through configuration or a business-owned selector, then read
it and provide it to the model. Do not let a model silently select an unknown latest head. Approval is not execution
authorization. The application still verifies:

- whether the current user permits this Skill;
- required file, network, tool, and secret permissions;
- whether instructions fit the current environment;
- whether validation actually ran and passed.

A managed Skill never enters `PreparedContext` automatically. Export to Codex or another Host is an explicit
host-local projection; see [Create and export a managed Skill](../how-to/create-and-export-skill.md).

## 21. Evolve a Skill from usage

First capture actual usage evidence:

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n --arg scope "$POWERCONTEXT_SCOPE" \
    '{
      scope_id: $scope,
      source_id: "skill-usage:validate-billing-response:1",
      content: "The validation caught a missing eligibility check. Add an explicit negative-case test.",
      metadata: {kind: "skill-usage", result: "partial"}
    }')" \
  "$POWERCONTEXT_URL/v1/sources/content" \
  | tee /tmp/powercontext-skill-usage-source.json \
  | jq .
```

Then create a replacement Candidate:

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  --slurpfile skill /tmp/powercontext-skill-approved.json \
  --slurpfile usage /tmp/powercontext-skill-usage-source.json \
  '{
    scope_id: $scope,
    origin: "usage",
    source_refs: [$usage[0].source],
    artifact_refs: [$skill[0].result_artifact],
    target: $skill[0].result_artifact,
    reason: "Add a negative-case check based on actual usage"
  }' \
  > /tmp/powercontext-skill-usage-generate-request.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-skill-usage-generate-request.json \
  "$POWERCONTEXT_URL/v1/skill/generate" \
  | jq .
```

Only Review and approval of the replacement Candidate creates the next Revision under the same Skill identity.

## 22. External Skill Registry

An external Skill is an Agent-native package already on the current Host, not a managed Skill Revision. Configure an
explicit target and restart the Server:

```bash
export POWERCONTEXT_SERVER_EXTERNAL_SKILLS='{
  "host_id": "workstation-1",
  "targets": [{
    "target_id": "codex-project",
    "agent_kind": "codex",
    "installation_scope": "project",
    "path": "/absolute/path/to/project/.agents/skills",
    "allow_managed_publish": false
  }]
}'
```

Scan and list:

```bash
curl --fail --silent --show-error \
  --request POST --header 'Content-Type: application/json' \
  --data "$(jq -n --arg scope "$POWERCONTEXT_SCOPE" '{scope_id: $scope}')" \
  "$POWERCONTEXT_URL/v1/external-skills/scan" \
  | jq .

curl --fail --silent --show-error \
  --request POST --header 'Content-Type: application/json' \
  --data "$(jq -n --arg scope "$POWERCONTEXT_SCOPE" \
    '{scope_id: $scope, include_unavailable: true}')" \
  "$POWERCONTEXT_URL/v1/external-skills/list" \
  | tee /tmp/powercontext-external-skills.json \
  | jq .
```

Resolve the first exact local package returned by `list`:

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  '{
    scope_id: $scope,
    external_skill_id: .skills[0].registration.external_skill_id,
    fingerprint: .skills[0].registration.fingerprint
  }' \
  /tmp/powercontext-external-skills.json \
  > /tmp/powercontext-external-skill-resolve.json

curl --fail --silent --show-error \
  --request POST --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-external-skill-resolve.json \
  "$POWERCONTEXT_URL/v1/external-skills/resolve" \
  | jq .
```

Status is `available` only while Agent, Host, scope, locator, content, and fingerprint match. The Server never looks
up or installs a missing package remotely.

To bring that exact snapshot into the managed lifecycle, choose `import` or `fork` and send it to Review:

```bash
jq '. + {
  mode: "fork",
  reason: "Adapt this local package for the billing API project"
}' \
  /tmp/powercontext-external-skill-resolve.json \
  > /tmp/powercontext-external-skill-import.json

curl --fail --silent --show-error \
  --request POST --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-external-skill-import.json \
  "$POWERCONTEXT_URL/v1/external-skills/import" \
  | jq .
```

Import captures an exact local snapshot and invokes the generation model to create a pending managed Skill Candidate.
It does not approve, install, execute, or overwrite the original package.

## 23. Scoped Stats

```bash
curl --fail --silent --show-error \
  --get \
  --data-urlencode "scope_id=$POWERCONTEXT_SCOPE" \
  --data-urlencode 'period=7d' \
  "$POWERCONTEXT_URL/v1/stats" \
  | jq .
```

`period` is `today`, `7d`, or `30d`. The response reports current inventory, model usage, and recall token estimates
with `Cache-Control: no-store`. Statistics must not expose prompt text, Memory bodies, tokens, URLs, or internal
exception content.

## 24. Handoff Report APIs

Report is an operational projection over Handoff. To report a scope with committed Handoff, no Project is required:

```bash
curl --fail --silent --show-error \
  --request POST --header 'Content-Type: application/json' \
  --data '{}' \
  "$POWERCONTEXT_URL/v1/handoff-reports/scopes/list-known" \
  | jq .

curl --fail --silent --show-error \
  --request POST --header 'Content-Type: application/json' \
  --data "$(jq -n --arg scope "$POWERCONTEXT_SCOPE" \
    '{scope_id: $scope, locale: "en", format: "json", include_evidence_checks: true}')" \
  "$POWERCONTEXT_URL/v1/handoff-reports/get" \
  | jq .
```

The complete Project/Workstream catalog flow is:

| Order | Operation | Purpose |
| --- | --- | --- |
| 1 | `POST /v1/handoff-reports/projects/create` | Create a Project; keep `project_id` and `version` |
| 2 | `POST /v1/handoff-reports/projects/list` | Page through Projects |
| 3 | `POST /v1/handoff-reports/projects/get` | Read one Project by exact ID |
| 4 | `POST /v1/handoff-reports/projects/update` | Send the complete `ProjectDescriptor + expected_version` |
| 5 | `POST /v1/handoff-reports/workstreams/register` | Associate a stable `scope_id` with the Project |
| 6 | `POST /v1/handoff-reports/workstreams/list` | Page through the Project's Workstreams |
| 7 | `POST /v1/handoff-reports/workstreams/update` | Send the complete `WorkstreamDescriptor + expected_version` |
| 8 | `POST /v1/handoff-reports/activities/record` | Idempotently record one observation by `source_event_id` |
| 9 | `POST /v1/handoff-reports/activities/list` | Page through a frozen Activity cursor range |
| 10 | `POST /v1/handoff-reports/activities/purge` | Remove Report-owned rows before `observed_before` |
| 11 | `POST /v1/handoff-reports/workspace-bindings/attach` | Confirm a Workspace-to-Project binding with version CAS |
| 12 | `POST /v1/handoff-reports/workspace-bindings/get` | Read a binding by Workspace instance ID |
| 13 | `POST /v1/handoff-reports/workspace-bindings/detach` | Detach the exact current binding version |

Create a Project:

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data '{
    "project_key": "billing-api",
    "title": "Billing API",
    "description": "Billing API project for the self-built AI engineering assistant",
    "default_locale": "en",
    "timezone": "UTC"
  }' \
  "$POWERCONTEXT_URL/v1/handoff-reports/projects/create" \
  | tee /tmp/powercontext-report-project.json \
  | jq .
```

List, get, and update that Project:

```bash
curl --fail --silent --show-error \
  --request POST --header 'Content-Type: application/json' \
  --data '{"limit": 50, "include_archived": false}' \
  "$POWERCONTEXT_URL/v1/handoff-reports/projects/list" \
  | jq .

jq '{project_id: .project_id}' \
  /tmp/powercontext-report-project.json \
  > /tmp/powercontext-report-project-get.json

curl --fail --silent --show-error \
  --request POST --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-report-project-get.json \
  "$POWERCONTEXT_URL/v1/handoff-reports/projects/get" \
  | jq .

jq '{
  project: (. + {description: "Billing API project and its AI-assistant workstreams"}),
  expected_version: .version
}' \
  /tmp/powercontext-report-project.json \
  > /tmp/powercontext-report-project-update.json

curl --fail --silent --show-error \
  --request POST --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-report-project-update.json \
  "$POWERCONTEXT_URL/v1/handoff-reports/projects/update" \
  | tee /tmp/powercontext-report-project.json \
  | jq .
```

Register a Workstream:

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  '{
    project_id: .project_id,
    scope_id: $scope,
    key: "refund-validation",
    title: "Refund eligibility validation",
    kind: "feature",
    catalog_state: "included",
    external_refs: [],
    labels: ["billing", "api"]
  }' \
  /tmp/powercontext-report-project.json \
  > /tmp/powercontext-report-workstream-request.json

curl --fail --silent --show-error \
  --request POST --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-report-workstream-request.json \
  "$POWERCONTEXT_URL/v1/handoff-reports/workstreams/register" \
  | tee /tmp/powercontext-report-workstream.json \
  | jq .
```

List and update the Workstream with the exact current version:

```bash
jq '{project_id: .project_id, limit: 50, include_archived: false}' \
  /tmp/powercontext-report-project.json \
  > /tmp/powercontext-report-workstreams-list.json

curl --fail --silent --show-error \
  --request POST --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-report-workstreams-list.json \
  "$POWERCONTEXT_URL/v1/handoff-reports/workstreams/list" \
  | jq .

jq '{
  workstream: (. + {labels: ((.labels + ["reviewed"]) | unique)}),
  expected_version: .version
}' \
  /tmp/powercontext-report-workstream.json \
  > /tmp/powercontext-report-workstream-update.json

curl --fail --silent --show-error \
  --request POST --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-report-workstream-update.json \
  "$POWERCONTEXT_URL/v1/handoff-reports/workstreams/update" \
  | tee /tmp/powercontext-report-workstream.json \
  | jq .
```

Record and list an untrusted operational observation. Reusing `source_event_id` with the same payload is idempotent;
reusing it with different content returns a conflict:

```bash
jq -n \
  --arg project_id "$(jq -r '.project_id' /tmp/powercontext-report-project.json)" \
  --arg scope "$POWERCONTEXT_SCOPE" \
  '{
    project_id: $project_id,
    scope_id: $scope,
    source: "coding_session",
    source_event_id: "api-tutorial-session-1",
    time_basis: "host_observed",
    title: "API tutorial completed",
    summary: "Verified the billing-assistant context and Handoff flow",
    evidence_refs: []
  }' \
  > /tmp/powercontext-report-activity.json

curl --fail --silent --show-error \
  --request POST --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-report-activity.json \
  "$POWERCONTEXT_URL/v1/handoff-reports/activities/record" \
  | jq .

jq '{project_id: .project_id, after_cursor: 0, limit: 50}' \
  /tmp/powercontext-report-project.json \
  > /tmp/powercontext-report-activities-list.json

curl --fail --silent --show-error \
  --request POST --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-report-activities-list.json \
  "$POWERCONTEXT_URL/v1/handoff-reports/activities/list" \
  | jq .
```

`purge` is an administrative retention operation. The following request shape uses a deliberately old boundary;
inspect it before running it against a non-disposable deployment:

```bash
jq -n \
  --arg project_id "$(jq -r '.project_id' /tmp/powercontext-report-project.json)" \
  '{project_id: $project_id, observed_before: "2000-01-01T00:00:00Z"}' \
  > /tmp/powercontext-report-activities-purge.json

curl --fail --silent --show-error \
  --request POST --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-report-activities-purge.json \
  "$POWERCONTEXT_URL/v1/handoff-reports/activities/purge" \
  | jq .
```

Finally, attach, read, and optionally detach a Workspace binding. First attach uses `expected_version: null`; later
mutations use the returned exact version:

```bash
jq -n \
  --arg project_id "$(jq -r '.project_id' /tmp/powercontext-report-project.json)" \
  '{
    workspace_instance_id: "billing-api-workspace-1",
    project_id: $project_id,
    repository_ref: {
      provider: "local",
      repository_id: null,
      normalized_remote: null,
      subpath: null
    },
    expected_version: null
  }' \
  > /tmp/powercontext-report-workspace-attach.json

curl --fail --silent --show-error \
  --request POST --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-report-workspace-attach.json \
  "$POWERCONTEXT_URL/v1/handoff-reports/workspace-bindings/attach" \
  | tee /tmp/powercontext-report-workspace.json \
  | jq .

curl --fail --silent --show-error \
  --request POST --header 'Content-Type: application/json' \
  --data '{"workspace_instance_id": "billing-api-workspace-1"}' \
  "$POWERCONTEXT_URL/v1/handoff-reports/workspace-bindings/get" \
  | jq .

jq '{workspace_instance_id: .workspace_instance_id, expected_version: .version}' \
  /tmp/powercontext-report-workspace.json \
  > /tmp/powercontext-report-workspace-detach.json

# Run only when the binding should actually be detached.
curl --fail --silent --show-error \
  --request POST --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-report-workspace-detach.json \
  "$POWERCONTEXT_URL/v1/handoff-reports/workspace-bindings/detach" \
  | jq .
```

Report update, Activity purge, and workspace detach are mutations and should require administrative access. When
Handoff Report is disabled, this route group is not registered.

## 25. Errors, concurrency, and retries

Stable error envelope:

```json
{
  "error": {
    "code": "invalid_request",
    "message": "The request violates the API contract.",
    "details": {}
  }
}
```

| Status | Common cause | Handling |
| --- | --- | --- |
| `401` | Missing or invalid Bearer token | Do not retry; fix credentials |
| `404` | Exact Source, Artifact, Candidate, or binding is absent | Refresh list/get; never guess IDs |
| `409` | Source conflict, stale citation/version, or advanced target head | Read current state and ask for a new decision |
| `413` | Report output exceeds a limit | Narrow the selection or output |
| `422` | Invalid type, required field, length, or provenance shape | Fix the client; do not retry blindly |
| `503` | Runtime capability or dependency unavailable | Degrade reads; fail writes explicitly |
| `500` | Internal Server error | Record request ID and use bounded backoff |

Retry rules:

- health, capabilities, search, list, get, and prepare may use bounded retries;
- Source capture with a stable `source_id` can replay identical content safely;
- Candidate Review, Memory mutation, and Report update must refresh version or citation first;
- never retry an uncertain non-idempotent write indefinitely;
- log only operation, status, stable error code, latency, and request ID—not user content or credentials.

## 26. Production authorization model

Separate at least three caller identities:

| Identity | Typical permissions |
| --- | --- |
| AI request service | prepare, search, exact get, and optionally submit proposals |
| Evidence writer | capture Source, remember, and Work/Handoff/Outcome writes |
| Reviewer/Admin | Candidate approval/rejection/revision, Report update/purge, and Skill publication |

Do not grant every permission to one model identity merely because the endpoints share one Server. `scope_id` does not
replace an ACL.

## 27. Production checklist

- [ ] Run the Server with persistent storage, backup, TLS, health checks, and monitoring.
- [ ] Map caller identity to allowed scopes at the Gateway.
- [ ] The model never receives Bearer tokens, arbitrary scopes, or Reviewer/Admin authority.
- [ ] Source capture has consent, sensitive-field filtering, and retention controls.
- [ ] Call `/v1/context/prepare` no more than once per model request.
- [ ] Keep PreparedContext read-only and untrusted; current instructions and live validation win.
- [ ] Memory writes are short, explicit, durable information with authorization.
- [ ] An independent reviewer checks exact Candidate version and lineage.
- [ ] Approved Skills still require separate execution authorization and environment validation.
- [ ] Every mutation preserves an exact citation, ArtifactRef, or expected version.
- [ ] Clients record `X-PowerContext-Request-ID` without recording content or credentials.
- [ ] Generated clients pin and verify the `/openapi.json` contract version.
- [ ] Acceptance includes persistence checks after restarting the Server.

You have now completed one continuous HTTP workflow across PowerContext's data, governance, and operational planes.
Use the [HTTP API reference](../reference/http-api.md) and the running process's `/openapi.json` for an exact field,
enum, limit, or complete response schema.
