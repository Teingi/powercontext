- Proposal Name: `source_artifact_rest_api`
- Start Date: 2026-09-01
- RFC PR: [oceanbase/powercontext#0000](https://github.com/oceanbase/powercontext/pull/0000)

# Summary

本 RFC 为 PowerContext 增加两组彼此独立的基础 HTTP API：

- Source：`create`、`get`、`list`、`search`；
- Artifact：`create`、`get`、`list`、`search`、`replace`、`delete`；
- Scope：列举当前调用方可见的全部 `scope_id`。

API 直接复用 PowerContext 已有的 Source、Artifact、Artifact Revision 和 Scope 语义，不增加二者之上的统一对象概念，不增加统一 selector、联合引用、统一 envelope、类型注册接口或跨类型 List/Search。

写入和生成仍是两个独立提交边界。Source Create 只返回 Source 的耐久写入结果，不携带生成参数或联合生成结果。需要“写入 Source 后立即生成 Memory 并等待结果”的调用方，顺序调用 `POST /v1/sources` 与现有 `POST /v1/memory/flush` 即可。

接口遵守以下约定：

- URL 使用复数名词，不使用 `/add`、`/get`、`/list`、`/update`、`/delete` 动词路径；
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
- 先发现当前可见的 `scope_id`，再在选定 Scope 中查询 Source 或 Artifact；
- 需要写入后立即生成时，由客户端编排 Source Create 与 Family command，而不是让基础写接口隐式调用模型。

# Goals

- 直接以 Source 与 Artifact 建模，不增加统一上层概念。
- 保持 `SourceReference` 无 Revision、`ArtifactReference` 必须包含 Revision。
- 为未来 Artifact Family 提供固定的基础 API surface。
- 使用 REST 风格的名词路径和 HTTP 方法。
- 保留现有领域命令及 Candidate Review 边界。
- 为 Source、Artifact 和 Scope 定义清晰的请求元数据、返回格式、分页、并发与错误语义。
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

## Scope

`scope_id` 是 Source 与 Artifact 的隔离和查询边界，不是 Source，也不是 Artifact。

Scope 是显式持久化的归属边界。新 `scope_id` 由 Scope application layer 生成，不能根据 Source、Artifact、repo、目录或 Agent identity 临时推导。`GET /v1/scopes` 列举调用方有权观察的持久 Scope；一个尚无 Source 或 Artifact 的新建 Scope 也可以被列出。

Scope 的创建、metadata、Organization Parent、Context References 与 binding 由 Scope organization 设计负责。本 RFC 只定义基础 Source/Artifact API 所需的 Scope 列表读取，不重复定义 Scope mutation。

# REST API conventions

## `create/get/list/search/replace/delete` 的 HTTP 映射

这些词适合作为用户能力名称，但不应全部写入 URL 并统一使用 POST。`POST /v1/artifacts/get`、`POST /v1/artifacts/list`、`POST /v1/artifacts/update` 属于 RPC command 风格，不是推荐的 REST 表达。

本 RFC 采用下表映射：

| 用户能力 | REST 表达 | HTTP 方法 | 推荐 operationId | 结论 |
| --- | --- | --- | --- | --- |
| Create | 向集合创建对象 | `POST` | `create_source` / `create_artifact` | URL 不使用 `/add` |
| Get | 读取一个具名对象或精确 Revision | `GET` | `get_source` / `get_artifact` / `get_artifact_revision` | URL 不使用 `/get` |
| List | 读取集合 | `GET` | `search_sources`（`type` 缺省或为 `list`）/ `list_artifacts` | URL 不使用 `/list` |
| Search | 读取带检索条件的结果集合 | `GET` | `search_sources` / `search_artifacts` | Source Search 与 List 共用 `/v1/sources`；Artifact Search 使用结果集合 |
| Replace | 完整替换 Artifact head | `PUT` | `replace_artifact` | 必须携带 `If-Match`；内部创建下一 Revision |
| Delete | 删除一个具名 Artifact 的当前可见状态 | `DELETE` | `delete_artifact` | URL 不使用 `/delete` |

OpenAPI `operationId` 使用动词是正常的；REST 约束的是 wire-level URL 与 HTTP method，不是要求所有 SDK 方法都只能使用名词。

## PowerContext HTTP 接口约束

- 集合路径与具名对象路径分离；
- `GET` collection 表示 List/Search，`POST` collection 表示 Create；
- `GET` named object 表示 Read，`DELETE` named object 表示 Delete；
- 子对象使用子集合表达；
- List 返回 typed items 和分页元数据；
- `PUT` 只接受完整 replacement；Artifact Replace/Delete 必须通过 `If-Match` 携带当前 head 的 ETag，不能静默覆盖并发写入；
- 不增加额外的类型 envelope 或通用版本字段，直接复用 `SourceReference`、`ArtifactReference`、Artifact Revision 和 Source journal position；
- 不把 `scope_id` 放进 URL path。PowerContext 的 `scope_id` 可能是 `git:github.com/acme/payments`，包含 `:` 与 `/`；因此 GET/DELETE 使用 query parameter，POST 使用 request body；
- 不为每个 Source type 或 Artifact Family 增加一条 OpenAPI path。基础集合固定为 `/v1/sources` 与 `/v1/artifacts`，`source_type` / `family` 放在 body 或 query 中；这保证新增 Family 不增加 generated Client method；
- 字段名继续使用现有 snake_case；
- Scope identity 与可见性来自 Scope organization 设计中的权威 Scope application layer；不能通过扫描 Source/Artifact 反向创造 Scope。

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

| 字段 | 语义 |
| --- | --- |
| `scope_id` | Source 所属 Scope；所有 Get/List/Search 必须显式关联 |
| `source_ref` | 现有精确 SourceReference；不包含 Revision |
| `content` | Source type 对应的权威内容；`content` type 首期为 string |
| `metadata` | 来源、标题、媒体类型等 Source-specific 元数据；保持可扩展对象 |
| `created_at` | 服务端耐久接收时间 |
| `position` | Source journal position；可用于判断 Memory flush 是否已经越过该 Source |
| `content_digest` | canonical content 的摘要，用于审计与幂等校验 |

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

| 字段 | 语义 |
| --- | --- |
| `scope_id` | Artifact 所属 Scope |
| `artifact_ref` | 现有精确 ArtifactReference，必须包含 Revision |
| `schema_version` | Family content schema 版本 |
| `metadata` | 标题、标签等非内容字段；具体约束由 Family 定义 |
| `content` | Family-specific JSON content |
| `source_refs` | 直接 Source evidence，必须是精确 SourceReference |
| `artifact_refs` | 直接 Artifact evidence，必须是精确 ArtifactReference |
| `created_at` | 当前 Revision 的提交时间 |
| `content_digest` | 当前 Revision canonical content 的摘要 |

Artifact Revision 已经承担并发前置条件的用途，因此不再增加第二个通用版本字段。

Artifact head response 使用标准 `ETag` header 暴露当前 Revision，例如：

```http
ETag: "revision:2"
```

`PUT` 与 `DELETE` 必须回传该值：

```http
If-Match: "revision:2"
```

缺少 `If-Match` 返回 `428 Precondition Required`；ETag 已过期返回 `412 Precondition Failed`。成功创建或替换 head 后，response 返回新 ETag。

## 分页与搜索返回

Source List/Search 共用一个 `SourcePage`。`type` 缺省或为 `list` 时，`query`、`mode`、`score` 和 `snippets` 为空；`type=search` 时使用 `q` 检索并填充搜索元数据：

```json
{
  "query": null,
  "mode": null,
  "items": [],
  "next_cursor": null
}
```

Artifact Search 使用独立结果页：

```json
{
  "query": "退款 人工复核",
  "mode": "keyword",
  "hits": [],
  "next_cursor": null
}
```

Cursor 必须绑定调用方身份、`scope_id`、`source_type/family`、Source 查询 `type`、`q`、过滤器、排序和实际搜索模式。任一条件变化后不能复用旧 cursor。

# Source API

Source 首期公开 Create、Get、List、Search。每次查询只处理一个 `scope_id` 与一个 `source_type`。

| 接口功能 | HTTP API | 接口名（operationId） | 请求及元数据定义 | 返回格式 | 调用示例 |
| --- | --- | --- | --- | --- | --- |
| Create Source | `POST /v1/sources` | `create_source` | Body 必填 `scope_id`、`source_type`、`source_id`、`content`；可选 `metadata`。`source_id` 是调用方幂等身份 | `201 Created`；返回完整 `Source`，并通过 `Location` 返回其 URI | `POST /v1/sources`<br>`{"scope_id":"git:github.com/acme/payments","source_type":"content","source_id":"refund-rule-001","content":"退款必须人工复核","metadata":{"media_type":"text/plain"}}` |
| Get Source | `GET /v1/sources/{source_id}` | `get_source` | Query 必填 `scope_id`、`source_type`；二者与 path 中 `source_id` 共同确定 Source | `200 Source`；不存在或不可见返回 `404` | `GET /v1/sources/refund-rule-001?scope_id=git%3Agithub.com%2Facme%2Fpayments&source_type=content` |
| List Sources | `GET /v1/sources` | `search_sources`（`type` 缺省或为 `list`） | Query 必填 `scope_id`、`source_type`；可选 `type=list`、`limit`、`cursor`、`created_after`、`created_before`。每次仅查询一个 `source_type`，不得传 `q` 或 `mode` | `200 SourcePage{query,mode,items,next_cursor}`；按稳定顺序列举，搜索字段为空 | `GET /v1/sources?scope_id=git%3Agithub.com%2Facme%2Fpayments&source_type=content&limit=50` |
| Search Sources | `GET /v1/sources` | `search_sources`（`type=search`） | Query 必填 `scope_id`、`source_type`、`type=search` 和非空 `q`；可选 `mode` 及可重复结构化过滤参数 | `200 SourcePage{query,mode,items,next_cursor}`；item 可包含 `score` 与 `snippets` | `GET /v1/sources?scope_id=git%3Agithub.com%2Facme%2Fpayments&source_type=content&type=search&q=refund%20manual%20review&mode=auto&limit=20` |

OpenAPI 对同一个 method + path 只能声明一个 operation。因此 `GET /v1/sources` 只声明 `operationId: search_sources`：

- 不传 `type` 或传入 `type=list`：执行确定性 List，`query=null`、`mode=null`，item 不返回 `score/snippets`；
- 传入 `type=search`：执行 Search；必须同时传入非空 `q`，response 报告实际 `mode`，item 可以返回 `score/snippets`；
- `type` 只用于选择 List/Search 行为；`source_type` 才表示 Source 类型，两者不是同一概念；
- 未知 `type`、List 请求携带 `q`/`mode`，或 Search 请求缺少非空 `q`，均返回 `422 invalid_request`，服务端不得静默忽略参数；
- cursor 必须绑定 `type`、`q`、mode、filters、排序和授权上下文。

## Source Create 兼容语义

推荐的 REST Create 入口是：

```http
POST /v1/sources
Content-Type: application/json
```

```json
{
  "scope_id": "git:github.com/acme/payments",
  "source_type": "content",
  "source_id": "refund-rule-001",
  "content": "退款流程必须保留人工复核。",
  "metadata": {
    "title": "退款流程约束",
    "media_type": "text/plain"
  }
}
```

```http
HTTP/1.1 201 Created
Location: /v1/sources/refund-rule-001?scope_id=git%3Agithub.com%2Facme%2Fpayments&source_type=content
```

Response body 使用“Common response conventions”中唯一的 `Source` 定义，不在本节重复一份平行结构。

现有 `POST /v1/sources/content` 原样保留为 `content` 的强类型兼容 facade：

```http
POST /v1/sources/content
Content-Type: application/json
```

```json
{
  "scope_id": "git:github.com/acme/payments",
  "source_id": "refund-rule-001",
  "content": "退款流程必须保留人工复核。",
  "metadata": {
    "title": "退款流程约束",
    "media_type": "text/plain"
  }
}
```

```http
HTTP/1.1 202 Accepted
```

```json
{
  "status": "accepted",
  "source": {
    "name": "content",
    "source_id": "refund-rule-001"
  },
  "position": 42
}
```

新旧入口委托同一个持久化 handler，但保留各自 HTTP response：新入口返回 `201 Source`，兼容入口返回现有 `202 CaptureContentSourceResponse`。相同 `scope_id + source_type + source_id` 与相同 canonical payload 重放时返回原幂等结果；相同身份但 payload 不同返回 `409 idempotency_conflict`。

## Source Search 示例

```http
GET /v1/sources?scope_id=git%3Agithub.com%2Facme%2Fpayments&source_type=content&type=search&q=refund%20manual%20review&mode=auto&limit=20
```

```json
{
  "query": "refund manual review",
  "mode": "keyword",
  "items": [
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
}
```

# Artifact API

Artifact 基础接口对未来 Family 使用固定 path。新增 Family 只需在 assembled Runtime 注册 Family implementation、content schema 与能力，不增加新的基础 HTTP path 或 generated Client method。

| 接口功能 | HTTP API | 接口名（operationId） | 请求及元数据定义 | 返回格式 | 调用示例 |
| --- | --- | --- | --- | --- | --- |
| Create Artifact | `POST /v1/artifacts` | `create_artifact` | Body 必填 `scope_id`、`family`、`content`、`schema_version`；可选 `artifact_id`、`metadata`、`source_refs`、`artifact_refs`、`idempotency_key`。创建 Revision 1 | `201 Created`；返回 `ArtifactRevision`，并通过 `Location` 与 `ETag` 返回 head URI 和当前 Revision | `POST /v1/artifacts`<br>`{"scope_id":"git:github.com/acme/payments","family":"company.example.decision","artifact_id":"dec_01J...","schema_version":1,"content":{"decision":"退款必须人工复核"},"source_refs":[{"name":"content","source_id":"refund-rule-001"}]}` |
| Get current Artifact | `GET /v1/artifacts/{artifact_id}` | `get_artifact` | Query 必填 `scope_id`、`family` | `200 ArtifactRevision` + `ETag`；返回当前可见 head | `GET /v1/artifacts/dec_01J...?scope_id=git%3Agithub.com%2Facme%2Fpayments&family=company.example.decision` |
| Get Artifact Revision | `GET /v1/artifacts/{artifact_id}/revisions/{revision}` | `get_artifact_revision` | Query 必填 `scope_id`、`family`；path 包含精确 `artifact_id + revision` | `200 ArtifactRevision`；不存在或不可见返回 `404` | `GET /v1/artifacts/dec_01J.../revisions/2?scope_id=git%3Agithub.com%2Facme%2Fpayments&family=company.example.decision` |
| List Artifacts | `GET /v1/artifacts` | `list_artifacts` | Query 必填 `scope_id`、`family`；可选 `limit`、`cursor`、`created_after`、`created_before`。每个 `artifact_id` 只列当前可见 head | `200 ArtifactPage{items,next_cursor}`；item 至少含精确 `artifact_ref`、摘要元数据与更新时间 | `GET /v1/artifacts?scope_id=git%3Agithub.com%2Facme%2Fpayments&family=experience&limit=50` |
| Search Artifacts | `GET /v1/artifact-search-results` | `search_artifacts` | Query 必填 `scope_id`、`family`、非空 `q`；可选 `mode`、结构化过滤参数、`limit`、`cursor`。首期只搜索当前可见 head | `200 ArtifactSearchResultPage{query,mode,hits,next_cursor}`；hit 含精确 `artifact_ref`、`score`、`snippets` | `GET /v1/artifact-search-results?scope_id=git%3Agithub.com%2Facme%2Fpayments&family=experience&q=refund%20manual%20review&mode=auto&limit=20` |
| Replace Artifact | `PUT /v1/artifacts/{artifact_id}` | `replace_artifact` | Query 必填 `scope_id`、`family`；Header 必填 `If-Match`；Body 是完整 replacement。首期不接受 Merge Patch | `200 ArtifactRevision` + 新 `ETag`；内部创建下一 Revision。ETag 过期返回 `412` | `PUT /v1/artifacts/dec_01J...?scope_id=git%3Agithub.com%2Facme%2Fpayments&family=company.example.decision`<br>`If-Match: "revision:1"` |
| Delete Artifact | `DELETE /v1/artifacts/{artifact_id}` | `delete_artifact` | Query 必填 `scope_id`、`family`；Header 必填 `If-Match`。只删除当前可见 head，不能删除历史 Revision | `200 ArtifactDeletionStatus{artifact_ref,status,deleted_at}`；ETag 过期返回 `412`；Family 不支持时返回 `405` | `DELETE /v1/artifacts/dec_01J...?scope_id=git%3Agithub.com%2Facme%2Fpayments&family=company.example.decision`<br>`If-Match: "revision:2"` |

## Artifact Create 示例

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
```

```http
HTTP/1.1 201 Created
Location: /v1/artifacts/dec_01J...?scope_id=git%3Agithub.com%2Facme%2Fpayments&family=company.example.decision
ETag: "revision:1"
```

```json
{
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
```

## Artifact Replace 示例

Artifact 的具名 URI 表示当前 head；历史 Revision URI 保持不可变。Replace 使用 `PUT` 完整替换 head，Runtime 在内部创建下一 Revision：

```http
PUT /v1/artifacts/dec_01J...?scope_id=git%3Agithub.com%2Facme%2Fpayments&family=company.example.decision
Content-Type: application/json
If-Match: "revision:1"
```

```json
{
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
```

成功时返回 Revision 2、`200 OK` 和新 ETag：

```http
HTTP/1.1 200 OK
ETag: "revision:2"
```

如果当前 head 已不是 Revision 1，则返回：

```json
{
  "code": "revision_conflict",
  "message": "Artifact ETag does not match the current head",
  "details": {
    "provided_etag": "revision:1",
    "current_etag": "revision:2"
  }
}
```

该错误的 HTTP status 为 `412 Precondition Failed`。Runtime 不自动合并，不把缺失字段解释为沿用旧值，也不原地覆盖 Revision 1。未来如果增加部分更新，再单独定义 `PATCH` 与 patch media type。

## Artifact Delete 语义

Delete 创建 lifecycle tombstone，不物理擦除历史 Revision：

- 普通 Get/List/Search/Context 不再返回已删除 head；
- 已经存在的精确 lineage 仍可验证；
- 重复 Delete 幂等返回同一删除状态；
- 首期不提供 Restore 或 Purge；
- `If-Match` 必须等于当前 head 的 ETag，避免删除并发产生的新 Revision；
- Family 必须显式声明支持 Delete，否则返回 `405 operation_not_supported`。

示例：

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

# Scope API

本 RFC 只增加通用 Scope 列表。Scope Create、metadata update、Parent、Context References 和 binding 继续遵守 Scope organization 设计，不在此重复定义；与现有专用接口的关系统一在“Existing API overlap and compatibility”章节说明。

| 接口功能 | HTTP API | 接口名（operationId） | 请求及元数据定义 | 返回格式 | 调用示例 |
| --- | --- | --- | --- | --- | --- |
| List visible Scopes | `GET /v1/scopes` | `list_scopes` | Query 可选 `limit`、`cursor`；不传 `scope_id`。身份与授权来自现有认证上下文 | `200 ScopePage{items,next_cursor}`；只返回调用方有权读取的 Scope | `GET /v1/scopes?limit=50` |

`ScopePage` 完整 response：

```json
{
  "items": [
    {
      "scope_id": "scp_01k...",
      "title": "Payments",
      "summary": "支付与退款规则",
      "parent_scope_id": null,
      "version": 3,
      "source_types": [
        "content"
      ],
      "artifact_families": [
        "memory",
        "experience",
        "company.example.decision"
      ],
      "source_count": 120,
      "artifact_count": 8
    }
  ],
  "next_cursor": "cur_01J..."
}
```

Scope 列表遵守以下规则：

- “全部”指调用方授权范围内的全部持久 Scope，不是绕过权限的全租户扫描；新建但尚无 Source/Artifact 的 Scope 也可以返回；
- 授权过滤必须发生在分页与计数之前，避免通过 item 数量或 cursor 泄露不可见 Scope；
- 对无权访问的具体 Scope，Source/Artifact Get 推荐返回 `404`，避免 Scope 枚举；
- `source_count` 统计耐久 Source；`artifact_count` 统计 Artifact identity 的当前 head 数，不统计历史 Revision 数；
- `source_types`、`artifact_families` 和 count 是活动摘要，不决定 Scope identity 或是否存在；
- 本 RFC 不定义 Scope Create/Update/Delete；这些动作不能由 Source/Artifact CRUD 隐式代替。

## Scope 查询实现

`GET /v1/scopes` 必须读取 Scope application layer 的权威 Scope 目录，不能对 Source journal 与 Artifact catalog 做 `UNION DISTINCT` 来推导 Scope identity。Source/Artifact 活动摘要可以使用按 `scope_id` 维护的读取投影，并在耐久 Source 写入或 Artifact Revision 提交后通过同一提交或可靠 outbox 更新。

SQLite 与 OceanBase 实现必须通过同一套行为测试。若活动摘要采用异步投影，API 必须把 count 定义为 eventually consistent；Scope 是否存在、identity、metadata 与授权可见性仍以权威 Scope 目录为准，不能因摘要延迟而错误或消失。

# Source Create + Memory Flush

本 RFC 不在 Source Create 中增加任何生成参数。需要“写入后立即触发 Memory 生成并返回结果”的客户端按以下顺序编排：

```text
1. POST /v1/sources
2. 记录 response.position
3. POST /v1/memory/flush
4. 如果 current_cursor < position，则继续 flush
5. 当 current_cursor >= position 时，返回最后一次 flush 的 Memory Revision/Changes
```

第一步的请求与 response 直接复用“Source Create 兼容语义”中的唯一示例。假设其 `response.position=42`，随后调用：

```http
POST /v1/memory/flush
```

```json
{
  "scope_id": "git:github.com/acme/payments"
}
```

示例 response：

```json
{
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
```

必须明确：

- `memory/flush` 每次处理一个 bounded pending Source window，不是“只针对刚写入的一个 Source”，也不是“全量刷新所有历史 Source”；
- `current_cursor >= create response.position` 才能证明本次 flush 已经越过刚写入的 Source；
- 一个窗口可能同时包含更早的 pending Sources，返回的 Memory Revision/Changes 可能是它们的合并结果；
- Source 已经耐久提交后，flush 失败不会回滚 Source；客户端可以安全重试 flush；
- 组合结果由调用方或 SDK convenience method 返回，不改变服务端 Source Create response；
- Experience、Skill、Handoff 等生成继续调用既有领域接口，不纳入本 RFC。

# Family capability and lifecycle boundaries

固定 Artifact path 不意味着每个 Family 都允许直接写入：

| Family 类型 | Create | Get/List/Search | Replace | Delete |
| --- | --- | --- | --- | --- |
| Direct Family | 允许创建 Revision 1 | 允许读取已提交 Revision/head | 允许创建下一 Revision | Family 显式声明后允许 |
| Review Family（如 Experience、managed Skill） | 不绕过 propose/review；直接 Create 返回 `405 operation_not_supported` | 只返回 approved/committed Artifact | 不绕过 Candidate；返回 `405 operation_not_supported` | 默认关闭 |
| Memory | 继续使用 Memory command 创建和修改 | Artifact-level 读取不能替代 Memory Entry API | 默认关闭；Entry revise 保留双层 Revision/CAS | 默认关闭 |
| Handoff | 继续 prepare/finalize/commit | 只读取 committed Handoff | 默认关闭 | 默认关闭 |

当前 `/v1/capabilities` 应扩展为按 `source_type` 和 `artifact family` 声明实际支持的基础动作。调用方不能假设所有部署和所有 Family 都支持全部 mutation。

Candidate 不是 Artifact。pending/rejected Candidate 不进入 Artifact List/Search；只有审批并成功提交后产生的 `result_artifact` 才能通过 Artifact API 读取。

# Error model

基础 API 复用现有统一错误 envelope，并至少稳定以下 code：

| HTTP status | code | 语义 |
| --- | --- | --- |
| `400/422` | `invalid_request` | 缺少 Scope、字段非法、Source 查询 `type`/`q` 组合非法、Schema 不匹配或 cursor 与查询条件不匹配 |
| `401` | `unauthorized` | 未认证 |
| `403` | `forbidden` | 已认证但无权执行 mutation；具体对象读取优先用 404 防枚举 |
| `404` | `source_not_found` / `artifact_not_found` | 对象不存在或对调用方不可见 |
| `405` | `operation_not_supported` | Source/Family 不支持该基础动作，或动作会绕过 Review |
| `409` | `idempotency_conflict` | 相同幂等身份对应不同 payload |
| `412` | `revision_conflict` | `If-Match` 与当前 Artifact head 的 ETag 不一致 |
| `428` | `precondition_required` | Artifact Replace/Delete 缺少 `If-Match` |
| `422` | `schema_validation_failed` | Source/Family content 不符合已注册 schema |
| `503` | `capability_unavailable` | 部署声明了能力，但当前 backend 暂不可用 |

# Existing API overlap and compatibility

| 新设计 | 现有接口 | 重叠程度 | 处理方式 |
| --- | --- | --- | --- |
| `POST /v1/sources` | `POST /v1/sources/content`、`capture_content_source` | 持久化语义重叠，HTTP response 不同 | 新入口与兼容 facade 委托同一个 handler；新入口返回 `201 Source`，旧接口保留 `202 CaptureContentSourceResponse` |
| Source Get/List/Search | 当前没有通用 HTTP 接口 | 新增 | 读取同一 Source journal/projection |
| Artifact head/exact Get | `/v1/experience/get`、`/v1/skill/get` 等强类型接口 | 语义重叠 | 新旧入口委托同一 application service；新 head Get 返回当前精确 Revision，旧接口继续提供强类型 response |
| Artifact List/Search | Memory Entry List/Search 等 | 仅部分重叠 | Artifact API 处理 Artifact head；Memory Entry API 继续处理 entry identity、citation 与 ranking |
| Artifact Replace | Candidate revise、Memory Entry revise | 不可合并 | 不绕过 Review，不把 Entry mutation 伪装为整个 Artifact Revision |
| Artifact Delete | Memory retire 等领域生命周期 | 不可直接合并 | Family 显式声明后才开放通用 Delete |
| `GET /v1/scopes` | `/v1/handoff-reports/scopes/list-known` | 后者是 Handoff Report 子集 | 保留旧接口；二者复用 Scope application layer 的授权 Scope 集合，旧接口再过滤 committed Handoff |
| Source Create + Memory Flush 客户端编排 | `/v1/memory/flush` | 复用现有命令 | 不增加服务端组合参数或新 response |

新接口不会删除或立即废弃任何领域 API。双入口必须通过 parity test，验证它们命中同一权威 Source/Artifact Revision、content digest、lineage、授权和错误语义。

# OpenAPI contract

`openapi/powercontext.yaml` 仍是唯一 HTTP 契约真相。实现时新增或复用以下 schema：

- `Source`
- `CreateSourceRequest`
- `SourceSummary`
- `SourceResult`
- `SourceQueryType`（`list` / `search`；缺省值为 `list`）
- `SourcePage`
- `ArtifactRevision`
- `ArtifactSummary`
- `ArtifactPage`
- `CreateArtifactRequest`
- `ReplaceArtifactRequest`
- `ArtifactSearchHit`
- `ArtifactSearchResultPage`
- `ArtifactDeletionStatus`
- `ScopeSummary`
- `ScopePage`

OpenAPI 还必须声明 `ETag` response header 与 `If-Match` request header。不得增加统一 Source/Artifact union schema、统一 selector 或统一引用 envelope。Family-specific `content` 通过 assembled Runtime 中已注册的 schema 校验；generated Client 将其暴露为 JSON object，强类型体验继续由现有 Family API 提供。

# Implementation plan

1. 在 OpenAPI 中保留 `POST /v1/sources/content`，增加 `POST /v1/sources`、Source Get，以及 operationId 为 `search_sources`、由 `type=list|search` 分流的统一 List/Search。
2. 增加 Artifact create、head get、exact revision get、list、search-result、replace 和 delete paths。
3. 建立 Source/Artifact 公共 application services，并让语义一致的既有接口委托它们。
4. 基于 Scope application layer 的权威目录增加 `GET /v1/scopes`，Source/Artifact 活动摘要使用独立读取投影。
5. 扩展 `/v1/capabilities`，按 Source type / Artifact Family 声明可用动作。
6. 运行 `make api-generate` 与 `make contract-test`，更新 checked-in generated Client。
7. 为 SQLite 与 OceanBase 增加相同的 API behavior、cursor、CAS、授权和幂等测试。
8. 增加 Source Create 后循环 Memory Flush 至 cursor 越过 position 的 SDK convenience example；不改变服务端契约。

# Acceptance criteria

| 场景 | 通过条件 |
| --- | --- |
| No umbrella concept | OpenAPI 中没有跨 Source/Artifact 的统一 selector、联合 request/response 或统一资源类型字段 |
| No write-time generation | Source Create request/response 只表达 Source 耐久写入，不包含任何生成参数或生成结果 |
| Source operations | Source 只公开 Create/Get/List/Search，不公开 Replace/Delete |
| Source list/search | `GET /v1/sources` 只有 `operationId: search_sources`；`type` 缺省或为 `list` 时 List，`type=search` 时 Search 且要求非空 `q` |
| Artifact operations | 固定 path 提供 Create/Get/List/Search/Replace/Delete；Replace 创建下一不可变 Revision |
| REST paths | URL 使用名词；Create 使用 POST，Get/List/Search 使用 GET，完整 Replace 使用 PUT，Delete 使用 DELETE |
| Exact identity | Source 使用无 Revision 的 SourceReference；Artifact head Get 和 exact revision Get 都返回包含 Revision 的 ArtifactReference |
| Scope required | 所有 Source/Artifact Get/List/Search/Mutation 都显式携带 `scope_id` |
| Scope discovery | `GET /v1/scopes` 返回调用方可见的持久 Scope；空 Scope 不因尚无 Source/Artifact 而消失 |
| Scope security | 授权过滤发生在分页与计数之前，不泄露不可见 Scope |
| Pagination | Source、Artifact、Scope List 与 Search 使用稳定 cursor，cursor 绑定完整查询和授权上下文 |
| Concurrency | Artifact Replace/Delete 必须携带 current head ETag；缺失返回 `428`，冲突返回 `412 revision_conflict` |
| Review gate | Experience/Skill 等 Review Family 不能通过基础 Create/Replace 绕过 Candidate approval |
| Memory boundary | Source Create + Memory Flush 是两个调用；flush 是 bounded pending window，不宣称 exact single-Source 或 full refresh |
| Compatibility | 现有 Source、Memory、Experience、Skill、Handoff 和 Candidate API 行为不变 |
| Source create compatibility | 新 `POST /v1/sources` 返回 `201 Source`；现有 `/v1/sources/content` 继续返回 `202 CaptureContentSourceResponse` |
| Extensibility | 新增 Direct Artifact Family 不增加基础 HTTP path 或 generated Client method |
| Conformance | SQLite 与 OceanBase 通过相同 contract 与行为测试 |

# Drawbacks

- Family-specific Artifact `content` 在基础 generated Client 中只能是 JSON object，静态类型弱于强类型 Family API。
- 新旧读取入口会并存一段时间，需要共享 application service 与 parity tests 防止行为漂移。
- Scope 列表中的 Source/Artifact 活动摘要增加读取投影及一致性维护成本。
- Direct Family 与 Review Family 的 mutation capability 不完全一致，调用方必须先读取 capabilities。
- Artifact logical delete、历史 lineage 可验证与 retention 之间仍需 Family 实现正确衔接。
- Source Create + Memory Flush 不是一个事务；客户端必须处理“Source 成功、flush 失败”的可重试状态。
- Source List 与 Search 共用 `search_sources` 和 `SourcePage`；客户端必须显式管理 `type`，Search 结果还需处理可选的命中字段。

# Alternatives

## 在 URL 中使用 `/add`、`/get`、`/list`、`/update`、`/delete`

这种方式与现有 command API 风格一致，但会放弃 HTTP GET 缓存、标准中间件、状态码和集合语义，也不符合本 RFC 的 REST contract，因此不采用。

## 所有动作都使用 POST

精确读取、确定性 List 和首期 Search 都不需要 request body，应使用 GET。Create 使用 POST，完整 Replace 使用 PUT，Delete 使用 DELETE。不能因 `scope_id` 复杂就把所有请求退回 POST；`scope_id` 可以安全放在 query parameter。

## 使用 `POST .../revisions` 表达 Artifact Replace

这种方式能直接表达“创建下一 Revision”，但用户面对的基础对象是 Artifact head，更新能力更适合对具名 head 使用 `PUT`。本 RFC 因此使用 `PUT /v1/artifacts/{artifact_id}` 完整替换 head，并通过 `If-Match` 做并发控制；Runtime 内部仍创建下一不可变 Revision。首期不接受 PATCH。

## 把 Scope 放入 path

PowerContext 既有 `scope_id` 是外部稳定身份，可能包含 `:` 和 `/`；即使新 ID 使用 path-safe 的 `scp_` 格式，也必须保持对既有 ID 的兼容。将 `scope_id` 放入 path 会造成网关、路由和双重解码风险，因此本 RFC 使用 query/body。

## 使用一个混合 Search

跨 Source type、跨 Artifact Family 的 ranking、分页和授权合并需要新的全局索引与 score 校准。基础企业场景按单 Scope、单 type/family 查询即可，首期不增加混合 Search。

## 从 Source/Artifact 反向推导 Scope

这种方式会把活动数据误当成 Scope identity，遗漏尚无 Source/Artifact 的空 Scope，并违背 Scope organization 设计。`GET /v1/scopes` 必须读取权威 Scope 目录；只有 Source/Artifact 活动摘要使用可重建的读取投影。

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
