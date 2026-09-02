- Proposal Name: `source_artifact_rest_api`
- Start Date: 2026-09-01
- RFC PR: [oceanbase/powercontext#0000](https://github.com/oceanbase/powercontext/pull/0000)

# Summary

本 RFC 为 PowerContext 增加两组彼此独立的基础 HTTP API：

- Source：`create`、`get`、`list`、`search`；
- Artifact：`create`、`get`、`list`、`search`、`replace`、`delete`。

API 直接复用 PowerContext 已有的 Source、Artifact、Artifact Revision 和 Scope 语义，不增加二者之上的统一对象概念，不增加统一 selector、联合引用、统一 envelope、类型注册接口或跨类型 List/Search。Scope 的创建、查询、组织与 binding 由 [PR #1401](https://github.com/oceanbase/powercontext/pull/1401) 定义，本 RFC 只把调用方已经取得的 `scope_id` 作为 Source/Artifact 请求边界。

写入和生成仍是两个独立提交边界。Source Create 只返回 Source 的耐久写入结果，不携带生成参数或联合生成结果。需要“写入 Source 后立即生成 Memory 并等待结果”的调用方，顺序调用 `POST /v1/sources` 与现有 `POST /v1/memory/flush` 即可。

接口遵守以下约定：

- Source 资源路径固定为 `/v1/sources`，Artifact 资源路径固定为 `/v1/artifacts`，搜索结果路径固定为
  `/v1/source-search-results` 与 `/v1/artifact-search-results`；
- `GET` 用于读取、列举和搜索，`POST` 用于创建，`PUT` 用于完整替换 Artifact head，`DELETE` 用于删除；
- Artifact 历史 Revision 不可变；`PUT` 替换当前 head 时，Runtime 在内部创建下一 Revision，而不是覆盖历史 Revision；
- List 使用 `items + next_cursor`，继续遵守 PowerContext 当前的 snake_case 与 cursor 约定。

# Motivation

PowerContext 当前主要按领域动作暴露接口，例如 Source capture、Memory flush、Experience/Skill generate、Candidate review 和 Handoff workflow。这些接口准确表达了领域不变量，但仍缺少一致、可预测的 Source 与 Artifact 基础访问方式。

目标用户需要的基础能力是：

- 按 Scope 创建和读取 Source；
- 按 Scope 列举、搜索 Source；
- 按 Scope 创建、读取、列举、搜索、修订和删除 Artifact；
- 新增 Artifact Family 时继续复用同一组 HTTP path 和 generated Client method；
- 需要写入后立即生成时，由客户端编排 Source Create 与 Family command，而不是让基础写接口隐式调用模型。

# Goals

- 直接以 Source 与 Artifact 建模，不增加统一上层概念。
- 保持 `SourceReference` 无 Revision、`ArtifactReference` 必须包含 Revision。
- 为未来 Artifact Family 提供固定的基础 API surface。
- 使用 REST 风格的名词路径和 HTTP 方法。
- 保留现有领域命令及 Candidate Review 边界。
- 为 Source 与 Artifact 定义清晰的请求元数据、返回格式、分页、并发与错误语义。
- 保持 `openapi/powercontext.yaml` 为 HTTP 契约唯一真相。

# Non-goals

- 不增加写入时同步生成参数、服务端组合接口或生成任务模型。
- 不提供跨 Source type、跨 Artifact Family 或 Source/Artifact 混合 List/Search。
- 不把 Candidate、Memory Entry、Handoff Draft 重新定义为 Artifact。
- 不替代 Memory、Experience、Skill、Handoff 和 Candidate 的领域命令。
- 不在本 RFC 中设计跨 Scope 共享、RBAC/ACL、恢复、物理清除或批量操作。
- 不要求所有 Artifact Family 绕过其既有 Review 或生命周期约束。

# Domain model

## Source

Source 是耐久证据。精确身份复用现有 `SourceReference`：

```json
{
  "name": "content",
  "source_id": "refund-rule-001"
}
```

其中 `name` 是当前 OpenAPI 中的稳定 Source type。HTTP path 与请求字段使用更直观的变量名 `source_type`，但 response 继续复用 `SourceReference{name, source_id}`，不再增加一份平行类型字段。

Source 没有 Revision。本 RFC 不提供 Source Replace/Delete：

- 元数据或正文修正应写入一个新的 Source，并通过既有 provenance/关系能力表达替代关系；
- 已被 Artifact lineage 引用的证据不能被普通 CRUD 原地覆盖或删除。

## Artifact

Artifact 是可提交、可演进的正式制品。精确身份复用现有 `ArtifactReference`：

```json
{
  "family": "experience",
  "artifact_id": "exp_01J...",
  "revision": 3
}
```

Revision 是 Artifact 身份的一部分，也是并发前置条件。Create 生成 Revision 1；Replace 校验当前 head 后创建下一 Revision；任何操作都不得原地覆盖历史 Revision。

## Scope dependency

`scope_id` 是 Source 与 Artifact 的隔离和查询边界，不是 Source，也不是 Artifact。Scope 的创建、读取、列举、metadata、Organization Parent、Context References 与 binding 均由 [PR #1401](https://github.com/oceanbase/powercontext/pull/1401) 的 Scope API 负责。本 RFC 不重复声明任何 Scope path、operationId、schema、分页或授权规则；调用方先通过该 API 获得 `scope_id`，再调用本文定义的 Source/Artifact API。

# REST API conventions

## 基础操作、HTTP 方法与 URL

基础操作的 wire-level 契约固定如下：

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

`operation_id`、HTTP 方法和 URL 格式以 JSON 定义为准，共同构成基础 API 的 wire contract。

## PowerContext HTTP 接口约束

- 集合路径与具名对象路径分离；
- `GET` 资源 collection 表示 List，`GET` search-result collection 表示 Search，`POST` 资源 collection 表示 Create；
- `GET` named object 表示 Read，`DELETE` named object 表示 Delete；
- 子对象使用子集合表达；
- List 返回 typed items 和分页元数据；
- `PUT` 只接受完整 replacement；Artifact Replace/Delete 必须通过 `If-Match` 携带当前 head 的 ETag，不能静默覆盖并发写入；
- response 直接复用 `SourceReference`、`ArtifactReference`、Artifact Revision 和 Source journal position；
- `scope_id` 使用 query parameter 或 request body；GET/DELETE 使用 query parameter，POST/PUT 使用 request body；
- 基础集合固定为 `/v1/sources` 与 `/v1/artifacts`，`source_type` / `family` 使用 request body 或 query parameter；
- 字段名继续使用现有 snake_case；
- Scope identity 与可见性由 PR #1401 的 Scope API 负责；本文不从 Source/Artifact 数据反向推导或列举 Scope。

所有 path parameter 必须按 RFC 3986 编码并由服务端只解码一次。`source_type`、`family` 与 `scope_id` 不作为 path parameter；`source_id` 和 `artifact_id` 应优先使用 path-segment-safe 值。

# Common response conventions

## Source 返回对象

```json
{
  "scope_id": "git:github.com/acme/payments",
  "source_ref": {
    "name": "content",
    "source_id": "refund-rule-001"
  },
  "content": "退款流程必须保留人工复核。",
  "metadata": {
    "title": "退款流程约束",
    "media_type": "text/plain"
  },
  "created_at": "2026-09-01T04:00:00Z",
  "position": 42,
  "content_digest": "sha256:..."
}
```

```json
{
  "schema": "SourceRecord",
  "field_semantics": {
    "scope_id": "Source 所属 Scope；所有 Get、List、Search 必须显式关联",
    "source_ref": "现有精确 SourceReference；不包含 Revision",
    "content": "Source type 对应的权威内容；content type 首期为 string",
    "metadata": "来源、标题、媒体类型等 Source-specific 元数据；保持可扩展对象",
    "created_at": "服务端耐久接收时间",
    "position": "Source journal position；可用于判断 Memory flush 是否已经越过该 Source",
    "content_digest": "canonical content 的摘要，用于审计与幂等校验"
  }
}
```

## Artifact Revision 返回对象

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
    "title": "退款人工复核约束"
  },
  "content": {
    "decision": "退款必须经过人工复核"
  },
  "source_refs": [
    {
      "name": "content",
      "source_id": "refund-rule-001"
    }
  ],
  "artifact_refs": [],
  "created_at": "2026-09-01T04:30:00Z",
  "content_digest": "sha256:..."
}
```

```json
{
  "schema": "ArtifactRevision",
  "field_semantics": {
    "scope_id": "Artifact 所属 Scope",
    "artifact_ref": "现有精确 ArtifactReference，必须包含 Revision",
    "schema_version": "Family content schema 版本",
    "metadata": "标题、标签等非内容字段；具体约束由 Family 定义",
    "content": "Family-specific JSON content",
    "source_refs": "直接 Source evidence，必须是精确 SourceReference",
    "artifact_refs": "直接 Artifact evidence，必须是精确 ArtifactReference",
    "created_at": "当前 Revision 的提交时间",
    "content_digest": "当前 Revision canonical content 的摘要"
  }
}
```

Artifact Revision 已经承担并发前置条件的用途，因此不再增加第二个通用版本字段。

Artifact head response 使用标准 `ETag` header 暴露当前 Revision；`PUT` 与 `DELETE` 通过 `If-Match` 回传该值：

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

缺少 `If-Match` 返回 `428 Precondition Required`；ETag 已过期返回 `412 Precondition Failed`。成功创建或替换 head 后，response 返回新 ETag。

## 分页与搜索结果集合

List 读取资源集合，返回不带排名语义的 `SourcePage{items,next_cursor}` 或 `ArtifactPage{items,next_cursor}`。Search 读取独立的虚拟、只读搜索结果集合：

- `GET /v1/source-search-results` 返回 `SourceSearchResultPage{query,mode,hits,next_cursor}`；
- `GET /v1/artifact-search-results` 返回 `ArtifactSearchResultPage{query,mode,hits,next_cursor}`。

“搜索结果集合”不是另一份持久化 Source/Artifact，也没有可单独 Get、Create、Update 或 Delete 的搜索结果对象。它只是一次查询产生的命中视图；每个 hit 都携带原始资源的精确引用以及可选的 `score`、`snippets`。

两个 Search API 的 `q` 都是可选参数。`q` 缺省、空字符串或仅含空白时统一归一化为 `query=null`，仅应用结构化过滤条件并按稳定默认顺序返回命中；此时调用方应省略 `mode`，response 中 `mode=null`，hit 的 `score=null`、`snippets=[]`。提供非空 `q` 时，response 返回归一化 query、实际执行 mode，并可返回排名与摘要：

```json
{
  "query": "退款 人工复核",
  "mode": "keyword",
  "hits": [],
  "next_cursor": null
}
```

Cursor 必须绑定调用方身份与授权上下文、请求 endpoint、`scope_id`、`source_type/family`、归一化 `q`、过滤器、排序和实际搜索模式。任一条件变化后不能复用旧 cursor。

# Source API

Source 首期公开 Create、Get、List、Search。每次查询只处理一个 `scope_id` 与一个 `source_type`。

List 与 Search 使用不同 path、operationId 和 response schema。`GET /v1/sources` 永远是 `list_sources`，不接受 `type`、`q` 或 `mode`；`GET /v1/source-search-results` 永远是 `search_sources`，不通过参数切换成 List。这样 generated Client 暴露对称且不误导的方法：`list_sources()` / `search_sources()` 与 `list_artifacts()` / `search_artifacts()`。

## Source Create 定义与兼容示例

```json
{
  "operation_id": "create_source",
  "request": {
    "method": "POST",
    "path": "/v1/sources",
    "headers": {
      "Content-Type": "application/json"
    },
    "body": {
      "required_fields": [
        "scope_id",
        "source_type",
        "source_id",
        "content"
      ],
      "optional_fields": [
        "metadata"
      ],
      "example": {
        "scope_id": "git:github.com/acme/payments",
        "source_type": "content",
        "source_id": "refund-rule-001",
        "content": "退款流程必须保留人工复核。",
        "metadata": {
          "title": "退款流程约束",
          "media_type": "text/plain"
        }
      }
    }
  },
  "success": {
    "status": 201,
    "schema": "SourceRecord",
    "headers": {
      "Location": "/v1/sources/refund-rule-001?scope_id=git%3Agithub.com%2Facme%2Fpayments&source_type=content"
    },
    "body": {
      "scope_id": "git:github.com/acme/payments",
      "source_ref": {
        "name": "content",
        "source_id": "refund-rule-001"
      },
      "content": "退款流程必须保留人工复核。",
      "metadata": {
        "title": "退款流程约束",
        "media_type": "text/plain"
      },
      "created_at": "2026-09-01T04:00:00Z",
      "position": 42,
      "content_digest": "sha256:..."
    }
  },
  "errors": [
    {
      "status": 409,
      "code": "idempotency_conflict"
    }
  ]
}
```

现有 `POST /v1/sources/content` 原样保留为 `content` 的强类型兼容 facade：

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
        "source_id": "refund-rule-001",
        "content": "退款流程必须保留人工复核。",
        "metadata": {
          "title": "退款流程约束",
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
        "name": "content",
        "source_id": "refund-rule-001"
      },
      "position": 42
    }
  }
}
```

新旧入口委托同一个持久化 handler，但保留各自 HTTP response：新入口返回 `201 SourceRecord`，兼容入口返回现有 `202 CaptureContentSourceResponse`。相同 `scope_id + source_type + source_id` 与相同 canonical payload 重放时返回原幂等结果；相同身份但 payload 不同返回 `409 idempotency_conflict`。

## Source Get 定义与示例

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
        "source_id": "refund-rule-001"
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
        "name": "content",
        "source_id": "refund-rule-001"
      },
      "content": "退款流程必须保留人工复核。",
      "metadata": {
        "title": "退款流程约束",
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

## Source List 定义与示例

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
            "name": "content",
            "source_id": "refund-rule-001"
          },
          "metadata": {
            "title": "退款流程约束"
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

## Source Search 定义与示例

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
          "q": "refund manual review",
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
        "query": "refund manual review",
        "mode": "keyword",
        "hits": [
          {
            "source_ref": {
              "name": "content",
              "source_id": "refund-rule-001"
            },
            "metadata": {
              "title": "退款流程约束"
            },
            "created_at": "2026-09-01T04:00:00Z",
            "score": 0.91,
            "snippets": [
              "退款流程必须保留人工复核。"
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
              "name": "content",
              "source_id": "refund-rule-001"
            },
            "metadata": {
              "title": "退款流程约束"
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

# Artifact API

Artifact 基础接口对未来 Family 使用固定 path。新增 Family 只需在 assembled Runtime 注册 Family implementation、content schema 与能力，不增加新的基础 HTTP path 或 generated Client method。

## Artifact Create 定义与示例

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
          "title": "退款人工复核约束"
        },
        "content": {
          "decision": "退款必须经过人工复核"
        },
        "source_refs": [
          {
            "name": "content",
            "source_id": "refund-rule-001"
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
        "title": "退款人工复核约束"
      },
      "content": {
        "decision": "退款必须经过人工复核"
      },
      "source_refs": [
        {
          "name": "content",
          "source_id": "refund-rule-001"
        }
      ],
      "artifact_refs": [],
      "created_at": "2026-09-01T04:30:00Z",
      "content_digest": "sha256:..."
    }
  }
}
```

## Artifact Get current 定义与示例

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
        "title": "退款人工复核约束"
      },
      "content": {
        "decision": "退款必须经过人工复核"
      },
      "source_refs": [
        {
          "name": "content",
          "source_id": "refund-rule-001"
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

## Artifact Get exact Revision 定义与示例

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
        "title": "退款人工复核约束"
      },
      "content": {
        "decision": "退款必须经过人工复核"
      },
      "source_refs": [
        {
          "name": "content",
          "source_id": "refund-rule-001"
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

精确 Revision response 不携带 head ETag；即使该 Artifact 后续被替换或删除，已提交 Revision 的内容仍不可变。

## Artifact List 定义与示例

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
            "title": "退款人工复核约束"
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

## Artifact Search 定义与示例

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
        "q": "refund manual review",
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
      "query": "refund manual review",
      "mode": "keyword",
      "hits": [
        {
          "artifact_ref": {
            "family": "company.example.decision",
            "artifact_id": "dec_01J...",
            "revision": 1
          },
          "metadata": {
            "title": "退款人工复核约束"
          },
          "score": 0.94,
          "snippets": [
            "退款必须经过人工复核"
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

## Artifact Replace 定义与示例

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
          "title": "退款人工复核约束"
        },
        "content": {
          "decision": "退款必须经过人工复核",
          "rationale": "满足资金安全要求"
        },
        "source_refs": [
          {
            "name": "content",
            "source_id": "refund-rule-001"
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
        "title": "退款人工复核约束"
      },
      "content": {
        "decision": "退款必须经过人工复核",
        "rationale": "满足资金安全要求"
      },
      "source_refs": [
        {
          "name": "content",
          "source_id": "refund-rule-001"
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
        "code": "revision_conflict",
        "message": "Artifact ETag does not match the current head",
        "details": {
          "provided_etag": "revision:1",
          "current_etag": "revision:2"
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

## Artifact Delete 定义与示例

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
    "restore_supported": false,
    "purge_supported": false,
    "family_must_enable_delete": true
  }
}
```

# Source Create + Memory Flush

```json
{
  "workflow": "create_source_then_flush_memory",
  "steps": [
    {
      "step": 1,
      "operation_id": "create_source",
      "request": {
        "method": "POST",
        "path": "/v1/sources"
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
  },
  "other_generation_commands": [
    "experience_generate",
    "skill_generate",
    "handoff_prepare"
  ]
}
```

# Family capability and lifecycle boundaries

固定 Artifact path 不意味着每个 Family 都允许直接写入：

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
      "replace": "disabled; entry_revision_retains_two_level_revision_and_cas",
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

当前 `/v1/capabilities` 应扩展为按 `source_type` 和 `artifact family` 声明实际支持的基础动作。调用方不能假设所有部署和所有 Family 都支持全部 mutation。

Candidate 不是 Artifact。pending/rejected Candidate 不进入 Artifact List/Search；只有审批并成功提交后产生的 `result_artifact` 才能通过 Artifact API 读取。

# Error model

基础 API 复用现有统一错误 envelope，并至少稳定以下 code：

```json
[
  {
    "http_status": [
      400,
      422
    ],
    "code": "invalid_request",
    "meaning": "缺少 scope_id、字段非法、Search mode 与请求不兼容，或 cursor 与查询条件不匹配"
  },
  {
    "http_status": 401,
    "code": "unauthorized",
    "meaning": "未认证"
  },
  {
    "http_status": 403,
    "code": "forbidden",
    "meaning": "已认证但无权执行 mutation；具体对象读取优先用 404 防枚举"
  },
  {
    "http_status": 404,
    "code": [
      "source_not_found",
      "artifact_not_found"
    ],
    "meaning": "对象不存在或对调用方不可见"
  },
  {
    "http_status": 405,
    "code": "operation_not_supported",
    "meaning": "Source 或 Artifact Family 不支持该基础动作，或动作会绕过 Review"
  },
  {
    "http_status": 409,
    "code": "idempotency_conflict",
    "meaning": "相同幂等身份对应不同 payload"
  },
  {
    "http_status": 412,
    "code": "revision_conflict",
    "meaning": "If-Match 与当前 Artifact head 的 ETag 不一致"
  },
  {
    "http_status": 428,
    "code": "precondition_required",
    "meaning": "Artifact Replace 或 Delete 缺少 If-Match"
  },
  {
    "http_status": 422,
    "code": "schema_validation_failed",
    "meaning": "Source 或 Artifact Family content 不符合已注册 schema"
  },
  {
    "http_status": 503,
    "code": "capability_unavailable",
    "meaning": "部署声明了能力，但当前 backend 暂不可用"
  }
]
```

# Existing API overlap and compatibility

```json
[
  {
    "new_api": "POST /v1/sources",
    "existing_api": [
      "POST /v1/sources/content",
      "capture_content_source"
    ],
    "relationship": "相同耐久 Source 写入，不同 HTTP response",
    "compatibility_rule": "委托同一个 application service；新接口返回 201 SourceRecord，兼容接口保留 202 CaptureContentSourceResponse"
  },
  {
    "new_api": "Source Get/List/Search",
    "existing_api": null,
    "relationship": "新增通用读取接口",
    "compatibility_rule": "读取同一 Source journal 和 projection"
  },
  {
    "new_api": "Artifact Head/Revision Get",
    "existing_api": [
      "/v1/experience/get",
      "/v1/skill/get",
      "其他强类型读取接口"
    ],
    "relationship": "读取语义重叠",
    "compatibility_rule": "委托同一 application service；基础接口返回精确 Revision，强类型 response 继续可用"
  },
  {
    "new_api": "Artifact List/Search",
    "existing_api": [
      "Memory Entry List",
      "Memory Entry Search"
    ],
    "relationship": "身份层级不同",
    "compatibility_rule": "Artifact API 处理 Artifact head；Memory Entry API 保留 entry identity、citation 与 ranking"
  },
  {
    "new_api": "Artifact Replace",
    "existing_api": [
      "Candidate revise",
      "Memory Entry revise"
    ],
    "relationship": "生命周期不同",
    "compatibility_rule": "不能绕过 Review，也不能把 Entry mutation 表达为整个 Artifact Replace"
  },
  {
    "new_api": "Artifact Delete",
    "existing_api": [
      "Memory retire",
      "其他 Family lifecycle command"
    ],
    "relationship": "生命周期不同",
    "compatibility_rule": "只有显式启用 Delete 的 Family 才接受通用 Delete"
  },
  {
    "new_api": "Source Create + Memory Flush 客户端编排",
    "existing_api": [
      "/v1/memory/flush"
    ],
    "relationship": "复用现有命令",
    "compatibility_rule": "不增加服务端组合参数或组合 response"
  }
]
```

新接口不会删除或立即废弃任何领域 API。双入口必须通过 parity test，验证它们命中同一权威 Source/Artifact Revision、content digest、lineage、授权和错误语义。

# OpenAPI contract

`openapi/powercontext.yaml` 仍是唯一 HTTP 契约真相。实现时新增或复用以下 schema：

```json
{
  "contract_source": "openapi/powercontext.yaml",
  "schemas": [
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
      "If-Match"
    ]
  }
}
```

OpenAPI 还必须声明 `ETag` response header 与 `If-Match` request header。不得增加统一 Source/Artifact union schema、统一 selector 或统一引用 envelope。Family-specific `content` 通过 assembled Runtime 中已注册的 schema 校验；generated Client 将其暴露为 JSON object，强类型体验继续由现有 Family API 提供。

# Implementation plan

1. 在 OpenAPI 中保留 `POST /v1/sources/content`，增加 `POST /v1/sources`、Source Get、`GET /v1/sources` List 与 `GET /v1/source-search-results` Search。
2. 增加 Artifact create、head get、exact revision get、list、search-result、replace 和 delete paths。
3. 建立 Source/Artifact 公共 application services，并让语义一致的既有接口委托它们。
4. 扩展 `/v1/capabilities`，按 Source type / Artifact Family 声明可用动作。
5. 运行 `make api-generate` 与 `make contract-test`，更新 checked-in generated Client。
6. 为 SQLite 与 OceanBase 增加相同的 API behavior、cursor、CAS、授权和幂等测试。
7. 增加 Source Create 后循环 Memory Flush 至 cursor 越过 position 的 SDK convenience example；不改变服务端契约。

# Acceptance criteria

| 场景 | 通过条件 |
| --- | --- |
| No umbrella concept | OpenAPI 中没有跨 Source/Artifact 的统一 selector、联合 request/response 或统一资源类型字段 |
| No write-time generation | Source Create request/response 只表达 Source 耐久写入，不包含任何生成参数或生成结果 |
| Source operations | Source 只公开 Create/Get/List/Search，不公开 Replace/Delete |
| Source list/search | `GET /v1/sources` 使用 `list_sources`；`GET /v1/source-search-results` 使用 `search_sources`；不存在 `type` 分流参数，Search 的 `q` 可选 |
| Artifact operations | 固定 path 提供 Create/Get/List/Search/Replace/Delete；Replace 创建下一不可变 Revision |
| REST paths | URL 使用名词；Create 使用 POST，Get/List/Search 使用 GET，完整 Replace 使用 PUT，Delete 使用 DELETE |
| Exact identity | Source 使用无 Revision 的 SourceReference；Artifact head Get 和 exact revision Get 都返回包含 Revision 的 ArtifactReference |
| Scope required | 所有 Source/Artifact Get/List/Search/Mutation 都显式携带 `scope_id` |
| Scope dependency | 本 RFC 不定义 Scope API；所有 Source/Artifact 操作使用由 PR #1401 Scope API 提供的 `scope_id` |
| Pagination | Source 与 Artifact 的 List/Search 使用稳定 cursor，cursor 绑定 endpoint、完整查询和授权上下文 |
| Concurrency | Artifact Replace/Delete 必须携带 current head ETag；缺失返回 `428`，冲突返回 `412 revision_conflict` |
| Review gate | Experience/Skill 等 Review Family 不能通过基础 Create/Replace 绕过 Candidate approval |
| Memory boundary | Source Create + Memory Flush 是两个调用；flush 是 bounded pending window，不宣称 exact single-Source 或 full refresh |
| Compatibility | 现有 Source、Memory、Experience、Skill、Handoff 和 Candidate API 行为不变 |
| Source create compatibility | 新 `POST /v1/sources` 返回 `201 SourceRecord`；现有 `/v1/sources/content` 继续返回 `202 CaptureContentSourceResponse` |
| Extensibility | 新增 Direct Artifact Family 不增加基础 HTTP path 或 generated Client method |
| Conformance | SQLite 与 OceanBase 通过相同 contract 与行为测试 |

# Drawbacks

- Family-specific Artifact `content` 在基础 generated Client 中只能是 JSON object，静态类型弱于强类型 Family API。
- 新旧读取入口会并存一段时间，需要共享 application service 与 parity tests 防止行为漂移。
- Direct Family 与 Review Family 的 mutation capability 不完全一致，调用方必须先读取 capabilities。
- Artifact logical delete、历史 lineage 可验证与 retention 之间仍需 Family 实现正确衔接。
- Source Create + Memory Flush 不是一个事务；客户端必须处理“Source 成功、flush 失败”的可重试状态。
- Source 与 Artifact 各增加一个独立 search-result collection 和 response schema，OpenAPI surface 略有增加，但 generated Client 方法与返回类型保持明确对称。

# Related PowerContext RFCs

- PowerContext RFC 0002：Source、Artifact、不可变 Revision、精确引用与 Core Protocol；
- PowerContext RFC 0011：OpenAPI-first、generated Client 与薄 Server mapping；
- PowerContext RFC 0014：Memory Artifact Revision、Entry lifecycle 与搜索投影；
- PowerContext RFC 0050：Candidate 不是 Artifact，Review Family 不能绕过 approval；
- PowerContext RFC 0051：Experience 与 managed Skill 的 Family identity、Revision、生成与发布边界；
- PowerContext RFC 1345：Scope identity、metadata、Organization Parent、Context References、binding 与 observation selection。

# Future possibilities

- 在 RFC 1345 的 Context Reference 与 exact publication 关系上，另行设计主体/用户组、read/write grant、审计和跨租户共享；
- 在有明确需求后设计跨 type/family Search、统一 ranking 与全局 cursor；
- 为 Artifact 增加 restore、retention、管理员 purge 与批量 mutation；
- 为常用客户端提供 `create_source_and_flush_memory` convenience method，仅做顺序编排，不增加服务端组合接口。
