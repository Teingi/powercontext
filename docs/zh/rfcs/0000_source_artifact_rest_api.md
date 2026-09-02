- Proposal Name: `source_artifact_rest_api`
- Start Date: 2026-09-01
- RFC PR: [oceanbase/powercontext#0000](https://github.com/oceanbase/powercontext/pull/0000)

# Summary

本 RFC 为 PowerContext 增加两组彼此独立的基础 HTTP API：

- Source：`create`、`get`、`list`、`search`；
- Artifact：`create`、`get`、`list`、`search`、`replace`、`delete`。

API 直接复用 PowerContext 已有的 Source、Artifact、Artifact Revision 和 Scope 语义，不增加二者之上的统一对象概念，不增加统一 selector、联合引用、统一 envelope、类型注册接口或跨类型 List/Search。Scope 的创建、查询、组织与 binding 由 [PR #1401](https://github.com/oceanbase/powercontext/pull/1401) 定义，本 RFC 只把调用方已经取得的 `scope_id` 作为 Source/Artifact 请求边界。

写入和生成仍是两个独立提交边界。Source Create 只返回 Source 的耐久写入结果，不携带生成参数或联合生成结果。需要“写入 Source 后立即生成 Memory 并等待结果”的调用方，顺序调用
`POST /v1/scopes/{scope_id}/sources/{source_type}` 与现有 `POST /v1/memory/flush` 即可。

接口遵守以下约定：

- Source 资源位于 `/v1/scopes/{scope_id}/sources/{source_type}`，Artifact 资源位于
  `/v1/scopes/{scope_id}/artifacts/{family}`；具名对象 URI 继续追加 `source_id` 或 `artifact_id`；
- Search 使用 Scope 下独立的 `/v1/scopes/{scope_id}/source-search-results` 与
  `/v1/scopes/{scope_id}/artifact-search-results` 结果集合；
- `GET` 用于读取、列举和搜索，`POST` 用于创建，`PUT` 用于完整替换 Artifact head，`DELETE` 用于删除；
- Artifact 历史 Revision 不可变；`PUT` 替换当前 head 时，Runtime 在内部创建下一 Revision，而不是覆盖历史 Revision；
- List 使用 `items + next_cursor`，继续遵守 PowerContext 当前的 snake_case 与 cursor 约定。
- 本 RFC 新增的基础 Source API 使用 `source_type` 表达 Source 类型；既有 API contract 不在本 RFC 中修改。

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
- 保持 Source 无 Revision、Artifact 的精确引用必须包含 Revision。
- 让新增基础 Source API 的字段名与领域模型 `SourceRef.source_type` 一致，同时不修改任何既有 API schema。
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
- 不修改或重新描述任何既有 API 的 request、response、状态码或幂等语义。
- 不在本 RFC 中设计跨 Scope 共享、RBAC/ACL、恢复、物理清除或批量操作。
- 不要求所有 Artifact Family 绕过其既有 Review 或生命周期约束。

# Domain model

## Source

Source 是耐久证据。新增基础 API 中，`scope_id` 与 `source_ref` 共同表达完整身份：

```json
{
  "source_type": "content",
  "source_id": "src_01J..."
}
```

`source_type` 是稳定的 Source 类型，`source_id` 是该类型下的稳定 Source 标识。Source 表必须以
`(scope_id, source_type, source_id)` 建立联合唯一约束；不能假设 `source_id` 跨 Scope 或跨 Source type 全局唯一：

```json
{
  "table": "sources",
  "unique_key": [
    "scope_id",
    "source_type",
    "source_id"
  ]
}
```

新增基础 API 的 `source_ref` transport shape 直接使用 `{source_type, source_id}`，完整引用仍是 response 顶层的
`scope_id` 与 `source_ref` 组合。该 shape 只属于本 RFC 新增的 schema，不修改既有 HTTP reference schema。

新的 `POST /v1/scopes/{scope_id}/sources/{source_type}` 不接受调用方指定 `source_id`，而由服务端生成 opaque
`source_id`，并在 `SourceRecord.source_ref` 与 `Location` 中返回。

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

Artifact lifecycle head 的联合唯一键是 `(scope_id, family, artifact_id)`；不可变 Revision 表的联合唯一键是
`(scope_id, family, artifact_id, revision)`：

```json
{
  "artifact_head_unique_key": [
    "scope_id",
    "family",
    "artifact_id"
  ],
  "artifact_revision_unique_key": [
    "scope_id",
    "family",
    "artifact_id",
    "revision"
  ]
}
```

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
    "path": "/v1/scopes/{scope_id}/sources/{source_type}"
  },
  {
    "function": "Source Get",
    "operation_id": "get_source",
    "method": "GET",
    "path": "/v1/scopes/{scope_id}/sources/{source_type}/{source_id}"
  },
  {
    "function": "Source List",
    "operation_id": "list_sources",
    "method": "GET",
    "path": "/v1/scopes/{scope_id}/sources/{source_type}"
  },
  {
    "function": "Source Search",
    "operation_id": "search_sources",
    "method": "GET",
    "path": "/v1/scopes/{scope_id}/source-search-results"
  },
  {
    "function": "Artifact Create",
    "operation_id": "create_artifact",
    "method": "POST",
    "path": "/v1/scopes/{scope_id}/artifacts/{family}"
  },
  {
    "function": "Artifact Head Get",
    "operation_id": "get_artifact",
    "method": "GET",
    "path": "/v1/scopes/{scope_id}/artifacts/{family}/{artifact_id}"
  },
  {
    "function": "Artifact Revision Get",
    "operation_id": "get_artifact_revision",
    "method": "GET",
    "path": "/v1/scopes/{scope_id}/artifacts/{family}/{artifact_id}/revisions/{revision}"
  },
  {
    "function": "Artifact List",
    "operation_id": "list_artifacts",
    "method": "GET",
    "path": "/v1/scopes/{scope_id}/artifacts/{family}"
  },
  {
    "function": "Artifact Search",
    "operation_id": "search_artifacts",
    "method": "GET",
    "path": "/v1/scopes/{scope_id}/artifact-search-results"
  },
  {
    "function": "Artifact Replace",
    "operation_id": "replace_artifact",
    "method": "PUT",
    "path": "/v1/scopes/{scope_id}/artifacts/{family}/{artifact_id}"
  },
  {
    "function": "Artifact Delete",
    "operation_id": "delete_artifact",
    "method": "DELETE",
    "path": "/v1/scopes/{scope_id}/artifacts/{family}/{artifact_id}"
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
- 新增基础 API 的 response 复用领域 `SourceRef`、`ArtifactReference`、Artifact Revision 和 Source journal
  position 的语义，但不修改既有 HTTP schema；
- Create 与 List 的 path 包含联合唯一键前缀：Source 使用 `scope_id + source_type`，Artifact 使用
  `scope_id + family`；
- 具名 Source path 包含 `scope_id + source_type + source_id`；Artifact head path 包含
  `scope_id + family + artifact_id`，精确 Revision path 再追加 `revision`；
- PUT request body 只承载完整 replacement；联合唯一键分量不在 body 或 query 中重复；
- Search 不是具名资源定位：`scope_id` 作为授权与隔离边界放在 path，`source_type` / `family`、`q`、`mode`、
  cursor 和时间范围作为 query filter；
- 字段名继续使用现有 snake_case；
- Scope identity 与可见性由 PR #1401 的 Scope API 负责；本文不从 Source/Artifact 数据反向推导或列举 Scope。

所有 path parameter 必须分别按 RFC 3986 path segment 编码并由服务端只解码一次。PR #1401 新生成的
`scp_...` Scope ID 是 path-segment-safe；实现仍必须为既有 `scope_id` 以及允许的 `source_type`、`family`、
`source_id`、`artifact_id` 覆盖保留字符和 encoded slash 的网关/路由一致性测试，不能把两个不同联合键错误映射到同一 URI。
通用 Source Create 返回的 `source_id` 是服务端生成的 opaque path identity，调用方不得解析或依赖其格式。

# Common response conventions

## Source 返回对象

```json
{
  "scope_id": "scp_01j8m4v2n7q9x3k6c5t0b1d2ef",
  "source_ref": {
    "source_type": "content",
    "source_id": "src_01J..."
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
    "source_ref": "本 RFC 新增基础 API 使用的 scope-local SourceRef；包含 source_type + source_id，不包含 Revision",
    "content": "Source type 对应的权威内容；content type 首期为 string",
    "metadata": "来源、标题、媒体类型等 Source-specific 元数据；保持可扩展对象",
    "created_at": "服务端耐久接收时间",
    "position": "Source journal position；可用于判断 Memory flush 是否已经越过该 Source",
    "content_digest": "canonical content 的摘要，用于审计与完整性比对；不作为通用 Source Create 的幂等身份"
  }
}
```

## Artifact Revision 返回对象

```json
{
  "scope_id": "scp_01j8m4v2n7q9x3k6c5t0b1d2ef",
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
      "source_type": "content",
      "source_id": "src_01J..."
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
    "source_refs": "直接 Source evidence；每项使用本 RFC 的 scope-local SourceRef shape",
    "artifact_refs": "直接 Artifact evidence，必须是精确 ArtifactReference",
    "created_at": "当前 Revision 的提交时间",
    "content_digest": "当前 Revision canonical content 的摘要"
  }
}
```

Artifact Revision 已经承担并发前置条件的用途，因此不再增加第二个通用版本字段。

请求省略可选集合或对象字段时，服务端持久化并返回稳定缺省值；List 使用摘要对象而不是伪装成完整记录：

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

- `GET /v1/scopes/{scope_id}/source-search-results` 返回
  `SourceSearchResultPage{query,mode,hits,next_cursor}`；
- `GET /v1/scopes/{scope_id}/artifact-search-results` 返回
  `ArtifactSearchResultPage{query,mode,hits,next_cursor}`。

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

List 与 Search 使用不同 path、operationId 和 response schema。`GET
/v1/scopes/{scope_id}/sources/{source_type}` 永远是 `list_sources`，不接受 `type`、`q` 或 `mode`；`GET
/v1/scopes/{scope_id}/source-search-results` 永远是 `search_sources`，不通过参数切换成 List。Search 的
`source_type` 是必填 filter，不是具名 Source 的资源身份。

## Source Create 定义与示例

```json
{
  "operation_id": "create_source",
  "request": {
    "method": "POST",
    "path": "/v1/scopes/{scope_id}/sources/{source_type}",
    "path_parameters": {
      "required": [
        "scope_id",
        "source_type"
      ],
      "example": {
        "scope_id": "scp_01j8m4v2n7q9x3k6c5t0b1d2ef",
        "source_type": "content"
      }
    },
    "headers": {
      "Content-Type": "application/json",
      "Idempotency-Key": "idem_01J..."
    },
    "body": {
      "required_fields": [
        "content"
      ],
      "optional_fields": [
        "metadata"
      ],
      "example": {
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
      "Location": "/v1/scopes/scp_01j8m4v2n7q9x3k6c5t0b1d2ef/sources/content/src_01J..."
    },
    "body": {
      "scope_id": "scp_01j8m4v2n7q9x3k6c5t0b1d2ef",
      "source_ref": {
        "source_type": "content",
        "source_id": "src_01J..."
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
      "status": 422,
      "code": "invalid_request",
      "condition": "缺少 Idempotency-Key，或请求体包含禁止由调用方指定的 source_id"
    },
    {
      "status": 409,
      "code": "idempotency_conflict",
      "condition": "相同 Idempotency-Key 对应不同 canonical request"
    }
  ]
}
```

`source_id` 由服务端生成，是调用方不可解析的 opaque identity。Source Create 的耐久幂等身份为
`(create_source, scope_id, source_type, Idempotency-Key)`：首次请求原子地保存 canonical request digest、生成的
`source_id`、journal position 与成功结果；相同 key 和相同 canonical request 重放时返回同一个 `201 SourceRecord`、
`Location` 与 `position`，不追加 journal；相同 key 对应不同 canonical request 时返回
`409 idempotency_conflict`。该绑定与 Source 一样耐久，不允许在同一 Scope 和 Source type 下复用 key 创建另一条 Source。

`Idempotency-Key` 只控制 Create 重试，不写入 `source_ref`，也不参与后续 Get/List/Search。服务端不得按
`content_digest` 自动合并 Source，因为内容相同的两次写入可能代表两条不同证据。

## Source Get 定义与示例

```json
{
  "operation_id": "get_source",
  "request": {
    "method": "GET",
    "path": "/v1/scopes/{scope_id}/sources/{source_type}/{source_id}",
    "path_parameters": {
      "required": [
        "scope_id",
        "source_type",
        "source_id"
      ],
      "example": {
        "scope_id": "scp_01j8m4v2n7q9x3k6c5t0b1d2ef",
        "source_type": "content",
        "source_id": "src_01J..."
      }
    }
  },
  "success": {
    "status": 200,
    "schema": "SourceRecord",
    "body": {
      "scope_id": "scp_01j8m4v2n7q9x3k6c5t0b1d2ef",
      "source_ref": {
        "source_type": "content",
        "source_id": "src_01J..."
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
    "path": "/v1/scopes/{scope_id}/sources/{source_type}",
    "path_parameters": {
      "required": [
        "scope_id",
        "source_type"
      ],
      "example": {
        "scope_id": "scp_01j8m4v2n7q9x3k6c5t0b1d2ef",
        "source_type": "content"
      }
    },
    "query_parameters": {
      "optional": [
        "limit",
        "cursor",
        "created_after",
        "created_before"
      ],
      "example": {
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
          "scope_id": "scp_01j8m4v2n7q9x3k6c5t0b1d2ef",
          "source_ref": {
            "source_type": "content",
            "source_id": "src_01J..."
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
    "path": "/v1/scopes/{scope_id}/source-search-results",
    "path_parameters": {
      "required": [
        "scope_id"
      ],
      "example": {
        "scope_id": "scp_01j8m4v2n7q9x3k6c5t0b1d2ef"
      }
    },
    "query_parameters": {
      "required": [
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
          "source_type": "content",
          "q": "refund manual review",
          "mode": "auto",
          "limit": 20
        },
        "without_query": {
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
              "source_type": "content",
              "source_id": "src_01J..."
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
              "source_type": "content",
              "source_id": "src_01J..."
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
    "path": "/v1/scopes/{scope_id}/artifacts/{family}",
    "path_parameters": {
      "required": [
        "scope_id",
        "family"
      ],
      "example": {
        "scope_id": "scp_01j8m4v2n7q9x3k6c5t0b1d2ef",
        "family": "company.example.decision"
      }
    },
    "headers": {
      "Content-Type": "application/json"
    },
    "body": {
      "required_fields": [
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
      "Location": "/v1/scopes/scp_01j8m4v2n7q9x3k6c5t0b1d2ef/artifacts/company.example.decision/dec_01J...",
      "ETag": "revision:1"
    },
    "body": {
      "scope_id": "scp_01j8m4v2n7q9x3k6c5t0b1d2ef",
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

`artifact_id` 可选；省略时由服务端生成，并通过 `artifact_ref.artifact_id` 和 `Location` 返回。希望安全重试
“服务端生成 ID”的 Create 时，调用方应提供 `idempotency_key`：相同 key 与相同 canonical request 返回同一
Revision 1，不再创建另一个 Artifact；相同 key 对应不同 canonical request 返回 `409 idempotency_conflict`。
未提供 `idempotency_key` 的每次 Create 都是独立创建尝试，网络超时后的盲重试可能创建另一条 Artifact。

## Artifact Get current 定义与示例

```json
{
  "operation_id": "get_artifact",
  "request": {
    "method": "GET",
    "path": "/v1/scopes/{scope_id}/artifacts/{family}/{artifact_id}",
    "path_parameters": {
      "required": [
        "scope_id",
        "family",
        "artifact_id"
      ],
      "example": {
        "scope_id": "scp_01j8m4v2n7q9x3k6c5t0b1d2ef",
        "family": "company.example.decision",
        "artifact_id": "dec_01J..."
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
      "scope_id": "scp_01j8m4v2n7q9x3k6c5t0b1d2ef",
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

## Artifact Get exact Revision 定义与示例

```json
{
  "operation_id": "get_artifact_revision",
  "request": {
    "method": "GET",
    "path": "/v1/scopes/{scope_id}/artifacts/{family}/{artifact_id}/revisions/{revision}",
    "path_parameters": {
      "required": [
        "scope_id",
        "family",
        "artifact_id",
        "revision"
      ],
      "example": {
        "scope_id": "scp_01j8m4v2n7q9x3k6c5t0b1d2ef",
        "family": "company.example.decision",
        "artifact_id": "dec_01J...",
        "revision": 1
      }
    }
  },
  "success": {
    "status": 200,
    "schema": "ArtifactRevision",
    "headers": {},
    "body": {
      "scope_id": "scp_01j8m4v2n7q9x3k6c5t0b1d2ef",
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

精确 Revision response 不携带 head ETag；即使该 Artifact 后续被替换或删除，已提交 Revision 的内容仍不可变。

## Artifact List 定义与示例

```json
{
  "operation_id": "list_artifacts",
  "request": {
    "method": "GET",
    "path": "/v1/scopes/{scope_id}/artifacts/{family}",
    "path_parameters": {
      "required": [
        "scope_id",
        "family"
      ],
      "example": {
        "scope_id": "scp_01j8m4v2n7q9x3k6c5t0b1d2ef",
        "family": "company.example.decision"
      }
    },
    "query_parameters": {
      "optional": [
        "limit",
        "cursor",
        "created_after",
        "created_before"
      ],
      "example": {
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
    "path": "/v1/scopes/{scope_id}/artifact-search-results",
    "path_parameters": {
      "required": [
        "scope_id"
      ],
      "example": {
        "scope_id": "scp_01j8m4v2n7q9x3k6c5t0b1d2ef"
      }
    },
    "query_parameters": {
      "required": [
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
    "path": "/v1/scopes/{scope_id}/artifacts/{family}/{artifact_id}",
    "path_parameters": {
      "required": [
        "scope_id",
        "family",
        "artifact_id"
      ],
      "example": {
        "scope_id": "scp_01j8m4v2n7q9x3k6c5t0b1d2ef",
        "family": "company.example.decision",
        "artifact_id": "dec_01J..."
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
      "scope_id": "scp_01j8m4v2n7q9x3k6c5t0b1d2ef",
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

## Artifact Delete 定义与示例

```json
{
  "operation_id": "delete_artifact",
  "request": {
    "method": "DELETE",
    "path": "/v1/scopes/{scope_id}/artifacts/{family}/{artifact_id}",
    "path_parameters": {
      "required": [
        "scope_id",
        "family",
        "artifact_id"
      ],
      "example": {
        "scope_id": "scp_01j8m4v2n7q9x3k6c5t0b1d2ef",
        "family": "company.example.decision",
        "artifact_id": "dec_01J..."
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
    "same_if_match_replay": "命中该 lifecycle 的 deletion receipt 时返回首次删除的同一 200 结果，不再写 tombstone",
    "different_if_match_after_delete": "412 revision_conflict",
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
        "path": "/v1/scopes/{scope_id}/sources/{source_type}",
        "path_parameters": {
          "scope_id": "scp_01j8m4v2n7q9x3k6c5t0b1d2ef",
          "source_type": "content"
        },
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
          "scope_id": "scp_01j8m4v2n7q9x3k6c5t0b1d2ef"
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

支持的基础动作由 assembled Runtime 中的 Source type / Artifact Family 注册信息决定；不支持的基础动作返回
`405 operation_not_supported`。本 RFC 不新增或扩展能力发现接口。

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
    "meaning": "缺少 scope_id 或必需的 Idempotency-Key、字段非法、Create body 包含 source_id、Search mode 与请求不兼容，或 cursor 与查询条件不匹配"
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
    "meaning": "支持幂等键的操作将相同 key 绑定到了不同 canonical request；包括新 Source Create"
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

本 RFC 不修改既有 API contract。新增基础入口必须直接读取同一权威 Source/Artifact Revision、content digest、
lineage 和授权结果，不能建立第二份业务数据或独立身份空间。

# OpenAPI contract

`openapi/powercontext.yaml` 仍是唯一 HTTP 契约真相。实现时新增或复用以下 schema：

```json
{
  "contract_source": "openapi/powercontext.yaml",
  "schemas": [
    "SourceRef",
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
  }
}
```

OpenAPI 还必须声明 `Idempotency-Key` 和 `If-Match` request header 以及 `ETag` response header。不得增加统一
Source/Artifact union schema、统一 selector 或统一引用 envelope。Family-specific `content` 通过 assembled
Runtime 中已注册的 schema 校验；generated Client 将其暴露为 JSON object，强类型体验继续由现有 Family API 提供。

# Implementation plan

1. 在 OpenAPI 中为新增基础 API 增加 `{source_type, source_id}` 结构的 `SourceRef`，不修改既有 HTTP schema。
2. 增加要求 `Idempotency-Key` 且由服务端生成 `source_id` 的
   `POST /v1/scopes/{scope_id}/sources/{source_type}`，以及使用同一联合键前缀的 Source Get/List 和 Scope-bound Search。
3. 增加按 `(scope_id, family, artifact_id[, revision])` 定位的 Artifact create、head get、exact revision get、list、
   search-result、replace 和 delete paths。
4. 建立 Source/Artifact 公共 application services，让新增入口读写现有权威 repository。
5. 运行 `make api-generate` 与 `make contract-test`，更新 checked-in generated Client。
6. 为 SQLite 与 OceanBase 增加相同的 API behavior、cursor、CAS、授权和幂等测试。
7. 增加 Source Create 后循环 Memory Flush 至 cursor 越过 position 的 SDK convenience example；不改变服务端契约。

# Acceptance criteria

| 场景 | 通过条件 |
| --- | --- |
| No umbrella concept | OpenAPI 中没有跨 Source/Artifact 的统一 selector、联合 request/response 或统一资源类型字段 |
| No write-time generation | Source Create request/response 只表达 Source 耐久写入，不包含任何生成参数或生成结果 |
| Source operations | Source 只公开 Create/Get/List/Search，不公开 Replace/Delete |
| Source list/search | `GET /v1/scopes/{scope_id}/sources/{source_type}` 使用 `list_sources`；`GET /v1/scopes/{scope_id}/source-search-results` 使用 `search_sources`；Search 的 `source_type` 是 query filter，`q` 可选 |
| Artifact operations | 固定 path 提供 Create/Get/List/Search/Replace/Delete；Replace 创建下一不可变 Revision |
| REST paths | URL 使用名词；Create 使用 POST，Get/List/Search 使用 GET，完整 Replace 使用 PUT，Delete 使用 DELETE |
| Exact identity | Source 表联合唯一键为 `(scope_id, source_type, source_id)`；Artifact head 与 Revision 分别按 `(scope_id, family, artifact_id)` 和追加 `revision` 的键定位 |
| Canonical URI | Source/Artifact Create、Get、List、Replace、Delete 的 identity 或 identity prefix 位于 path；Search 仅把 `scope_id` 放 path，其余检索条件放 query |
| Source-generated identity | `POST /v1/scopes/{scope_id}/sources/{source_type}` 不接受 `source_id`，服务端生成 opaque `source_id` 并通过 body 与 `Location` 返回 |
| Source create idempotency | `Idempotency-Key` 必填；相同 key/request 返回同一个 Source 与 position，不同 request 返回 `409 idempotency_conflict` |
| Scope required | 所有 Source/Artifact Get/List/Search/Mutation 都显式携带 `scope_id` |
| Scope dependency | 本 RFC 不定义 Scope API；所有 Source/Artifact 操作使用由 PR #1401 Scope API 提供的 `scope_id` |
| Pagination | Source 与 Artifact 的 List/Search 使用稳定 cursor，cursor 绑定 endpoint、完整查询和授权上下文 |
| Concurrency | Artifact Replace/Delete 必须携带 current head ETag；缺失返回 `428`，冲突返回 `412 revision_conflict` |
| Review gate | Experience/Skill 等 Review Family 不能通过基础 Create/Replace 绕过 Candidate approval |
| Memory boundary | Source Create + Memory Flush 是两个调用；flush 是 bounded pending window，不宣称 exact single-Source 或 full refresh |
| Compatibility | 本 RFC 不修改任何既有 path、operation、request/response schema 或领域行为 |
| Extensibility | 新增 Direct Artifact Family 不增加基础 HTTP path 或 generated Client method |
| Conformance | SQLite 与 OceanBase 通过相同 contract 与行为测试 |

# Drawbacks

- Family-specific Artifact `content` 在基础 generated Client 中只能是 JSON object，静态类型弱于强类型 Family API。
- 新旧读取入口会并存一段时间，需要共享 application service 与 parity tests 防止行为漂移。
- Direct Family 与 Review Family 的 mutation capability 不完全一致，调用方必须处理 `405 operation_not_supported`。
- Artifact logical delete、历史 lineage 可验证与 retention 之间仍需 Family 实现正确衔接。
- Source Create + Memory Flush 不是一个事务；客户端必须处理“Source 成功、flush 失败”的可重试状态。
- 把联合键分量放入 path 后，Server 与网关必须对保留字符执行一致的 path-segment 编解码，否则旧格式 ID 可能无法寻址。
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
