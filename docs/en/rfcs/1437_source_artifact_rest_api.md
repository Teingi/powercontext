- Proposal Name: `source_artifact_rest_api`
- Start Date: 2026-09-01
- RFC PR: [oceanbase/powercontext#1437](https://github.com/oceanbase/powercontext/pull/1437)
- Related RFCs: [RFC 0019](0019_local_source_memory_runtime.md),
  [RFC 0048](0048_handoff_artifact.md), [RFC 0050](0050_artifact_candidate_review_inbox.md),
  [RFC 0051](0051_experience_skill_artifact_families.md), and
  [RFC 1345](1345_scope_organization_and_agent_integration.md)

# Summary

This RFC adds two foundational REST API surfaces for PowerContext: Source supports Create, Get, List, and Search;
Artifact supports Create, Get head, Get Revision, List, Search, Replace, and Delete. List and Search share each
resource's collection GET. An absent or blank `query` performs List, while a non-empty `query` performs Search, so the
design adds nine HTTP operations in total.

The new APIs model Source and Artifact as children of a Scope. A Source has the public identity
`(scope_id, source_type, source_id)`. An Artifact head has the public identity `(scope_id, family, artifact_id)`, and an
exact Revision adds `revision`. Every component of a named resource's identity appears in its URI path. Create operates
on a parent collection and the server generates `source_id` or `artifact_id`. This RFC does not introduce a generic
Resource abstraction, change existing APIs, or combine Source persistence with Memory, Experience, Skill, or Handoff
generation.

# Motivation

PowerContext's existing APIs primarily represent domain actions such as Source capture, Memory flush, Candidate
review, and Handoff workflows. Those APIs preserve the correct domain boundaries, but callers still lack consistent,
predictable foundational access for:

- creating and reading Sources in a selected Scope;
- listing or searching Sources within one Source type;
- creating, reading, revising, listing, searching, and logically deleting committed Artifacts;
- reusing a fixed HTTP surface when a Source type or Artifact Family is added instead of adding another CRUD path set;
- explicitly composing Source Create with an existing domain command when immediate generation is required.

The design must also align public fields with the current persistence model. It distinguishes fields stored directly,
fields encoded in canonical payloads, relationships represented by lineage tables, request-only values, and the small
set of persistence fields required for stable timestamps and logical deletion.

# Guide-level explanation

## Two foundational resources

A Source is durable evidence without revisions. After creation it cannot be replaced or deleted through this API. A
correction creates another Source, and subsequent Artifact lineage records the exact evidence used.

An Artifact is a committed, evolving product. Create commits Revision 1. Replace never overwrites old content; it
commits the next immutable Revision and advances the head. A caller can read either the current head or an exact
historical Revision.

```json
{
  "source_key": [
    "scope_id",
    "source_type",
    "source_id"
  ],
  "artifact_head_key": [
    "scope_id",
    "family",
    "artifact_id"
  ],
  "artifact_revision_key": [
    "scope_id",
    "family",
    "artifact_id",
    "revision"
  ]
}
```

`source_id` is unique only within one `(scope_id, source_type)` collection. `artifact_id` is unique only within one
`(scope_id, family)` collection. A caller must not treat either value as globally unique without its Scope and
classification fields.

## Common request flow

Create a captured text Source:

```http
POST /v1/scopes/scp_01J/sources
Content-Type: application/json
```

```json
{
  "source_type": "content",
  "content": "Refund processing must retain human review.",
  "metadata": {
    "title": "Refund processing constraint"
  }
}
```

The response contains the complete identity and canonical URI:

```http
HTTP/1.1 201 Created
Location: /v1/scopes/scp_01J/sources/content/src_01J
```

```json
{
  "scope_id": "scp_01J",
  "source_type": "content",
  "source_id": "src_01J",
  "content": "Refund processing must retain human review.",
  "metadata": {
    "title": "Refund processing constraint"
  },
  "created_at": "2026-09-02T12:00:00Z",
  "position": 42,
  "content_digest": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
}
```

Source Create only performs durable persistence; it does not invoke a model. A caller that needs Memory immediately
then invokes the existing Memory flush command:

```json
[
  {
    "step": 1,
    "request": "POST /v1/scopes/scp_01J/sources",
    "capture": "response.position"
  },
  {
    "step": 2,
    "request": "POST /v1/memory/flush",
    "body": {
      "scope_id": "scp_01J"
    },
    "repeat_until": "response.current_cursor >= source.position"
  }
]
```

Memory flush processes a bounded pending Source window. It does not guarantee that only the newly created Source is
processed, and it is not a full-history refresh. A generation failure does not roll back a committed Source.

To create a committed Artifact, the caller supplies `family` in the request body. The server generates `artifact_id`
and commits Revision 1:

```http
POST /v1/scopes/scp_01J/artifacts
Content-Type: application/json
```

```json
{
  "family": "company.example.decision",
  "content": {
    "title": "Human review for refunds",
    "decision": "Refunds require human review"
  },
  "source_refs": [
    {
      "source_type": "content",
      "source_id": "src_01J"
    }
  ],
  "artifact_refs": []
}
```

```http
HTTP/1.1 201 Created
Location: /v1/scopes/scp_01J/artifacts/company.example.decision/dec_01J
ETag: "revision:1"
```

The initial API does not define top-level Artifact `metadata` or `schema_version`. Titles, tags, and other
Family-specific properties belong in `content` and are validated by the corresponding Family model.

## List and Search

List and Search use the same typed collection URI:

```http
GET /v1/scopes/scp_01J/sources/content?limit=50
GET /v1/scopes/scp_01J/sources/content?query=refund&mode=auto&limit=20

GET /v1/scopes/scp_01J/artifacts/company.example.decision?limit=50
GET /v1/scopes/scp_01J/artifacts/company.example.decision?query=refund&mode=auto&limit=20
```

An absent, empty, or whitespace-only `query` means List. A non-empty `query` means Search. Both return
`query + mode + items + next_cursor`. For List, `query`, `mode`, and `score` are `null`, and `snippets` is `[]`.

# Reference-level explanation

## Scope, hierarchy, and canonical URIs

`scope_id` is the resource owner, authorization boundary, and part of the public identity. Scope creation, retrieval,
listing, organization relationships, and bindings are defined by
[RFC 1345](1345_scope_organization_and_agent_integration.md) and its implementation. This RFC does not define Scope
operations; it only defines Source and Artifact children beneath an existing Scope.

Every new business API follows:

```text
{scheme}://{endpoint}/{resource-path}?{query-string}
```

- production uses `https`, and the endpoint identifies deployment rather than business semantics;
- paths use lowercase plural nouns, with `kebab-case` for multi-word static segments;
- JSON and query parameters use `snake_case`, and URIs have no trailing slash;
- paths do not contain CRUD verbs such as `/add`, `/get`, `/update`, or `/delete`;
- query strings carry query, search-mode, and pagination inputs, not named-resource identity components;
- `source_type` and `family` must each encode as one path segment and cannot contain an unescaped `/`.

The allowed resource paths are:

```text
/v1/scopes/{scope_id}/sources
/v1/scopes/{scope_id}/sources/{source_type}
/v1/scopes/{scope_id}/sources/{source_type}/{source_id}

/v1/scopes/{scope_id}/artifacts
/v1/scopes/{scope_id}/artifacts/{family}
/v1/scopes/{scope_id}/artifacts/{family}/{artifact_id}
/v1/scopes/{scope_id}/artifacts/{family}/{artifact_id}/revisions/{revision}
```

Create operates on the `/sources` or `/artifacts` parent collection, with classification supplied by `source_type` or
`family` in the body. Typed collection GETs use `/sources/{source_type}` or `/artifacts/{family}`. Named Source,
Artifact head, and Artifact Revision paths contain their complete compound identity.

If a resource is later shared with another Scope, its canonical URI continues to use the owner Scope. Authorization
must not create a second Scope path for the same resource. Changing owner Scope, `source_type`, or `family` changes the
public identity and is treated as creating a new resource or performing an explicit migration.

## New operations

Nine HTTP operations provide eleven foundational capabilities:

| Object | Capability | operationId | HTTP method and URI | Input | Success |
| --- | --- | --- | --- | --- | --- |
| Source | Create | `create_source` | `POST /v1/scopes/{scope_id}/sources` | body: `source_type?`, `content`, `metadata?` | `201 SourceRecord` + `Location` |
| Source | Get | `get_source` | `GET /v1/scopes/{scope_id}/sources/{source_type}/{source_id}` | complete compound identity in Path | `200 SourceRecord` |
| Source | List/Search | `list_sources` | `GET /v1/scopes/{scope_id}/sources/{source_type}` | query: `query?`, `mode?`, `limit?`, `cursor?` | `200 SourcePage` |
| Artifact | Create | `create_artifact` | `POST /v1/scopes/{scope_id}/artifacts` | body: `family`, `content`, references | `201 ArtifactRevision` + `Location` + `ETag` |
| Artifact | Get head | `get_artifact` | `GET /v1/scopes/{scope_id}/artifacts/{family}/{artifact_id}` | `If-None-Match?` | `200 ArtifactRevision` + `ETag`, or `304` |
| Artifact | Get Revision | `get_artifact_revision` | `GET /v1/scopes/{scope_id}/artifacts/{family}/{artifact_id}/revisions/{revision}` | complete Revision identity in Path | `200 ArtifactRevision` |
| Artifact | List/Search | `list_artifacts` | `GET /v1/scopes/{scope_id}/artifacts/{family}` | query: `query?`, `mode?`, `limit?`, `cursor?` | `200 ArtifactPage` |
| Artifact | Replace | `replace_artifact` | `PUT /v1/scopes/{scope_id}/artifacts/{family}/{artifact_id}` | `If-Match`; complete replacement body | `200 ArtifactRevision` + new `ETag` |
| Artifact | Delete | `delete_artifact` | `DELETE /v1/scopes/{scope_id}/artifacts/{family}/{artifact_id}` | `If-Match` | `204 No Content` |

OpenAPI permits only one operation per method/path pair. The collection GET operation IDs are therefore
`list_sources` and `list_artifacts`. A non-empty `query` changes query behavior but does not create another method/path
or introduce a `type=list|search` discriminator.

## Wire schemas

### Source schemas

`CreateSourceRequest`:

```json
{
  "source_type": "optional string; defaults to content",
  "content": "required JSON value; validated by the source_type adapter",
  "metadata": "optional object; defaults to {}, stored and returned only"
}
```

The request does not accept `scope_id` or `source_id`. `scope_id` comes from the path, and the server generates
`source_id`. Every Source adapter exposed through this generic API must preserve and return `metadata` without loss.

`SourceRecord`:

```json
{
  "scope_id": "string; owner Scope",
  "source_type": "string; Source adapter name and typed collection",
  "source_id": "string; stable ID within the collection",
  "content": "JSON value; persisted canonical content",
  "metadata": "object; defaults to {}",
  "created_at": "RFC 3339 UTC date-time; server persistence time",
  "position": "integer; Scope Source journal position",
  "content_digest": "sha256:<64 lowercase hexadecimal characters>"
}
```

`SourceCollectionItem` omits full `content`:

```json
{
  "scope_id": "scp_01J",
  "source_type": "content",
  "source_id": "src_01J",
  "metadata": {},
  "created_at": "2026-09-02T12:00:00Z",
  "position": 42,
  "content_digest": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "score": null,
  "snippets": []
}
```

### Artifact schemas

`CreateArtifactRequest`:

```json
{
  "family": "required string; Artifact Family",
  "content": "required object; complete Family content for Revision 1",
  "source_refs": "optional SourceReference[]; defaults to []",
  "artifact_refs": "optional ArtifactReference[]; defaults to []"
}
```

`ReplaceArtifactRequest` does not repeat path identity:

```json
{
  "content": "required object; complete Family content for the next Revision",
  "source_refs": "optional SourceReference[]; omission resets to []",
  "artifact_refs": "optional ArtifactReference[]; omission resets to []"
}
```

`ArtifactRevision`:

```json
{
  "scope_id": "scp_01J",
  "artifact_ref": {
    "family": "company.example.decision",
    "artifact_id": "dec_01J",
    "revision": 2
  },
  "content": {
    "title": "Human review for refunds",
    "decision": "Refunds require human review"
  },
  "source_refs": [
    {
      "source_type": "content",
      "source_id": "src_01J"
    }
  ],
  "artifact_refs": [],
  "created_at": "2026-09-02T12:10:00Z",
  "content_digest": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
}
```

`artifact_ref` does not contain `scope_id`; only its combination with top-level `scope_id` is a complete public
identity. `source_refs` and `artifact_refs` likewise inherit the current Artifact's Scope. This RFC does not express
cross-Scope lineage.

`ArtifactCollectionItem` represents only the current head of a non-deleted Artifact and omits full `content` and
historical Revisions:

```json
{
  "scope_id": "scp_01J",
  "artifact_ref": {
    "family": "company.example.decision",
    "artifact_id": "dec_01J",
    "revision": 2
  },
  "created_at": "2026-09-02T12:10:00Z",
  "content_digest": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "score": null,
  "snippets": []
}
```

## Operation examples

### Source Get and collection GET

```json
[
  {
    "operation_id": "get_source",
    "request": "GET /v1/scopes/scp_01J/sources/content/src_01J",
    "success": "200 SourceRecord"
  },
  {
    "operation_id": "list_sources",
    "request": "GET /v1/scopes/scp_01J/sources/content?limit=50&cursor=...",
    "success": "200 SourcePage<SourceCollectionItem>"
  },
  {
    "operation_id": "list_sources",
    "request": "GET /v1/scopes/scp_01J/sources/content?query=refund&mode=auto&limit=20",
    "success": "200 SourcePage<SourceCollectionItem>"
  }
]
```

### Artifact Get and collection GET

```json
[
  {
    "operation_id": "get_artifact",
    "request": "GET /v1/scopes/scp_01J/artifacts/company.example.decision/dec_01J",
    "success": "200 ArtifactRevision + ETag"
  },
  {
    "operation_id": "get_artifact_revision",
    "request": "GET /v1/scopes/scp_01J/artifacts/company.example.decision/dec_01J/revisions/1",
    "success": "200 ArtifactRevision"
  },
  {
    "operation_id": "list_artifacts",
    "request": "GET /v1/scopes/scp_01J/artifacts/company.example.decision?limit=50&cursor=...",
    "success": "200 ArtifactPage<ArtifactCollectionItem>"
  },
  {
    "operation_id": "list_artifacts",
    "request": "GET /v1/scopes/scp_01J/artifacts/company.example.decision?query=refund&mode=auto&limit=20",
    "success": "200 ArtifactPage<ArtifactCollectionItem>"
  }
]
```

### Artifact Replace

```http
PUT /v1/scopes/scp_01J/artifacts/company.example.decision/dec_01J
Content-Type: application/json
If-Match: "revision:1"
```

```json
{
  "content": {
    "title": "Human review for refunds",
    "decision": "Refunds require human review",
    "rationale": "Required for funds safety"
  },
  "source_refs": [],
  "artifact_refs": []
}
```

PUT is a complete replacement. Success commits Revision 2 and returns `200 ArtifactRevision` with a new ETag.
Omitting an optional reference array resets it to `[]`; omission does not preserve the previous Revision's value. The
operation does not support merge patch or automatic merging.

### Artifact Delete

```http
DELETE /v1/scopes/scp_01J/artifacts/company.example.decision/dec_01J
If-Match: "revision:2"
```

Successful logical deletion returns `204 No Content`. Historical Revisions remain, and this RFC does not provide
restore or purge.

## Collection queries and cursors

Collection GET accepts:

| Parameter | Required | Meaning |
| --- | --- | --- |
| `query` | no | List when normalized to empty; Search when non-empty. |
| `mode` | no | Requested search mode; `auto` lets the server select the actual mode. Valid only with a non-empty `query`. |
| `limit` | no | Maximum number of items in this page. |
| `cursor` | no | Opaque token returned by the previous page; it must match the caller, collection path, and query conditions. |

The common response envelope is:

```json
{
  "query": null,
  "mode": null,
  "items": [],
  "next_cursor": null
}
```

Search returns the normalized `query`, actual `mode`, and each item's `score` and `snippets`. For List, `query`, `mode`,
and `score` are `null`, and `snippets` is `[]`. Responses do not include `total`.

A cursor is bound to the caller, endpoint, complete collection path, normalized query, filters, ordering, and actual
search mode. List and Search cursors cannot be exchanged. v0.1 supports forward pagination only. An invalid or
mismatched cursor returns `400 invalid_cursor`; an expired cursor returns `410 cursor_expired`. The HTTP pagination
cursor has no mapping to internal `pc_source_cursors.cursor`, which tracks a domain binding's progress through the
Source journal.

## Requests, responses, and errors

- Path, Query, Header, and Body describe parameter locations, not one aggregate JSON payload.
- GET and DELETE have no request body.
- Request schemas default to `additionalProperties: false`, except explicit Source `metadata` extension objects.
- Response schemas may gain optional fields, and clients must ignore unknown response fields.
- Source `metadata` defaults to `{}`; reference arrays and `snippets` default to `[]`; `score` is `null` without ranking.
- Times use RFC 3339 UTC, and enumerations use `lower_snake_case`.
- Every response includes `X-PowerContext-Request-ID`.

| Status | Meaning |
| --- | --- |
| `200` | Get, List, Search, or Replace succeeded. |
| `201` | Source or Artifact synchronously created; `Location` is required. |
| `204` | Delete succeeded with no response body. |
| `304` | `If-None-Match` matched. |
| `400` | Invalid query, format, or cursor. |
| `401` | Unauthenticated; includes `WWW-Authenticate`. |
| `403` | The caller cannot access the explicitly selected Scope. |
| `404` | The resource does not exist or is hidden from the caller. |
| `405` | The Family does not support the operation; includes `Allow`. |
| `409` | Resource identity or lifecycle state conflict. |
| `410` | Cursor expired. |
| `412` | `If-Match` does not match the current ETag. |
| `413` | Request body too large; never used for an oversized response. |
| `422` | Field or Family content validation failed. |
| `428` | Required `If-Match` missing. |
| `429` | Rate limited; includes `Retry-After`. |
| `503` | A declared capability is temporarily unavailable. |

Errors use one envelope:

```json
{
  "error": {
    "code": "invalid_request",
    "message": "The request is invalid.",
    "details": {}
  }
}
```

An error is never returned inside a successful `200` envelope.

## Create retries, caching, and concurrency

Source Create and Artifact Create do not accept `Idempotency-Key`. Every successful request creates a new resource;
retrying after an unknown outcome may create a duplicate. The server-generated ID is returned in the response body and
`Location`.

Artifact Create, Get head, and Replace return an ETag. Get head may carry `If-None-Match`; a match returns `304` with no
body. Replace and Delete require `If-Match`; omission returns `428`, and a mismatch with the current head returns `412`.

The first successful Delete returns `204`. A retry also returns `204` when the server can prove it is the same deletion.
A resource that never existed, whose retry identity can no longer be proven, or that is hidden from the caller returns
`404`.

## Family capability boundaries

A fixed Artifact URI does not imply that every Family allows direct writes:

| Family kind | Read | Create/Replace/Delete |
| --- | --- | --- |
| Direct | Read committed Artifacts. | Enabled according to Family capability. |
| Review | Read approved Artifacts only. | Return `405 operation_not_supported`; continue using Candidate Review. |
| Memory | Read the Artifact head without replacing Entry APIs. | Continue using Memory domain commands. |
| Handoff | Read committed Handoffs. | Continue using the prepare/finalize/commit workflow. |

A Candidate is not an Artifact. Pending and rejected Candidates do not appear in Artifact List/Search.

## API-to-persistence mapping

The table and column names below describe the current `SHARED_METADATA` implementation mapping, not the client
contract. Internal storage may be refactored, but the OpenAPI field semantics must remain stable.

Mapping kinds:

```json
{
  "direct": "reads or writes an existing relational column directly",
  "encoded": "is contained in an existing canonical payload/content binary column",
  "relation": "is split into ordered relationship rows",
  "derived": "is deterministically generated from persisted data without a separate column",
  "runtime": "exists only during HTTP, search, or pagination processing",
  "new_column": "is absent on current master and must be persisted to retain the API semantics"
}
```

### Source field mapping

| API field | Persistence field | Mapping | Meaning |
| --- | --- | --- | --- |
| `scope_id` | `pc_sources.scope_id` | `direct` | Owner Scope, authorization boundary, and identity component; at most 256 characters with byte-exact comparison. |
| `source_type` | `pc_sources.source_type` | `direct` | Stable adapter name and typed collection; at most 128 characters and defaults to `content` on Create. |
| `source_id` | `pc_sources.source_id`; the typed Source `name` remains equal | `direct` | Stable ID within the collection; server-generated and at most 256 characters. |
| `content` | `pc_sources.payload` | `encoded` | Evidence content in the complete typed Source model; the `content` adapter maps it to `ContentSource.content`. |
| `metadata` | Source metadata inside `pc_sources.payload` | `encoded` | Extension attributes that are only stored and returned; there is no separate column or metadata query/index. |
| `created_at` | target `pc_sources.created_at` | `new_column` | Server UTC time when the Source first commits successfully. |
| `position` | `pc_sources.journal_position` | `direct` | Monotonically increasing position unique within the Scope journal. |
| `content_digest` | no separate column | `derived` | SHA-256 digest of canonical API `content`. |

`pc_source_journal_heads.position` is the Scope journal high-water mark and allocation source, not an individual
Source response field.

### Artifact field mapping

| API field | Persistence field | Mapping | Meaning |
| --- | --- | --- | --- |
| `scope_id` | `scope_id` in Artifact, head, and lineage tables | `direct` | Owner Scope, authorization boundary, and identity component; at most 256 characters. |
| `artifact_ref.family` | `pc_artifacts.family`, `pc_artifact_heads.family` | `direct` | Family and adapter route; at most 128 characters. Create receives `family` in the body. |
| `artifact_ref.artifact_id` | `pc_artifacts.artifact_id`, `pc_artifact_heads.artifact_id` | `direct` | Stable lifecycle ID; server-generated and at most 128 characters. |
| `artifact_ref.revision` | `pc_artifacts.revision`; the head points through `pc_artifact_heads.revision` | `direct` | Immutable Revision increasing from 1. |
| `artifact_ref` | no separate JSON column | `derived` | Assembled from Family, Artifact ID, and Revision, and located together with the top-level Scope. |
| `content` | `pc_artifacts.content` | `encoded` | Canonical JSON bytes validated by the Family content model. |
| `source_refs` | `pc_artifact_lineage_sources` | `relation` | Same-Scope Source references preserved in array order. |
| `artifact_refs` | `pc_artifact_lineage_artifacts` | `relation` | Same-Scope upstream Artifact Revision references preserved in array order. |
| `created_at` | target `pc_artifacts.created_at` | `new_column` | Server UTC time when this Revision commits successfully. |
| `content_digest` | no separate column | `derived` | SHA-256 digest of canonical Artifact content. |

Artifact has no top-level `metadata`, so this RFC does not add `pc_artifacts.metadata` or change the existing
Family-content encoding in `pc_artifacts.content`.

`source_refs` is stored as:

```json
{
  "child_identity": [
    "scope_id",
    "family",
    "artifact_id",
    "revision"
  ],
  "ordinal": "generated from request array order",
  "source_refs[].source_type": "source_type",
  "source_refs[].source_id": "source_id"
}
```

`artifact_refs` is stored as:

```json
{
  "child_identity": [
    "scope_id",
    "family",
    "artifact_id",
    "revision"
  ],
  "ordinal": "generated from request array order",
  "artifact_refs[].family": "upstream_family",
  "artifact_refs[].artifact_id": "upstream_artifact_id",
  "artifact_refs[].revision": "upstream_revision"
}
```

### Runtime and internal fields

| Field | Persistence relation | Meaning |
| --- | --- | --- |
| `query`, `mode`, `limit` | `runtime` | Control only the current collection query. |
| `cursor`, `next_cursor` | `runtime` | HTTP pagination tokens, not business-resource fields. |
| `score`, `snippets` | `runtime` | Search ranking and match-display data, never written back to resources. |
| `Location` | `derived` | Canonical URI assembled from the complete public identity. |
| `ETag` | `derived` | Generated from current `pc_artifact_heads.revision`. |
| `If-Match`, `If-None-Match` | `runtime` | Compared with the current ETag and not stored separately. |
| `X-PowerContext-Request-ID` | `runtime` | Per-request tracing ID. |
| `pc_artifact_heads.searchable_text` | internal Artifact Search projection | Searchable text for the current head; each searchable Family supplies a deterministic projector. |
| Source search projection | internal Source Search projection | No generic column exists on master; v0.1 may read payloads, while a scalable implementation may add an internal index. |
| target `pc_artifact_heads.deleted_at` | Artifact lifecycle | `null` means active; non-null is the logical deletion time while retaining the head Revision. |

Explanatory `status`, `notes`, `precondition_errors`, `retry`, and `not_found` values in documentation are not wire
response fields and do not map to database columns.

### Required schema adaptations

| Table | New field | Required | Migration rule |
| --- | --- | --- | --- |
| `pc_sources` | `created_at` | yes | Record UTC time for new writes; legacy rows may remain `null` when the original time cannot be recovered. |
| `pc_artifacts` | `created_at` | yes | Record UTC commit time for each new Revision; legacy rows may remain `null`. |
| `pc_artifact_heads` | `deleted_at` | yes | Active and existing historical heads default to `null`; Delete writes UTC time and retains current `revision`. |

`content_digest`, ETag, Location, search information, and pagination cursors are derived or request-local and do not
require database columns.

Digest computation is fixed as:

```json
{
  "algorithm": "sha256",
  "input": "UTF-8 canonical JSON bytes of API content",
  "object_key_order": "lexicographic",
  "insignificant_whitespace": "removed",
  "included_fields": [
    "content"
  ],
  "output": "sha256:<64 lowercase hexadecimal characters>"
}
```

## Existing API compatibility

This RFC defines only new operations. It does not change any existing path, request, response, status code, reference
schema, or domain behavior. New entry points must use the same authoritative Source journal, Artifact Revisions,
lineage, and authorization decisions rather than creating a second data or identity space.

The new APIs use server-generated IDs. Whether an existing domain entry point accepts a caller-stable ID is outside
this RFC. Both entry-point styles can adapt at the application-service boundary but must ultimately preserve the same
persistence uniqueness and read/write invariants.

## Implementation and acceptance

Implementation order:

1. Add the nine operations and separate request/response schemas to `openapi/powercontext.yaml`.
2. Regenerate checked-in HTTP models and operations.
3. Reuse the Source repository, Artifact repository, lineage, and authorization services.
4. Add `created_at` and `deleted_at` persistence fields with SQLite and OceanBase migration checks.
5. Implement stable List/Search cursors, ETags, and conditional requests.
6. Run `make api-generate`, `make contract-test`, `make test`, and `make docs-test`.

Acceptance criteria:

- Operations are added only beneath the two Scope child-resource trees listed in this RFC; Scope APIs are not
  redefined.
- Source exposes only Create, Get, and List/Search; Create does not accept `source_id`.
- Artifact exposes Create, Get head, Get Revision, List/Search, Replace, and Delete; Create does not accept
  `artifact_id`.
- Create does not accept `Idempotency-Key` and returns the server-generated ID plus `Location`.
- Every named GET carries the complete compound identity in its path.
- A non-empty `query` performs Search; otherwise the collection GET performs List. There is no `type=list|search`.
- Replace creates the next immutable Revision and protects the head with ETag/If-Match.
- Artifact has no top-level `metadata` or `schema_version`.
- Source `metadata` round-trips without loss through `pc_sources.payload`.
- Review Families cannot bypass Candidate approval through the foundational API.
- SQLite and OceanBase pass the same contract and behavior tests.

# Drawbacks

- Compound identities produce longer URIs, and changing owner Scope, Source type, or Artifact Family changes the
  canonical URI.
- Family-specific `content` is represented as a JSON object in the generic generated client, with weaker static typing
  than a dedicated Family API.
- Source List must decode typed payloads to return metadata, and generic Source Search may scan payloads until an index
  projection exists.
- Create has no idempotency key, so retrying an unknown outcome may create a duplicate resource.
- Source Create and subsequent generation are not transactional, and clients must handle generation failure and retry.
- Logical deletion and stable timestamps require a persistence migration, while original timestamps for legacy rows
  cannot be reconstructed reliably.

# Rationale and alternatives

## No generic Resource API

Source is immutable evidence; Artifact is a versioned, lifecycle-managed product. Their update, deletion, and lineage
semantics differ. A generic `/resources` surface would require selectors or union schemas and defer Family capability
errors to runtime, so the design retains two fixed resource APIs.

## Scope children with complete path identity

Putting `scope_id`, `source_type`/`family`, and the ID in a named-resource path gives canonical URIs, authorization
audits, cache keys, and logs the complete public identity. Required query parameters could route the request, but they
would leave the path naming only part of a resource and are not used for identity.

Create operates on the `/sources` and `/artifacts` parent collections because the server generates IDs and receives
`source_type`/`family` in the body. After creation, classification is part of identity and therefore appears in typed
collection and item URIs.

## Combined List and Search

Separate `/search-results` collections could have different response schemas but would add collection paths and
generated-client operations. This RFC defines common `SourcePage` and `ArtifactPage` schemas with explicit empty
values for `query`, `mode`, `score`, and `snippets` in List mode. One collection GET can therefore provide both stable
List and relevance Search. A GET body and a `type=list|search` discriminator are both rejected.

## Server-generated IDs without Create idempotency

Server-generated IDs simplify callers and avoid requiring external systems to construct internal identities. v0.1
does not accept `Idempotency-Key`; the explicit tradeoff is that retrying an unknown result may create a duplicate,
rather than pretending Create is idempotent.

## Source metadata reuses payload

The API only stores and returns Source metadata; it does not filter, sort, or index by metadata. `ContentSource`
already includes metadata in `pc_sources.payload`, so no separate column is added. Artifact has no equivalent generic
metadata semantics in the initial API. The field is omitted instead of changing the Family-specific encoding of
`pc_artifacts.content`.

# Prior art

The design builds directly on PowerContext's existing Scope, Source journal, Artifact Repository, ArtifactRef,
SourceRef, lineage, Candidate Review, and domain commands. Source journal positions already provide a stable processing
boundary. Artifact heads and immutable Revisions already provide revision and concurrency foundations. This RFC adds a
consistent foundational HTTP surface over those existing domain objects.

HTTP methods, noun-based resource paths, `Location`, conditional ETags, RFC 3339 timestamps, and standard error status
codes follow common HTTP/REST practice. Compound identity, Family capability, and generation boundaries remain
PowerContext-specific domain decisions.

# Unresolved questions

There are no blocking design questions for RFC acceptance. The implementation PR may choose the following internal
details without changing the public contract:

- the server-generated ID algorithm, provided values remain opaque, path-safe, and within the defined limits;
- cursor signing and encoding, provided cursors remain opaque, query-bound, and preserve the specified errors;
- payload scanning or an internal projection for v0.1 Source Search, provided response behavior is unchanged;
- the nullable compatibility mechanism for legacy `created_at` values that cannot be reconstructed.

Cross-Scope sharing and authorization, cross-type or cross-Family Search, complex POST Search, Artifact restore,
retention, administrative purge, and batch mutation are explicitly outside this RFC and require separate designs.

# Future possibilities

- Add dedicated full-text or vector projections for Source and more Artifact Families.
- Define side-effect-free POST Search if complex conditions cannot be represented stably in a query string.
- Add cross-type and cross-Family ranking without changing named-resource URIs.
- Add Artifact restore, retention, and administrative purge.
- Define read/write grants and cross-tenant authorization outside the owner Scope in a separate RFC.
- Add a TTL-bound Create idempotency key with original-response replay semantics when a concrete retry requirement
  exists.
