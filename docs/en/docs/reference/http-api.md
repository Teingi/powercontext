---
title: HTTP API
description: Call the PowerContext Server over HTTP and find the complete OpenAPI contract.
---

# HTTP API

The HTTP API is the language-neutral interface to a running PowerContext Server. The default base URL is
`http://127.0.0.1:8000`.

If you are integrating PowerContext into your own AI application rather than looking up one field, start with the
[HTTP API lifecycle tutorial](../tutorials/api-quickstart.md). This page remains the path, contract, and
error-semantics reference.

## Discover the contract

With a local unauthenticated Server running, open:

- `/docs` for interactive Swagger UI;
- `/redoc` for ReDoc;
- `/openapi.json` for the contract served by that process.

The checked-in source of truth is
[`openapi/powercontext.yaml`](https://github.com/oceanbase/powercontext/blob/master/openapi/powercontext.yaml).
Use it when generating a client or reviewing every request and response field. When Server authentication is enabled,
the three discovery routes require the same bearer token as other protected routes. A browser address bar cannot add
that header: use a trusted proxy or browser setup that injects it, or download `/openapi.json` with an authenticated
command after setting the variables below. Never put the token in the URL.

## Authenticate requests

Authentication is disabled for the default loopback-only installation. When the operator enables it, include this
header on API and MCP requests:

```http
Authorization: Bearer <token>
```

The examples below use an optional shell variable:

```bash
POWERCONTEXT_URL=http://127.0.0.1:8000
POWERCONTEXT_AUTH_HEADER="Authorization: Bearer ${POWERCONTEXT_CLIENT_API_TOKEN}"
```

Omit `--header "$POWERCONTEXT_AUTH_HEADER"` when authentication is disabled. The `/health/live` and
`/health/ready` endpoints are always public. See [Deploy the Server](../how-to/deploy-server.md) before allowing remote
access.

For an authenticated Server, download the exact contract served by that process with:

```bash
curl --fail \
  --header "$POWERCONTEXT_AUTH_HEADER" \
  --output powercontext-openapi.json \
  "$POWERCONTEXT_URL/openapi.json"
```

## Store and search one Memory

Choose a stable `scope_id` for the project or tenant. Reuse it across sessions; a session ID is not a durable project
identity.

Store one already-curated Memory entry:

```bash
curl --fail \
  --request POST \
  --header 'Content-Type: application/json' \
  --header "$POWERCONTEXT_AUTH_HEADER" \
  --data '{
    "scope_id": "project:example",
    "kind": "decision",
    "text": "Keep the public API asynchronous."
  }' \
  "$POWERCONTEXT_URL/v1/memory/remember"
```

The response contains an exact citation. Keep that citation when a later request must revise, retire, or read that
specific immutable revision.

Search active entries in the same scope:

```bash
curl --fail \
  --request POST \
  --header 'Content-Type: application/json' \
  --header "$POWERCONTEXT_AUTH_HEADER" \
  --data '{
    "scope_id": "project:example",
    "query": "public API",
    "limit": 5
  }' \
  "$POWERCONTEXT_URL/v1/memory/search"
```

## Grant one exact Handoff to a receiver

`scope_id` never grants access by itself. An administrator delegates one exact committed Handoff by creating a
Binding for the receiver's authenticated Principal:

```bash
curl --fail \
  --request POST \
  --header 'Content-Type: application/json' \
  --header "$POWERCONTEXT_AUTH_HEADER" \
  --data '{
    "subject": {"type": "user", "issuer": "https://id.example", "id": "user-b"},
    "resource": {
      "type": "artifact",
      "scope_id": "project:example",
      "reference": {"family": "handoff", "artifact_id": "handoff-42", "revision": 3},
      "selector": null
    },
    "role": "handoff.receiver",
    "idempotency_key": "handoff-42-r3-to-user-b"
  }' \
  "$POWERCONTEXT_URL/v1/access/bindings/create"
```

The receiver can read evidence and acknowledge only that Revision. It cannot use latest-Handoff discovery, read
another Handoff, or access Memory in the parent scope unless a separate scope role allows it. Use `/v1/access/me` to
verify which Principal the deployment established, `/v1/access/check` for one decision, and
`/v1/access/resources/list` for a non-discovering list of already visible resources. Creation is idempotent per
grantor and key; revocation uses `binding_id` plus `expected_version`. Relationship and decision events are available
to Server administrators through `/v1/access/audit/list`.

The Access wire contract has only three Resource Kinds: `server`, `scope`, and `artifact`. An Artifact `reference`
must identify one exact Revision. Memory also requires a complete `memory_entry` selector containing `entry_id` and
`entry_version_id`. Unknown Families, `prompt` when no Prompt lifecycle is implemented, mismatched selectors or roles,
and `latest` never create a Binding. `/v1/access/me` reports the current mode, Provider capabilities, and each Artifact
Family's enabled state.

Reading a managed Skill and publishing it are separate permissions. Both `/v1/skills/publication-targets/list` and
`/v1/skills/publish` require `artifact.read` plus `skill.publish` on the same exact Skill Revision. Requests submit only
an opaque `target_id`; public responses and errors omit host paths, Agent homes, credentials, and locators. Detailed
Dashboard publication status is separately protected by `server.observe`.

The built-in static token represents one local administrator and cannot model different A/B users. A real multi-user
deployment must authenticate each caller to a different Principal and inject an Authorization Provider. HTTP and MCP
use the same policy enforcement point; MCP tool visibility is not permission.

## Find an operation

| Area | Main paths | Purpose |
| --- | --- | --- |
| Health and capabilities | `/health/*`, `/v1/capabilities` | Probe the deployment and discover enabled runtime behavior |
| Access Control | `/v1/access/*` | Inspect identity, check decisions, and administer roles, Bindings, and audit events |
| Source and context | `/v1/sources/content`, `/v1/context/prepare` | Capture evidence and prepare bounded context |
| Work continuity | `/v1/work/*` | Create work contracts, prepare or acknowledge Handoffs, and record outcomes |
| Low-level Handoff | `/v1/handoff/*` | Activate, prepare, finalize, commit, or continue a Handoff |
| Memory | `/v1/memory/*` | Flush, remember, search, list, get, revise, retire, and inspect changes |
| Experience and Skill | `/v1/experience/*`, `/v1/skill/*`, `/v1/skills/*` | Propose, generate, read Artifact revisions, and publish managed Skills under dual authorization |
| Review | `/v1/artifact-candidates/*` | List, inspect, revise, approve, or reject pending Candidates |
| External Skills | `/v1/external-skills/*` | Scan configured targets and resolve or import packages |
| Handoff Reports | `/v1/handoff-reports/*` | Manage Projects, Workstreams, activities, reports, and workspace bindings |
| Statistics | `/v1/stats` | Read scoped usage statistics |

The OpenAPI contract defines the complete path list, schemas, limits, and status codes. The higher-level workflow and
Python examples are in [Interfaces](interfaces.md).

## Handle errors and concurrent changes

Errors use one JSON envelope:

```json
{
  "error": {
    "code": "invalid_request",
    "message": "The request violates the API contract.",
    "details": {}
  }
}
```

Common statuses are:

| Status | Meaning |
| --- | --- |
| `401` | The Server requires a valid bearer token |
| `403` | The authenticated Principal is not authorized for the requested action and resource |
| `404` | The requested immutable value does not exist |
| `409` | The request conflicts with current immutable state or an expected version |
| `413` | A selected Handoff Report exceeds its output limit |
| `422` | The JSON body violates the transport or application contract |
| `503` | A required Runtime binding or dependency is unavailable |
| `500` | The Server failed without exposing internal details |

Every response includes `X-PowerContext-Request-ID`; record it when diagnosing a failed call. Preserve exact citations
for Memory revision and retirement. Candidate review writes require the current `expected_version`; after a `409`, read
the Candidate again before deciding whether to retry.
