- Proposal Name: `source_artifact_rest_api`
- Start Date: 2026-09-01
- RFC PR: [oceanbase/powercontext#0000](https://github.com/oceanbase/powercontext/pull/0000)

# Summary

This RFC adds independent, stable HTTP APIs for two existing PowerContext concepts:

- Source: create, get, list, and search;
- Artifact: create, get, list, search, replace, and delete.

The API reuses the existing Source, Artifact, immutable Artifact Revision, and Scope semantics. It does not add an
umbrella object, a union reference, a shared selector, a type-registration endpoint, or a cross-kind list/search.
Adding an Artifact family does not add another set of base paths or generated Client methods.

Scope creation, retrieval, listing, organization, and bindings are defined by
[PR #1401](https://github.com/oceanbase/powercontext/pull/1401). This RFC only consumes an already resolved
`scope_id` as the boundary of Source and Artifact operations; it defines no Scope endpoint or schema.

Writing and generation remain separate commit boundaries. `POST /v1/sources` durably creates a Source and returns
that Source. A caller that needs immediate Memory extraction composes it with the existing
`POST /v1/memory/flush` operation.

The wire contract follows these rules:

- plural noun paths carry object identity while HTTP methods carry the operation;
- `GET` reads, lists, and searches; `POST` creates; `PUT` fully replaces an Artifact head; `DELETE` deletes it;
- Artifact revisions remain immutable: replacing a head commits the next revision instead of overwriting history;
- list and search responses use typed items and `next_cursor`.
- every HTTP `SourceReference` uses `source_type` for the Source type and no longer uses the historical `name` field.

# Motivation

PowerContext currently exposes domain commands such as Source capture, Memory flush, Experience and Skill
generation, Candidate review, and the Handoff workflow. Those commands preserve the domain lifecycle, but callers
also need predictable base access to already durable Sources and committed Artifacts.

The required outcomes are:

- create and read a Source in one Scope;
- list and search Sources by Scope and Source type;
- create, read, list, search, revise, and delete Artifacts by Scope and family where the family permits it;
- add future Artifact families without adding family-specific base endpoints;
- let clients explicitly compose Source creation with generation commands instead of making writes invoke models.

# Goals

- Model Source and Artifact directly without introducing a shared parent concept.
- Preserve Source identity without a revision and Artifact identity with an exact revision.
- Standardize the shared HTTP `SourceReference` type field as `source_type`.
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

## Source and Artifact

A Source is durable evidence with a stable `SourceReference`:

```json
{
  "source_type": "content",
  "source_id": "src_01J..."
}
```

`source_type` is the stable Source type, and `source_id` is the stable identifier within that type. Exact identity is
`(scope_id, source_type, source_id)`. Because `SourceReference` does not carry `scope_id`, it is exact only within the
Scope already established by the request.

This RFC changes the shared HTTP `SourceReference` from the historical `{name, source_id}` shape to
`{source_type, source_id}`. The rename applies together to every Source, Memory, Experience, Skill, Candidate,
Handoff, and Work HTTP request or response that reuses `SourceReference`; no second reference shape is introduced.

The new `POST /v1/sources` operation does not accept a caller-selected `source_id`. The server generates an opaque
`source_id` and returns it in `SourceRecord.source_ref` and `Location`. The compatibility operation
`POST /v1/sources/content` continues to accept a caller-supplied `source_id` for mapping an upstream message,
document, or event identity into Source identity.

A Source has no revision. This RFC therefore does not add Source replace or delete operations. Corrections are new
Sources so evidence already cited by Artifact lineage is never silently changed.

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
Artifact. Scope operations, metadata, organization parents, context references, bindings, pagination, and
authorization remain owned by PR #1401. Callers resolve a `scope_id` through that API before using the operations
defined here.

## Immediate Memory extraction

```json
{
  "workflow": "create_source_then_flush_memory",
  "steps": [
    {
      "step": 1,
      "operation_id": "create_source",
      "request": {
        "method": "POST",
        "path": "/v1/sources",
        "headers": {
          "Idempotency-Key": "idem_01J..."
        }
      },
      "capture": {
        "source_position": "success.body.position"
      }
    },
    {
      "step": 2,
      "operation_id": "flush_memory",
      "request": {
        "method": "POST",
        "path": "/v1/memory/flush",
        "headers": {
          "Content-Type": "application/json"
        },
        "body": {
          "scope_id": "git:github.com/acme/payments"
        }
      },
      "success": {
        "status": 200,
        "body": {
          "status": "processed",
          "previous_cursor": 38,
          "current_cursor": 42,
          "high_watermark": 42,
          "processed_source_count": 4,
          "memory": {
            "family": "memory",
            "artifact_id": "memory",
            "revision": 7
          },
          "changes": []
        }
      },
      "repeat_while": "success.body.current_cursor < source_position"
    }
  ],
  "completion_condition": "flush_memory.success.body.current_cursor >= source_position",
  "flush_semantics": {
    "processing_unit": "bounded_pending_source_window",
    "single_source_only": false,
    "full_history_refresh": false,
    "may_include_earlier_pending_sources": true,
    "source_rolled_back_on_flush_failure": false,
    "flush_retryable": true,
    "combined_result_owner": "caller_or_sdk_convenience_method",
    "changes_create_source_response": false
  }
}
```

# Reference-level explanation

## Base operations, HTTP methods, and URLs

The wire contract for each base operation is fixed as follows:

```json
[
  {
    "function": "Source Create",
    "operation_id": "create_source",
    "method": "POST",
    "path": "/v1/sources"
  },
  {
    "function": "Source Get",
    "operation_id": "get_source",
    "method": "GET",
    "path": "/v1/sources/{source_id}"
  },
  {
    "function": "Source List",
    "operation_id": "list_sources",
    "method": "GET",
    "path": "/v1/sources"
  },
  {
    "function": "Source Search",
    "operation_id": "search_sources",
    "method": "GET",
    "path": "/v1/source-search-results"
  },
  {
    "function": "Artifact Create",
    "operation_id": "create_artifact",
    "method": "POST",
    "path": "/v1/artifacts"
  },
  {
    "function": "Artifact Head Get",
    "operation_id": "get_artifact",
    "method": "GET",
    "path": "/v1/artifacts/{artifact_id}"
  },
  {
    "function": "Artifact Revision Get",
    "operation_id": "get_artifact_revision",
    "method": "GET",
    "path": "/v1/artifacts/{artifact_id}/revisions/{revision}"
  },
  {
    "function": "Artifact List",
    "operation_id": "list_artifacts",
    "method": "GET",
    "path": "/v1/artifacts"
  },
  {
    "function": "Artifact Search",
    "operation_id": "search_artifacts",
    "method": "GET",
    "path": "/v1/artifact-search-results"
  },
  {
    "function": "Artifact Replace",
    "operation_id": "replace_artifact",
    "method": "PUT",
    "path": "/v1/artifacts/{artifact_id}"
  },
  {
    "function": "Artifact Delete",
    "operation_id": "delete_artifact",
    "method": "DELETE",
    "path": "/v1/artifacts/{artifact_id}"
  }
]
```

The `operation_id`, HTTP method, and URL pattern in this JSON definition together form the base API wire contract.

The API additionally requires:

- Create carries `scope_id` and `source_type` / `family` in the request body. GET, PUT, and DELETE carry the
  `scope_id` and `source_type` / `family` identity selectors in query parameters; the PUT body contains only the
  complete replacement;
- `source_type` and `family` are query or body fields, so a new type or family does not add a path;
- resource collection paths are reserved for List, while `/v1/source-search-results` and
  `/v1/artifact-search-results` are read-only virtual collections for Search hits;
- fields use the existing snake_case convention;
- a `source_id` generated by the generic Source Create operation is an opaque path identity that callers must not
  parse or depend on;
- `PUT` accepts only a complete replacement; partial updates require a future `PATCH` contract;
- Artifact replace and delete require the current `ETag` in `If-Match`;
- `SourceReference` is always `{source_type, source_id}`; the historical HTTP field `name` is removed.

Every path segment is RFC 3986 encoded and decoded exactly once. `source_type`, `family`, and `scope_id` are not path
parameters. A `source_id` generated by the generic Source Create operation is an opaque path identity that callers
must not parse or depend on. A `source_id` accepted by the compatibility operation and every `artifact_id` should be
path-segment safe.

## Common response models

### SourceRecord

```json
{
  "scope_id": "git:github.com/acme/payments",
  "source_ref": {
    "source_type": "content",
    "source_id": "src_01J..."
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

`position` is the Source journal position. `content_digest` is the digest of canonical durable content for audit and
integrity checks; it is not the generic Source Create idempotency identity. Legacy Sources created before the
timestamp projection exists may return `created_at: null` without changing identity.

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
      "source_type": "content",
      "source_id": "src_01J..."
    }
  ],
  "artifact_refs": [],
  "created_at": "2026-09-01T04:30:00Z",
  "content_digest": "sha256:0000000000000000000000000000000000000000000000000000000000000000"
}
```

The head response includes the current revision as a strong ETag. Replace and delete send that value back through
`If-Match`:

```json
{
  "response_headers": {
    "ETag": "revision:2"
  },
  "conditional_request_headers": {
    "If-Match": "revision:2"
  }
}
```

Missing `If-Match` returns `428 Precondition Required`; a stale ETag returns `412 Precondition Failed`. No second
generic version field is added because the Artifact revision is already the concurrency version.

When optional object or collection fields are omitted, the Server persists and returns stable defaults. List pages
use explicit summaries instead of presenting partial objects as complete records:

```json
{
  "defaults": {
    "metadata": {},
    "source_refs": [],
    "artifact_refs": [],
    "snippets": []
  },
  "search_score_without_ranking": null,
  "list_item_schemas": {
    "SourcePage.items": "SourceSummary[]",
    "ArtifactPage.items": "ArtifactSummary[]"
  }
}
```

## Source API

Each request addresses one `scope_id` and one `source_type`.

List and Search have different paths, operationIds, and response schemas. `GET /v1/sources` is always
`list_sources` and does not accept `type`, `q`, or `mode`. `GET /v1/source-search-results` is always
`search_sources`; no query parameter switches it into List. Generated Clients therefore expose the symmetric
methods `list_sources()` / `search_sources()` and `list_artifacts()` / `search_artifacts()`.

### Source create contract and compatibility example

```json
{
  "operation_id": "create_source",
  "request": {
    "method": "POST",
    "path": "/v1/sources",
    "headers": {
      "Content-Type": "application/json",
      "Idempotency-Key": "idem_01J..."
    },
    "body": {
      "required_fields": [
        "scope_id",
        "source_type",
        "content"
      ],
      "optional_fields": [
        "metadata"
      ],
      "example": {
        "scope_id": "git:github.com/acme/payments",
        "source_type": "content",
        "content": "Refunds require manual review.",
        "metadata": {
          "title": "Refund constraint",
          "media_type": "text/plain"
        }
      }
    }
  },
  "success": {
    "status": 201,
    "schema": "SourceRecord",
    "headers": {
      "Location": "/v1/sources/src_01J...?scope_id=git%3Agithub.com%2Facme%2Fpayments&source_type=content"
    },
    "body": {
      "scope_id": "git:github.com/acme/payments",
      "source_ref": {
        "source_type": "content",
        "source_id": "src_01J..."
      },
      "content": "Refunds require manual review.",
      "metadata": {
        "title": "Refund constraint",
        "media_type": "text/plain"
      },
      "created_at": "2026-09-01T04:00:00Z",
      "position": 42,
      "content_digest": "sha256:..."
    }
  },
  "errors": [
    {
      "status": 422,
      "code": "invalid_request",
      "condition": "Idempotency-Key is missing or the body contains the caller-forbidden source_id field"
    },
    {
      "status": 409,
      "code": "idempotency_conflict",
      "condition": "the same Idempotency-Key is bound to a different canonical request"
    }
  ]
}
```

`source_id` is an opaque identity generated by the server. The durable Source Create idempotency identity is
`(create_source, scope_id, source_type, Idempotency-Key)`. On the first request, the server atomically persists the
canonical request digest, generated `source_id`, journal position, and successful result. Replaying the same key and
canonical request returns the same `201 SourceRecord`, `Location`, and `position` without appending to the journal.
Binding the same key to a different canonical request returns `409 idempotency_conflict`. The binding is as durable as
the Source, so the key cannot later create another Source in the same Scope and Source type.

`Idempotency-Key` controls Create retries only. It is not part of `SourceReference` and is not used by Get, List, or
Search. The server must not deduplicate Sources by `content_digest`, because identical content may represent distinct
evidence events.

Existing `POST /v1/sources/content` remains a strongly typed compatibility facade. Its request continues to take a
caller-supplied `source_id`, while the shared `SourceReference` response field changes from `name` to `source_type`:

```json
{
  "operation_id": "capture_content_source",
  "request": {
    "method": "POST",
    "path": "/v1/sources/content",
    "headers": {
      "Content-Type": "application/json"
    },
    "body": {
      "required_fields": [
        "scope_id",
        "source_id",
        "content"
      ],
      "optional_fields": [
        "metadata"
      ],
      "example": {
        "scope_id": "git:github.com/acme/payments",
        "source_id": "upstream-refund-rule-001",
        "content": "Refunds require manual review.",
        "metadata": {
          "title": "Refund constraint",
          "media_type": "text/plain"
        }
      }
    }
  },
  "success": {
    "status": 202,
    "schema": "CaptureContentSourceResponse",
    "body": {
      "status": "accepted",
      "source": {
        "source_type": "content",
        "source_id": "upstream-refund-rule-001"
      },
      "position": 42
    }
  }
}
```

After resolving Source identity, both operations reuse the same durable write capability, but the identity source and
HTTP responses differ. The new operation binds a server-generated `source_id` to `Idempotency-Key` and returns
`201 SourceRecord`. The compatibility operation uses the caller-supplied `source_id` and returns
`202 CaptureContentSourceResponse`. Its stable identity is `(scope_id, source_type="content", source_id)`; replaying
that identity with the same canonical payload returns the original result without advancing the journal position, while
a different payload preserves the existing `409 source_conflict` behavior.

### Source get contract and example

```json
{
  "operation_id": "get_source",
  "request": {
    "method": "GET",
    "path": "/v1/sources/{source_id}",
    "path_parameters": {
      "required": [
        "source_id"
      ],
      "example": {
        "source_id": "src_01J..."
      }
    },
    "query_parameters": {
      "required": [
        "scope_id",
        "source_type"
      ],
      "example": {
        "scope_id": "git:github.com/acme/payments",
        "source_type": "content"
      }
    }
  },
  "success": {
    "status": 200,
    "schema": "SourceRecord",
    "body": {
      "scope_id": "git:github.com/acme/payments",
      "source_ref": {
        "source_type": "content",
        "source_id": "src_01J..."
      },
      "content": "Refunds require manual review.",
      "metadata": {
        "title": "Refund constraint",
        "media_type": "text/plain"
      },
      "created_at": "2026-09-01T04:00:00Z",
      "position": 42,
      "content_digest": "sha256:..."
    }
  },
  "errors": [
    {
      "status": 404,
      "code": "source_not_found"
    }
  ]
}
```

### Source list contract and example

```json
{
  "operation_id": "list_sources",
  "request": {
    "method": "GET",
    "path": "/v1/sources",
    "query_parameters": {
      "required": [
        "scope_id",
        "source_type"
      ],
      "optional": [
        "limit",
        "cursor",
        "created_after",
        "created_before"
      ],
      "example": {
        "scope_id": "git:github.com/acme/payments",
        "source_type": "content",
        "limit": 50
      }
    }
  },
  "success": {
    "status": 200,
    "schema": "SourcePage",
    "body": {
      "items": [
        {
          "scope_id": "git:github.com/acme/payments",
          "source_ref": {
            "source_type": "content",
            "source_id": "src_01J..."
          },
          "metadata": {
            "title": "Refund constraint"
          },
          "created_at": "2026-09-01T04:00:00Z",
          "position": 42,
          "content_digest": "sha256:..."
        }
      ],
      "next_cursor": null
    }
  }
}
```

### Source search contract and example

```json
{
  "operation_id": "search_sources",
  "request": {
    "method": "GET",
    "path": "/v1/source-search-results",
    "query_parameters": {
      "required": [
        "scope_id",
        "source_type"
      ],
      "optional": [
        "q",
        "mode",
        "limit",
        "cursor",
        "created_after",
        "created_before"
      ],
      "examples": {
        "ranked": {
          "scope_id": "git:github.com/acme/payments",
          "source_type": "content",
          "q": "manual review",
          "mode": "auto",
          "limit": 20
        },
        "without_query": {
          "scope_id": "git:github.com/acme/payments",
          "source_type": "content",
          "created_after": "2026-09-01T00:00:00Z",
          "limit": 20
        }
      },
      "rules": {
        "blank_q": "normalize_to_null",
        "mode_without_q": "omit"
      }
    }
  },
  "success": {
    "status": 200,
    "schema": "SourceSearchResultPage",
    "examples": {
      "ranked": {
        "query": "manual review",
        "mode": "keyword",
        "hits": [
          {
            "source_ref": {
              "source_type": "content",
              "source_id": "src_01J..."
            },
            "metadata": {
              "title": "Refund constraint"
            },
            "created_at": "2026-09-01T04:00:00Z",
            "score": 0.91,
            "snippets": [
              "Refunds require manual review."
            ]
          }
        ],
        "next_cursor": null
      },
      "without_query": {
        "query": null,
        "mode": null,
        "hits": [
          {
            "source_ref": {
              "source_type": "content",
              "source_id": "src_01J..."
            },
            "metadata": {
              "title": "Refund constraint"
            },
            "created_at": "2026-09-01T04:00:00Z",
            "score": null,
            "snippets": []
          }
        ],
        "next_cursor": null
      }
    }
  }
}
```

## Artifact API

The fixed paths apply to future families. A family registers its content schema and supported actions in the
assembled Runtime instead of adding another set of endpoints.

### Artifact create contract and example

```json
{
  "operation_id": "create_artifact",
  "request": {
    "method": "POST",
    "path": "/v1/artifacts",
    "headers": {
      "Content-Type": "application/json"
    },
    "body": {
      "required_fields": [
        "scope_id",
        "family",
        "schema_version",
        "content"
      ],
      "optional_fields": [
        "artifact_id",
        "metadata",
        "source_refs",
        "artifact_refs",
        "idempotency_key"
      ],
      "example": {
        "scope_id": "git:github.com/acme/payments",
        "family": "company.example.decision",
        "artifact_id": "dec_01J...",
        "schema_version": 1,
        "metadata": {
          "title": "Refund manual-review constraint"
        },
        "content": {
          "decision": "Refunds require manual review"
        },
        "source_refs": [
          {
            "source_type": "content",
            "source_id": "src_01J..."
          }
        ],
        "artifact_refs": [],
        "idempotency_key": "idem_01J..."
      }
    }
  },
  "success": {
    "status": 201,
    "schema": "ArtifactRevision",
    "headers": {
      "Location": "/v1/artifacts/dec_01J...?scope_id=git%3Agithub.com%2Facme%2Fpayments&family=company.example.decision",
      "ETag": "revision:1"
    },
    "body": {
      "scope_id": "git:github.com/acme/payments",
      "artifact_ref": {
        "family": "company.example.decision",
        "artifact_id": "dec_01J...",
        "revision": 1
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
          "source_type": "content",
          "source_id": "src_01J..."
        }
      ],
      "artifact_refs": [],
      "created_at": "2026-09-01T04:30:00Z",
      "content_digest": "sha256:..."
    }
  }
}
```

`artifact_id` is optional. When omitted, the Server generates it and returns it through
`artifact_ref.artifact_id` and `Location`. A caller that needs retry-safe Create with a server-generated ID should
provide `idempotency_key`: the same key and canonical request return the same Revision 1 without creating another
Artifact, while a different canonical request returns `409 idempotency_conflict`. Every Create without an
`idempotency_key` is an independent attempt, so a blind retry after a network timeout may create another Artifact.

### Artifact get-current contract and example

```json
{
  "operation_id": "get_artifact",
  "request": {
    "method": "GET",
    "path": "/v1/artifacts/{artifact_id}",
    "path_parameters": {
      "required": [
        "artifact_id"
      ],
      "example": {
        "artifact_id": "dec_01J..."
      }
    },
    "query_parameters": {
      "required": [
        "scope_id",
        "family"
      ],
      "example": {
        "scope_id": "git:github.com/acme/payments",
        "family": "company.example.decision"
      }
    }
  },
  "success": {
    "status": 200,
    "schema": "ArtifactRevision",
    "headers": {
      "ETag": "revision:1"
    },
    "body": {
      "scope_id": "git:github.com/acme/payments",
      "artifact_ref": {
        "family": "company.example.decision",
        "artifact_id": "dec_01J...",
        "revision": 1
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
          "source_type": "content",
          "source_id": "src_01J..."
        }
      ],
      "artifact_refs": [],
      "created_at": "2026-09-01T04:30:00Z",
      "content_digest": "sha256:..."
    }
  },
  "errors": [
    {
      "status": 404,
      "code": "artifact_not_found"
    }
  ]
}
```

### Artifact exact-revision contract and example

```json
{
  "operation_id": "get_artifact_revision",
  "request": {
    "method": "GET",
    "path": "/v1/artifacts/{artifact_id}/revisions/{revision}",
    "path_parameters": {
      "required": [
        "artifact_id",
        "revision"
      ],
      "example": {
        "artifact_id": "dec_01J...",
        "revision": 1
      }
    },
    "query_parameters": {
      "required": [
        "scope_id",
        "family"
      ],
      "example": {
        "scope_id": "git:github.com/acme/payments",
        "family": "company.example.decision"
      }
    }
  },
  "success": {
    "status": 200,
    "schema": "ArtifactRevision",
    "headers": {},
    "body": {
      "scope_id": "git:github.com/acme/payments",
      "artifact_ref": {
        "family": "company.example.decision",
        "artifact_id": "dec_01J...",
        "revision": 1
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
          "source_type": "content",
          "source_id": "src_01J..."
        }
      ],
      "artifact_refs": [],
      "created_at": "2026-09-01T04:30:00Z",
      "content_digest": "sha256:..."
    }
  },
  "errors": [
    {
      "status": 404,
      "code": "artifact_not_found"
    }
  ]
}
```

Exact-revision responses do not carry the current-head ETag. Their committed content remains immutable after a
later replacement or deletion.

### Artifact list contract and example

```json
{
  "operation_id": "list_artifacts",
  "request": {
    "method": "GET",
    "path": "/v1/artifacts",
    "query_parameters": {
      "required": [
        "scope_id",
        "family"
      ],
      "optional": [
        "limit",
        "cursor",
        "created_after",
        "created_before"
      ],
      "example": {
        "scope_id": "git:github.com/acme/payments",
        "family": "company.example.decision",
        "limit": 50
      }
    }
  },
  "success": {
    "status": 200,
    "schema": "ArtifactPage",
    "body": {
      "items": [
        {
          "artifact_ref": {
            "family": "company.example.decision",
            "artifact_id": "dec_01J...",
            "revision": 1
          },
          "schema_version": 1,
          "metadata": {
            "title": "Refund manual-review constraint"
          },
          "created_at": "2026-09-01T04:30:00Z",
          "content_digest": "sha256:..."
        }
      ],
      "next_cursor": null
    }
  }
}
```

### Artifact search contract and example

```json
{
  "operation_id": "search_artifacts",
  "request": {
    "method": "GET",
    "path": "/v1/artifact-search-results",
    "query_parameters": {
      "required": [
        "scope_id",
        "family"
      ],
      "optional": [
        "q",
        "mode",
        "limit",
        "cursor",
        "created_after",
        "created_before"
      ],
      "example": {
        "scope_id": "git:github.com/acme/payments",
        "family": "company.example.decision",
        "q": "manual review",
        "mode": "auto",
        "limit": 20
      },
      "rules": {
        "blank_q": "normalize_to_null",
        "mode_without_q": "omit",
        "revision_selection": "current_visible_head"
      }
    }
  },
  "success": {
    "status": 200,
    "schema": "ArtifactSearchResultPage",
    "body": {
      "query": "manual review",
      "mode": "keyword",
      "hits": [
        {
          "artifact_ref": {
            "family": "company.example.decision",
            "artifact_id": "dec_01J...",
            "revision": 1
          },
          "metadata": {
            "title": "Refund manual-review constraint"
          },
          "score": 0.94,
          "snippets": [
            "Refunds require manual review"
          ]
        }
      ],
      "next_cursor": null
    },
    "without_query": {
      "query": null,
      "mode": null,
      "score": null,
      "snippets": []
    }
  }
}
```

### Artifact replace contract and example

```json
{
  "operation_id": "replace_artifact",
  "request": {
    "method": "PUT",
    "path": "/v1/artifacts/{artifact_id}",
    "path_parameters": {
      "required": [
        "artifact_id"
      ],
      "example": {
        "artifact_id": "dec_01J..."
      }
    },
    "query_parameters": {
      "required": [
        "scope_id",
        "family"
      ],
      "example": {
        "scope_id": "git:github.com/acme/payments",
        "family": "company.example.decision"
      }
    },
    "headers": {
      "required": [
        "Content-Type",
        "If-Match"
      ],
      "example": {
        "Content-Type": "application/json",
        "If-Match": "revision:1"
      }
    },
    "body": {
      "semantics": "complete_replacement",
      "required_fields": [
        "schema_version",
        "content"
      ],
      "optional_fields": [
        "metadata",
        "source_refs",
        "artifact_refs",
        "idempotency_key"
      ],
      "example": {
        "schema_version": 1,
        "metadata": {
          "title": "Refund manual-review constraint"
        },
        "content": {
          "decision": "Refunds require manual review",
          "rationale": "Satisfy funds-safety requirements"
        },
        "source_refs": [
          {
            "source_type": "content",
            "source_id": "src_01J..."
          }
        ],
        "artifact_refs": [],
        "idempotency_key": "idem_01K..."
      }
    }
  },
  "success": {
    "status": 200,
    "schema": "ArtifactRevision",
    "headers": {
      "ETag": "revision:2"
    },
    "body": {
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
        "decision": "Refunds require manual review",
        "rationale": "Satisfy funds-safety requirements"
      },
      "source_refs": [
        {
          "source_type": "content",
          "source_id": "src_01J..."
        }
      ],
      "artifact_refs": [],
      "created_at": "2026-09-01T04:45:00Z",
      "content_digest": "sha256:..."
    }
  },
  "errors": [
    {
      "status": 428,
      "code": "precondition_required"
    },
    {
      "status": 412,
      "code": "revision_conflict",
      "body": {
        "error": {
          "code": "revision_conflict",
          "message": "Artifact ETag does not match the current head",
          "details": {
            "provided_etag": "revision:1",
            "current_etag": "revision:2"
          }
        }
      }
    }
  ],
  "rules": {
    "creates_next_revision": true,
    "historical_revisions_immutable": true,
    "merge_patch_supported": false,
    "automatic_merge": false
  }
}
```

### Artifact delete contract and example

```json
{
  "operation_id": "delete_artifact",
  "request": {
    "method": "DELETE",
    "path": "/v1/artifacts/{artifact_id}",
    "path_parameters": {
      "required": [
        "artifact_id"
      ],
      "example": {
        "artifact_id": "dec_01J..."
      }
    },
    "query_parameters": {
      "required": [
        "scope_id",
        "family"
      ],
      "example": {
        "scope_id": "git:github.com/acme/payments",
        "family": "company.example.decision"
      }
    },
    "headers": {
      "required": [
        "If-Match"
      ],
      "example": {
        "If-Match": "revision:2"
      }
    }
  },
  "success": {
    "status": 200,
    "schema": "ArtifactDeletionStatus",
    "body": {
      "artifact_ref": {
        "family": "company.example.decision",
        "artifact_id": "dec_01J...",
        "revision": 2
      },
      "status": "deleted",
      "deleted_at": "2026-09-01T05:00:00Z"
    }
  },
  "errors": [
    {
      "status": 428,
      "code": "precondition_required"
    },
    {
      "status": 412,
      "code": "revision_conflict"
    },
    {
      "status": 405,
      "code": "operation_not_supported"
    }
  ],
  "rules": {
    "deletion_mode": "lifecycle_tombstone",
    "physical_revision_erasure": false,
    "hidden_from_head_get_list_search_context": true,
    "historical_lineage_verifiable": true,
    "idempotent_for_same_revision": true,
    "same_if_match_replay": "return the original 200 deletion receipt without writing another tombstone",
    "different_if_match_after_delete": "412 revision_conflict",
    "restore_supported": false,
    "purge_supported": false,
    "family_must_enable_delete": true
  }
}
```

## Pagination and search

Collection responses use a stable `next_cursor`. A cursor is bound to the caller identity, authorization context,
request endpoint, Scope, Source type or Artifact family, normalized query text, filters, ordering, and actual search
mode. A cursor cannot be reused after any of those values changes.

List returns typed resource collections without ranking metadata:

```json
{
  "items": [],
  "next_cursor": null
}
```

Source and Artifact Search each use a separate, virtual, read-only result collection. A search hit is not a
persisted resource and cannot be fetched or mutated independently; it points to the exact underlying Source or
Artifact and may add score and snippet metadata:

```json
{
  "query": "refund manual review",
  "mode": "keyword",
  "hits": [],
  "next_cursor": null
}
```

For both Search endpoints, `q` is optional. An omitted, empty, or whitespace-only query is normalized to
`query: null`; the caller omits `mode`, the response reports `mode: null`, hits use deterministic fallback ordering,
scores are null, and snippets are empty. A nonblank query reports the normalized query and actual search mode.

## Family capability and lifecycle boundaries

A fixed Artifact path does not imply that every family accepts direct writes:

```json
[
  {
    "family_kind": "direct",
    "capabilities": {
      "create": "commit_revision_1",
      "get_list_search": "committed_revision_and_head",
      "replace": "commit_next_revision",
      "delete": "available_when_declared"
    }
  },
  {
    "family_kind": "review",
    "examples": [
      "experience",
      "managed_skill"
    ],
    "capabilities": {
      "create": {
        "supported": false,
        "status": 405,
        "code": "operation_not_supported",
        "required_workflow": "propose_review"
      },
      "get_list_search": "approved_or_committed_artifact_only",
      "replace": {
        "supported": false,
        "status": 405,
        "code": "operation_not_supported",
        "required_workflow": "candidate_revision_and_review"
      },
      "delete": "disabled_by_default"
    }
  },
  {
    "family_kind": "memory",
    "capabilities": {
      "create": "use_memory_commands",
      "get_list_search": "artifact_reads_do_not_replace_memory_entry_apis",
      "replace": "disabled; entry_revision_retains_its_own_cas",
      "delete": "disabled"
    }
  },
  {
    "family_kind": "handoff",
    "capabilities": {
      "create": "use_prepare_finalize_commit",
      "get_list_search": "committed_handoff_only",
      "replace": "disabled",
      "delete": "disabled"
    }
  }
]
```

Candidate is not an Artifact. Pending and rejected Candidates never appear in Artifact list/search. Only an approved
Candidate whose result was committed can be read as an Artifact.

`/v1/capabilities` should report the actions supported by each Source type and Artifact family. Callers must not
assume every assembled deployment supports every mutation.

## Error model

The operations reuse the existing error envelope and stabilize these codes:

```json
[
  {
    "http_status": [
      400,
      422
    ],
    "code": "invalid_request",
    "meaning": "missing scope_id or required Idempotency-Key, invalid fields, a caller-supplied source_id in Source Create, or an invalid search/cursor combination"
  },
  {
    "http_status": 401,
    "code": "unauthorized",
    "meaning": "authentication is required"
  },
  {
    "http_status": 403,
    "code": "forbidden",
    "meaning": "the authenticated caller lacks mutation authority"
  },
  {
    "http_status": 404,
    "code": [
      "source_not_found",
      "artifact_not_found"
    ],
    "meaning": "the object is absent or invisible"
  },
  {
    "http_status": 405,
    "code": "operation_not_supported",
    "meaning": "the action is unsupported or would bypass review"
  },
  {
    "http_status": 409,
    "code": "idempotency_conflict",
    "meaning": "an operation that supports idempotency keys bound the same key to a different canonical request; this includes the new Source Create operation"
  },
  {
    "http_status": 409,
    "code": "source_conflict",
    "meaning": "the same caller-supplied identity for the compatibility Source capture operation was bound to a different canonical payload"
  },
  {
    "http_status": 412,
    "code": "revision_conflict",
    "meaning": "If-Match does not identify the current Artifact head"
  },
  {
    "http_status": 428,
    "code": "precondition_required",
    "meaning": "replace or delete omitted If-Match"
  },
  {
    "http_status": 422,
    "code": "schema_validation_failed",
    "meaning": "content does not match the registered Source or Artifact Family schema"
  },
  {
    "http_status": 503,
    "code": "capability_unavailable",
    "meaning": "a declared backend is temporarily unavailable"
  }
]
```

## Existing API overlap and compatibility

```json
[
  {
    "new_api": "POST /v1/sources",
    "existing_api": [
      "POST /v1/sources/content",
      "capture_content_source"
    ],
    "relationship": "reuse the durable Source write with different identity inputs and HTTP responses",
    "compatibility_rule": "the new API requires Idempotency-Key, generates source_id, and returns 201 SourceRecord; the compatibility API still accepts source_id and returns 202 CaptureContentSourceResponse"
  },
  {
    "new_api": "Source Get/List/Search",
    "existing_api": null,
    "relationship": "new generic read surface",
    "compatibility_rule": "read the same Source journal and projection"
  },
  {
    "new_api": "Artifact Head/Revision Get",
    "existing_api": [
      "/v1/experience/get",
      "/v1/skill/get",
      "other typed read APIs"
    ],
    "relationship": "overlapping read semantics",
    "compatibility_rule": "delegate to one application service; the base API returns an exact revision and typed responses remain available"
  },
  {
    "new_api": "Artifact List/Search",
    "existing_api": [
      "Memory Entry List",
      "Memory Entry Search"
    ],
    "relationship": "different identity level",
    "compatibility_rule": "Artifact APIs operate on heads; Memory Entry APIs retain entry identity, citation, and ranking"
  },
  {
    "new_api": "Artifact Replace",
    "existing_api": [
      "Candidate revise",
      "Memory Entry revise"
    ],
    "relationship": "different lifecycle",
    "compatibility_rule": "never bypass review or represent an Entry mutation as a whole Artifact replacement"
  },
  {
    "new_api": "Artifact Delete",
    "existing_api": [
      "Memory retire",
      "other Family lifecycle commands"
    ],
    "relationship": "different lifecycle",
    "compatibility_rule": "only a Family that explicitly enables Delete accepts the generic operation"
  },
  {
    "new_api": "Source Create followed by Memory Flush",
    "existing_api": [
      "/v1/memory/flush"
    ],
    "relationship": "reuses an existing command",
    "compatibility_rule": "adds no combined server parameter or response"
  }
]
```

No current domain endpoint is removed or deprecated by this RFC. The shared wire model is nevertheless a breaking
field rename: every `SourceReference.name` becomes `SourceReference.source_type` in the same OpenAPI change. Parity
tests ensure overlapping entries resolve to the same durable Source or Artifact revision, digest, lineage,
authorization result, and error semantics.

## OpenAPI and implementation

`openapi/powercontext.yaml` remains the sole HTTP contract. Generated models and operation metadata are checked in,
and Client methods encode path segments, query values, and `If-Match` without adding family-specific methods.

```json
{
  "contract_source": "openapi/powercontext.yaml",
  "schemas": [
    "SourceReference",
    "SourceRecord",
    "CreateSourceRequest",
    "SourceSummary",
    "SourcePage",
    "SourceSearchHit",
    "SourceSearchResultPage",
    "ArtifactRevision",
    "ArtifactSummary",
    "ArtifactPage",
    "CreateArtifactRequest",
    "ReplaceArtifactRequest",
    "ArtifactSearchHit",
    "ArtifactSearchResultPage",
    "ArtifactDeletionStatus"
  ],
  "headers": {
    "response": [
      "ETag"
    ],
    "request": [
      "Idempotency-Key",
      "If-Match"
    ]
  },
  "scope_schema_owner": "PR #1401"
}
```

The persistence implementation uses the existing Source journal, Artifact revision table, Artifact head table, and
lineage tables. Timestamp, digest, schema metadata, and deletion state may use compatible side tables so existing
databases do not require destructive column rewrites. Historical rows without optional projected metadata remain
readable. SQLite and OceanBase must pass the same behavioral contract.

The implementation sequence is:

1. rename the shared `SourceReference.name` field to `source_type` in OpenAPI and migrate Server mapping, generated
   Clients, CLI, web UI, and contract tests together;
2. add Source create/get/list and the Source search-result collection, with required `Idempotency-Key` and a
   server-generated `source_id` for Create;
3. add the Artifact paths and schemas to OpenAPI and regenerate Python and JavaScript operation bindings;
4. add shared Source/Artifact application services and route overlapping reads/writes through them;
5. add cursor, optimistic concurrency, tombstone, family-capability, and durable idempotency behavior;
6. add Client methods and contract, persistence, server, and end-to-end tests.

## Acceptance criteria

| Scenario | Required behavior |
| --- | --- |
| No umbrella concept | no shared Source/Artifact selector, union request/response, or kind field |
| No write-time generation | Source create carries and returns only durable Source state |
| Source operations | only create/get/list/search are exposed |
| Source list/search | `GET /v1/sources` uses `list_sources`; `GET /v1/source-search-results` uses `search_sources`; there is no `type` dispatcher and `q` is optional for Search |
| Artifact operations | fixed create/get/list/search/replace/delete paths; replace commits an immutable next revision |
| Exact identity | SourceReference is `{source_type, source_id}` with no revision; every Artifact response has an exact revision |
| Server-generated Source identity | `POST /v1/sources` rejects `source_id`; the server returns an opaque ID in the body and `Location` |
| Source Create idempotency | `Idempotency-Key` is required; the same key/request returns the same Source and position, while a different request returns `409 idempotency_conflict` |
| Scope required | every Source/Artifact operation names one `scope_id` |
| Scope dependency | this RFC defines no Scope API; all operations use a `scope_id` supplied by the PR #1401 Scope API |
| Pagination | cursors are stable and bound to the endpoint, complete query, and authorization context |
| Concurrency | replace/delete require current ETag; missing is `428`, stale is `412` |
| Review gate | Review families cannot be mutated through direct Artifact operations |
| Memory boundary | Source create and Memory flush are separate; flush processes a bounded pending window |
| Compatibility | existing paths, operations, and domain behavior remain; every shared SourceReference wire field migrates from `name` to `source_type` |
| Source Create compatibility | the new operation generates the ID and returns `201`; `/v1/sources/content` keeps caller-supplied IDs and `202`, with `409 source_conflict` for a different payload |
| Extensibility | adding a direct Artifact family adds no base path or generated Client method |

# Drawbacks

- Base Artifact content is generic JSON in generated clients, so a typed family endpoint remains more ergonomic.
- Old and new read paths coexist and require shared services plus parity tests to prevent drift.
- Direct and reviewed families support different mutations, so clients must inspect capabilities.
- Logical deletion must remain compatible with lineage validation and retention.
- Source create and Memory flush are not one transaction; callers must handle a durable Source followed by a
  retryable flush failure.
- Renaming `SourceReference.name` to `source_type` is a breaking field change that requires generated Clients and all
  callers to migrate together.
- Source and Artifact each add a dedicated search-result collection and response schema. This slightly enlarges the
  OpenAPI surface but keeps generated Client methods and return types explicit and symmetric.

# Future possibilities

- subject and group grants for read/write sharing built on exact Scope and publication semantics;
- cross-type or cross-family search with an explicit ranking and cursor contract;
- Artifact restore, retention, administrator purge, and bulk mutations;
- a Client convenience method that sequentially creates a Source and flushes Memory without changing the server
  contract.
