- Proposal Name: `source_artifact_rest_api`
- Start Date: 2026-09-01
- RFC PR: [oceanbase/powercontext#0000](https://github.com/oceanbase/powercontext/pull/0000)

# Summary

This RFC adds independent, stable HTTP APIs for three existing PowerContext concepts:

- Source: create, get, list, and search;
- Artifact: create, get, list, search, replace, and delete;
- Scope: list every Scope observable by the caller.

The API reuses the existing Source, Artifact, immutable Artifact Revision, and Scope semantics. It does not add an
umbrella object, a union reference, a shared selector, a type-registration endpoint, or a cross-kind list/search.
Adding an Artifact family does not add another set of base paths or generated Client methods.

Writing and generation remain separate commit boundaries. `POST /v1/sources` durably creates a Source and returns
that Source. A caller that needs immediate Memory extraction composes it with the existing
`POST /v1/memory/flush` operation.

The wire contract follows these rules:

- plural noun paths carry object identity while HTTP methods carry the operation;
- `GET` reads, lists, and searches; `POST` creates; `PUT` fully replaces an Artifact head; `DELETE` deletes it;
- Artifact revisions remain immutable: replacing a head commits the next revision instead of overwriting history;
- list and search responses use typed items and `next_cursor`.

# Motivation

PowerContext currently exposes domain commands such as Source capture, Memory flush, Experience and Skill
generation, Candidate review, and the Handoff workflow. Those commands preserve the domain lifecycle, but callers
also need predictable base access to already durable Sources and committed Artifacts.

The required outcomes are:

- create and read a Source in one Scope;
- list and search Sources by Scope and Source type;
- create, read, list, search, revise, and delete Artifacts by Scope and family where the family permits it;
- add future Artifact families without adding family-specific base endpoints;
- discover observable `scope_id` values before querying Sources and Artifacts;
- let clients explicitly compose Source creation with generation commands instead of making writes invoke models.

# Goals

- Model Source and Artifact directly without introducing a shared parent concept.
- Preserve Source identity without a revision and Artifact identity with an exact revision.
- Keep a fixed base API surface as Artifact families are added.
- Preserve existing domain commands and Candidate Review gates.
- Define request metadata, responses, pagination, concurrency, and errors for every base operation.
- Keep `openapi/powercontext.yaml` as the single source of truth for the HTTP contract.

# Non-goals

- Write-time generation parameters, server-side combined writes, or generation jobs.
- Cross-Source-type, cross-Artifact-family, or Source-and-Artifact combined list/search.
- Reclassifying Candidates, Memory entries, or Handoff drafts as Artifacts.
- Replacing Memory, Experience, Skill, Handoff, or Candidate commands.
- Cross-Scope sharing, ACL/RBAC, restore, physical purge, or bulk mutations.
- Letting a family bypass an existing review or lifecycle rule.

# Guide-level explanation

## Source, Artifact, and Scope

A Source is durable evidence with a stable `SourceReference`:

```json
{
  "name": "content",
  "source_id": "refund-rule-001"
}
```

`name` is the stable Source type used by the existing OpenAPI contract. Requests use the field name
`source_type`; responses continue to use `SourceReference{name, source_id}`. A Source has no revision. This RFC
therefore does not add Source replace or delete operations. Corrections are new Sources so evidence already cited
by Artifact lineage is never silently changed.

An Artifact is a committed, evolvable output with an exact `ArtifactReference`:

```json
{
  "family": "company.example.decision",
  "artifact_id": "dec_01J...",
  "revision": 2
}
```

Create commits revision 1. Replace validates the current head and commits the next revision. Exact historical
revision URIs remain immutable.

`scope_id` is the ownership, isolation, and query boundary for both concepts. It is neither a Source nor an
Artifact. `GET /v1/scopes` reads the authoritative Scope application layer and returns only Scopes observable by
the caller. Scope creation, metadata, organization parents, context references, and bindings remain governed by
the Scope organization design.

## Immediate Memory extraction

Source creation does not contain a generation option. A caller that wants to wait for Memory extraction performs
two explicit operations:

```text
POST /v1/sources       -> Source.position
POST /v1/memory/flush  -> Memory Revision and Changes
```

Memory flush processes one bounded pending Source window. It is neither a single-Source operation nor a full
historical rebuild. The caller knows the newly created Source has been crossed when `current_cursor` is greater
than or equal to the Source `position`. A flush failure does not roll back the durable Source and can be retried.

# Reference-level explanation

## HTTP and naming conventions

Capability names such as create, get, list, search, replace, and delete are useful SDK names. They are not added as
path suffixes. The mapping is:

| Capability | HTTP representation | Method | operationId |
| --- | --- | --- | --- |
| Create | submit to a collection | `POST` | `create_source`, `create_artifact` |
| Get | read a named object or exact revision | `GET` | `get_source`, `get_artifact`, `get_artifact_revision` |
| List | read a collection | `GET` | `search_sources` in list mode, `list_artifacts`, `list_scopes` |
| Search | read a result collection | `GET` | `search_sources`, `search_artifacts` |
| Replace | fully replace the Artifact head | `PUT` | `replace_artifact` |
| Delete | delete the current visible Artifact head | `DELETE` | `delete_artifact` |

The API additionally requires:

- `scope_id` is a query or body field rather than a path segment because it may contain `:` and `/`;
- `source_type` and `family` are query or body fields, so a new type or family does not add a path;
- fields use the existing snake_case convention;
- all path segments are RFC 3986 encoded and decoded exactly once;
- `PUT` accepts only a complete replacement; partial updates require a future `PATCH` contract;
- Artifact replace and delete require the current `ETag` in `If-Match`.

## Common response models

### SourceRecord

```json
{
  "scope_id": "git:github.com/acme/payments",
  "source_ref": {
    "name": "content",
    "source_id": "refund-rule-001"
  },
  "content": "Refunds require manual review.",
  "metadata": {
    "title": "Refund constraint",
    "media_type": "text/plain"
  },
  "created_at": "2026-09-01T04:00:00Z",
  "position": 42,
  "content_digest": "sha256:0000000000000000000000000000000000000000000000000000000000000000"
}
```

`position` is the Source journal position. `content_digest` is the digest of canonical durable content. Legacy
Sources created before the timestamp projection exists may return `created_at: null` without changing identity.

### ArtifactRevision

```json
{
  "scope_id": "git:github.com/acme/payments",
  "artifact_ref": {
    "family": "company.example.decision",
    "artifact_id": "dec_01J...",
    "revision": 2
  },
  "schema_version": 1,
  "metadata": {
    "title": "Refund manual-review constraint"
  },
  "content": {
    "decision": "Refunds require manual review"
  },
  "source_refs": [
    {
      "name": "content",
      "source_id": "refund-rule-001"
    }
  ],
  "artifact_refs": [],
  "created_at": "2026-09-01T04:30:00Z",
  "content_digest": "sha256:0000000000000000000000000000000000000000000000000000000000000000"
}
```

The head response includes the current revision as a strong ETag:

```http
ETag: "revision:2"
```

Replace and delete send that value back:

```http
If-Match: "revision:2"
```

Missing `If-Match` returns `428 Precondition Required`; a stale ETag returns `412 Precondition Failed`. No second
generic version field is added because the Artifact revision is already the concurrency version.

## Source API

Each request addresses one `scope_id` and one `source_type`.

| Function | HTTP API | operationId | Request and metadata | Response | Example |
| --- | --- | --- | --- | --- | --- |
| Create Source | `POST /v1/sources` | `create_source` | Body: required `scope_id`, `source_type`, `source_id`, `content`; optional `metadata`. `source_id` is the caller-stable idempotent identity | `201 SourceRecord`; `Location` identifies the Source | `POST /v1/sources` with `{"scope_id":"git:github.com/acme/payments","source_type":"content","source_id":"refund-rule-001","content":"Refunds require manual review","metadata":{"media_type":"text/plain"}}` |
| Get Source | `GET /v1/sources/{source_id}` | `get_source` | Query: required `scope_id`, `source_type` | `200 SourceRecord`; absent or invisible is `404` | `GET /v1/sources/refund-rule-001?scope_id=git%3Agithub.com%2Facme%2Fpayments&source_type=content` |
| List Sources | `GET /v1/sources` | `search_sources` | Query: required `scope_id`, `source_type`; omitted `type` or `type=list`; optional `limit`, `cursor`; no `q` or `mode` | `200 SourcePage`; `query` and `mode` are null | `GET /v1/sources?scope_id=...&source_type=content&type=list&limit=50` |
| Search Sources | `GET /v1/sources` | `search_sources` | Query: required `scope_id`, `source_type`, `type=search`, nonblank `q`; optional `mode`, `limit`, `cursor` | `200 SourcePage`; reports actual mode and optional score/snippets | `GET /v1/sources?scope_id=...&source_type=content&type=search&q=manual%20review&mode=auto` |

OpenAPI can define only one operation for one method and path. `GET /v1/sources` therefore has the single
operationId `search_sources`:

- omitted `type` or `type=list` performs deterministic listing;
- `type=search` requires nonblank `q` and performs search;
- `type` selects behavior while `source_type` identifies the Source type;
- an unknown `type`, list request with `q`/`mode`, or search request without `q` returns `422 invalid_request`;
- a cursor is bound to the caller, Scope, Source type, operation type, query, mode, filters, and ordering.

### Source create compatibility

The new create operation returns the created representation:

```http
POST /v1/sources
Content-Type: application/json
```

```json
{
  "scope_id": "git:github.com/acme/payments",
  "source_type": "content",
  "source_id": "refund-rule-001",
  "content": "Refunds require manual review.",
  "metadata": {"media_type": "text/plain"}
}
```

```http
HTTP/1.1 201 Created
Location: /v1/sources/refund-rule-001?scope_id=git%3Agithub.com%2Facme%2Fpayments&source_type=content
```

Existing `POST /v1/sources/content` remains a strongly typed compatibility facade and keeps its `202 Accepted`
response. Both operations delegate to the same durable write. Replaying the same identity and canonical payload is
an idempotent success; reusing the identity for different content returns `409 idempotency_conflict`.

## Artifact API

The fixed paths apply to future families. A family registers its content schema and supported actions in the
assembled Runtime instead of adding another set of endpoints.

| Function | HTTP API | operationId | Request and metadata | Response | Example |
| --- | --- | --- | --- | --- | --- |
| Create Artifact | `POST /v1/artifacts` | `create_artifact` | Body: required `scope_id`, `family`, `content`, `schema_version`; optional `artifact_id`, `metadata`, `source_refs`, `artifact_refs` | `201 ArtifactRevision` plus `Location` and `ETag`; commits revision 1 | `POST /v1/artifacts` with family-specific JSON content |
| Get current Artifact | `GET /v1/artifacts/{artifact_id}` | `get_artifact` | Query: required `scope_id`, `family` | `200 ArtifactRevision` plus `ETag` | `GET /v1/artifacts/dec_01J...?scope_id=...&family=company.example.decision` |
| Get exact revision | `GET /v1/artifacts/{artifact_id}/revisions/{revision}` | `get_artifact_revision` | Query: required `scope_id`, `family`; path carries exact revision | `200 ArtifactRevision` | `GET /v1/artifacts/dec_01J.../revisions/2?scope_id=...&family=company.example.decision` |
| List Artifacts | `GET /v1/artifacts` | `list_artifacts` | Query: required `scope_id`, `family`; optional `limit`, `cursor`; only current visible heads | `200 ArtifactPage` | `GET /v1/artifacts?scope_id=...&family=experience&limit=50` |
| Search Artifacts | `GET /v1/artifact-search-results` | `search_artifacts` | Query: required `scope_id`, `family`, nonblank `q`; optional `mode`, `limit`, `cursor`; searches visible heads | `200 ArtifactSearchResultPage` | `GET /v1/artifact-search-results?scope_id=...&family=experience&q=manual%20review` |
| Replace Artifact | `PUT /v1/artifacts/{artifact_id}` | `replace_artifact` | Query/body identify `scope_id` and `family`; required `If-Match`; body is a complete replacement | `200 ArtifactRevision` plus new `ETag`; stale ETag is `412` | `PUT /v1/artifacts/dec_01J...?scope_id=...&family=company.example.decision` |
| Delete Artifact | `DELETE /v1/artifacts/{artifact_id}` | `delete_artifact` | Query: required `scope_id`, `family`; required `If-Match` | `200 ArtifactDeletionStatus`; unsupported family is `405` | `DELETE /v1/artifacts/dec_01J...?scope_id=...&family=company.example.decision` |

### Create and replace examples

```http
POST /v1/artifacts
Content-Type: application/json
```

```json
{
  "scope_id": "git:github.com/acme/payments",
  "family": "company.example.decision",
  "artifact_id": "dec_01J...",
  "schema_version": 1,
  "metadata": {"title": "Refund manual-review constraint"},
  "content": {"decision": "Refunds require manual review"},
  "source_refs": [{"name": "content", "source_id": "refund-rule-001"}],
  "artifact_refs": []
}
```

```http
HTTP/1.1 201 Created
Location: /v1/artifacts/dec_01J...?scope_id=git%3Agithub.com%2Facme%2Fpayments&family=company.example.decision
ETag: "revision:1"
```

Replace sends a complete representation and the current ETag:

```http
PUT /v1/artifacts/dec_01J...?scope_id=git%3Agithub.com%2Facme%2Fpayments&family=company.example.decision
Content-Type: application/json
If-Match: "revision:1"
```

```json
{
  "scope_id": "git:github.com/acme/payments",
  "family": "company.example.decision",
  "schema_version": 1,
  "metadata": {"title": "Refund manual-review constraint"},
  "content": {
    "decision": "Refunds require manual review",
    "rationale": "Satisfy funds-safety requirements"
  },
  "source_refs": [{"name": "content", "source_id": "refund-rule-001"}],
  "artifact_refs": []
}
```

Success returns revision 2, `200 OK`, and `ETag: "revision:2"`. If revision 1 is no longer the head, the operation
returns `412 revision_conflict` with both the provided and current ETags. The Runtime does not merge, retain omitted
fields, or overwrite revision 1.

### Delete semantics

Delete records a lifecycle tombstone and does not physically erase revisions:

- normal head get, list, search, and context preparation no longer return the deleted head;
- exact historical lineage remains verifiable;
- retrying delete with the same revision returns the same deletion state;
- restore and purge are not provided by this RFC;
- `If-Match` prevents deletion of a concurrently revised head;
- a family must explicitly support delete, otherwise the operation returns `405 operation_not_supported`.

```http
DELETE /v1/artifacts/dec_01J...?scope_id=git%3Agithub.com%2Facme%2Fpayments&family=company.example.decision
If-Match: "revision:2"
```

```json
{
  "artifact_ref": {
    "family": "company.example.decision",
    "artifact_id": "dec_01J...",
    "revision": 2
  },
  "status": "deleted",
  "deleted_at": "2026-09-01T05:00:00Z"
}
```

## Scope API

| Function | HTTP API | operationId | Request and metadata | Response | Example |
| --- | --- | --- | --- | --- | --- |
| List observable Scopes | `GET /v1/scopes` | `list_scopes` | Optional query `limit`, `cursor`; authorization comes from the request identity | `200 ScopePage{items,next_cursor}` | `GET /v1/scopes?limit=50` |

A Scope summary can include identity metadata and activity summaries:

```json
{
  "items": [
    {
      "scope_id": "scp_01K...",
      "title": "Payments",
      "summary": "Payment and refund rules",
      "parent_scope_id": null,
      "version": 3,
      "source_types": ["content"],
      "artifact_families": ["memory", "experience", "company.example.decision"],
      "source_count": 120,
      "artifact_count": 8
    }
  ],
  "next_cursor": null
}
```

“All” means every durable Scope observable by the caller, never an authorization bypass. Authorization filtering
happens before pagination and counts. Source and Artifact activity may be a projection, but it does not establish
Scope identity. An empty Scope remains visible when it exists in the authoritative Scope directory. Reading a
specific invisible Scope should generally return `404` to avoid enumeration.

## Pagination and search

Collection responses use a stable `next_cursor`. A cursor is bound to the caller identity, authorization context,
Scope, Source type or Artifact family, query type, query text, filters, ordering, and actual search mode. A cursor
cannot be reused after any of those values changes.

Source list and search share `SourcePage`:

```json
{
  "query": null,
  "mode": null,
  "items": [],
  "next_cursor": null
}
```

Artifact search has an explicit result collection:

```json
{
  "query": "refund manual review",
  "mode": "keyword",
  "hits": [],
  "next_cursor": null
}
```

## Family capability and lifecycle boundaries

A fixed Artifact path does not imply that every family accepts direct writes:

| Family kind | Create | Get/List/Search | Replace | Delete |
| --- | --- | --- | --- | --- |
| Direct family | commits revision 1 | reads committed revisions and heads | commits next revision | available only when declared |
| Review family, including Experience and managed Skill | `405`; use propose/review | approved Artifacts only | `405`; use Candidate revision and review | disabled by default |
| Memory | use Memory commands | Artifact-level reads do not replace Memory entry APIs | disabled; entry revision keeps its own CAS | disabled |
| Handoff | use prepare/finalize/commit | committed Handoffs only | disabled | disabled |

Candidate is not an Artifact. Pending and rejected Candidates never appear in Artifact list/search. Only an approved
Candidate whose result was committed can be read as an Artifact.

`/v1/capabilities` should report the actions supported by each Source type and Artifact family. Callers must not
assume every assembled deployment supports every mutation.

## Error model

The operations reuse the existing error envelope and stabilize these codes:

| HTTP status | code | Meaning |
| --- | --- | --- |
| `400/422` | `invalid_request` | invalid fields, query/cursor combination, or metadata |
| `401` | `unauthorized` | authentication is required |
| `403` | `forbidden` | authenticated caller lacks mutation authority |
| `404` | `source_not_found`, `artifact_not_found` | absent or invisible object |
| `405` | `operation_not_supported` | action is unsupported or would bypass review |
| `409` | `idempotency_conflict` | stable identity was reused for different canonical content |
| `412` | `revision_conflict` | `If-Match` does not identify the current Artifact head |
| `428` | `precondition_required` | replace/delete omitted `If-Match` |
| `422` | `schema_validation_failed` | content does not match the registered Source/family schema |
| `503` | `capability_unavailable` | a declared backend is temporarily unavailable |

## Existing API overlap and compatibility

| New design | Existing API | Relationship | Compatibility rule |
| --- | --- | --- | --- |
| `POST /v1/sources` | `POST /v1/sources/content` | same durable Source write, different HTTP response | share one application service; new endpoint returns `201 SourceRecord`, old endpoint remains `202 CaptureContentSourceResponse` |
| Source get/list/search | none | new read surface | read the same Source journal and projection |
| Artifact head/exact get | `/v1/experience/get`, `/v1/skill/get`, and other typed reads | overlapping read | use the same committed revisions; typed responses remain available |
| Artifact list/search | Memory entry list/search | different identity level | Artifact endpoints operate on heads; Memory endpoints retain entry identity, citation, and ranking |
| Artifact replace | Candidate revise and Memory entry revise | different lifecycle | generic replace never bypasses review or pretends an entry update is a whole Artifact replacement |
| Artifact delete | Memory retire and other family lifecycles | different lifecycle | only a family that explicitly opts in accepts generic delete |
| `GET /v1/scopes` | `/v1/handoff-reports/scopes/list-known` | the report route is a Handoff subset | retain the old route and filter the authorized Scope set to committed Handoffs |
| Source create followed by Memory flush | `/v1/memory/flush` | reuses the existing command | no combined server parameter or response is added |

No current domain endpoint is removed or deprecated by this RFC. Parity tests ensure overlapping entries resolve to
the same durable Source or Artifact revision, digest, lineage, authorization result, and error semantics.

## OpenAPI and implementation

`openapi/powercontext.yaml` remains the sole HTTP contract. Generated models and operation metadata are checked in,
and Client methods encode path segments, query values, and `If-Match` without adding family-specific methods.

The persistence implementation uses the existing Source journal, Artifact revision table, Artifact head table, and
lineage tables. Timestamp, digest, schema metadata, and deletion state may use compatible side tables so existing
databases do not require destructive column rewrites. Historical rows without optional projected metadata remain
readable. SQLite and OceanBase must pass the same behavioral contract.

The implementation sequence is:

1. add the Source, Artifact, and Scope paths and schemas to OpenAPI;
2. generate Python and JavaScript operation bindings;
3. add shared Source/Artifact application services and route overlapping reads/writes through them;
4. add cursor, optimistic concurrency, tombstone, and family-capability behavior;
5. add Client methods and contract, persistence, server, and end-to-end tests.

## Acceptance criteria

| Scenario | Required behavior |
| --- | --- |
| No umbrella concept | no shared Source/Artifact selector, union request/response, or kind field |
| No write-time generation | Source create carries and returns only durable Source state |
| Source operations | only create/get/list/search are exposed |
| Source list/search | one `GET /v1/sources` operationId, `search_sources`; omitted `type` or `list` lists, `search` requires `q` |
| Artifact operations | fixed create/get/list/search/replace/delete paths; replace commits an immutable next revision |
| Exact identity | Source reference has no revision; every Artifact response has an exact revision |
| Scope required | every Source/Artifact operation names one `scope_id` |
| Scope discovery | `GET /v1/scopes` lists authorized durable Scopes, including empty Scopes known to the Scope layer |
| Pagination | cursors are stable and bound to the complete query and authorization context |
| Concurrency | replace/delete require current ETag; missing is `428`, stale is `412` |
| Review gate | Review families cannot be mutated through direct Artifact operations |
| Memory boundary | Source create and Memory flush are separate; flush processes a bounded pending window |
| Compatibility | existing Source, Memory, Experience, Skill, Handoff, and Candidate APIs keep their behavior |
| Extensibility | adding a direct Artifact family adds no base path or generated Client method |

# Drawbacks

- Base Artifact content is generic JSON in generated clients, so a typed family endpoint remains more ergonomic.
- Old and new read paths coexist and require shared services plus parity tests to prevent drift.
- Scope activity summaries add projection and consistency work.
- Direct and reviewed families support different mutations, so clients must inspect capabilities.
- Logical deletion must remain compatible with lineage validation and retention.
- Source create and Memory flush are not one transaction; callers must handle a durable Source followed by a
  retryable flush failure.
- Source list and search share one operationId and response, so clients must handle `type` and optional hit fields.

# Rationale and alternatives

Action suffixes such as `/add`, `/get`, `/list`, `/update`, and `/delete` were rejected because HTTP methods already
express those operations and noun paths give each object one stable address. Making every action a POST would also
discard safe/cacheable read semantics and standard conditional requests.

`POST /v1/artifacts/{id}/revisions` was considered for updates. It represents append-only storage accurately but
makes callers construct revision transitions directly. `PUT` on the current head better expresses complete
replacement while the Runtime retains revision allocation and CAS.

Putting `scope_id` in paths was rejected because valid Scope identifiers may contain `/`. A combined Source and
Artifact search was rejected because identity, ranking, projection, and lifecycle differ. Deriving Scope identity
from Source or Artifact rows was rejected because it loses empty Scopes and conflicts with the authoritative Scope
application layer.

# Unresolved questions

There are no unresolved wire-level decisions required to accept this RFC. Authorization vocabulary, Scope mutation,
cross-Scope sharing, family schema registration details, and partial Artifact updates are intentionally separate
designs.

# Future possibilities

- subject and group grants for read/write sharing built on exact Scope and publication semantics;
- cross-type or cross-family search with an explicit ranking and cursor contract;
- Artifact restore, retention, administrator purge, and bulk mutations;
- a Client convenience method that sequentially creates a Source and flushes Memory without changing the server
  contract.
