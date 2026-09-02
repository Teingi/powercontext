- Proposal Name: `source_artifact_rest_api`
- Start Date: 2026-09-01
- RFC PR: [oceanbase/powercontext#0000](https://github.com/oceanbase/powercontext/pull/0000)
- Related RFCs: [RFC 0019](0019_local_source_memory_runtime.md)、
  [RFC 0048](0048_handoff_artifact.md)、[RFC 0050](0050_artifact_candidate_review_inbox.md)、
  [RFC 0051](0051_experience_skill_artifact_families.md) 和
  [RFC 1345](1345_scope_organization_and_agent_integration.md)

# Summary

本 RFC 为 PowerContext 增加 Source 与 Artifact 两组基础 REST API。Source 支持 Create、Get、List 和 Search；
Artifact 支持 Create、Get head、Get Revision、List、Search、Replace 和 Delete。List 与 Search 共用各自的集合
GET：省略或传入空白 `query` 时执行 List，传入非空 `query` 时执行 Search，因此共新增 9 个 HTTP operation。

新增 API 以 Scope 为父资源。Source 的公开身份是 `(scope_id, source_type, source_id)`；Artifact head 的公开身份
是 `(scope_id, family, artifact_id)`，精确 Revision 再增加 `revision`。具名资源的完整身份都进入 URI Path。
Create 在 Scope 下的父集合执行，由服务端生成 `source_id` 或 `artifact_id`。本 RFC 不增加统一 Resource 抽象，
不改变既有接口，也不把 Source 写入与 Memory、Experience、Skill 或 Handoff 生成合并为一次操作。

# Motivation

PowerContext 已有接口主要表达 Source capture、Memory flush、Candidate review 和 Handoff workflow 等领域动作。
这些接口保留了正确的领域边界，但调用方仍缺少一致、可预测的基础访问方式：

- 在指定 Scope 中创建和读取 Source；
- 按 Source type 稳定列举或检索 Source；
- 创建、读取、修订、列举、检索和逻辑删除正式 Artifact；
- 新增 Source type 或 Artifact Family 时复用固定的 HTTP surface，而不是新增一套 CRUD path；
- 需要写入后生成时，由客户端明确编排 Source Create 和既有领域命令。

该设计还需要把公开 API 字段与当前持久化模型对齐，明确哪些字段直接落库、哪些包含在 canonical payload 中、
哪些由 lineage 表表达、哪些只在请求期间生成，以及为了稳定时间和逻辑删除语义必须增加哪些持久化字段。

# Guide-level explanation

## 两类基础资源

Source 是没有 Revision 的耐久证据。创建成功后不可原地修改或删除；需要纠正时写入一个新的 Source，并由后续
Artifact lineage 表达所使用的精确证据。

Artifact 是可提交、可演进的正式制品。Create 提交 Revision 1；Replace 不覆盖旧内容，而是提交下一条不可变
Revision 并移动 head。调用方既可以读取当前 head，也可以读取一个精确的历史 Revision。

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

`source_id` 只要求在同一个 `(scope_id, source_type)` 集合内唯一；`artifact_id` 只要求在同一个
`(scope_id, family)` 集合内唯一。调用方不得脱离 Scope 和分类字段，把两者当作全局唯一 ID。

## 常见调用流程

创建一条文本 Source：

```http
POST /v1/scopes/scp_01J/sources
Content-Type: application/json
```

```json
{
  "source_type": "content",
  "content": "退款流程必须保留人工复核。",
  "metadata": {
    "title": "退款流程约束"
  }
}
```

成功响应返回完整身份和 canonical URI：

```http
HTTP/1.1 201 Created
Location: /v1/scopes/scp_01J/sources/content/src_01J
```

```json
{
  "scope_id": "scp_01J",
  "source_type": "content",
  "source_id": "src_01J",
  "content": "退款流程必须保留人工复核。",
  "metadata": {
    "title": "退款流程约束"
  },
  "created_at": "2026-09-02T12:00:00Z",
  "position": 42,
  "content_digest": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
}
```

Source Create 只完成耐久写入，不触发模型生成。需要立即生成 Memory 的调用方随后调用既有 Memory flush：

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

Memory flush 处理一个有界的待处理 Source window，不保证只处理刚创建的 Source，也不是全历史刷新。Source 已经
提交后，即使后续生成失败也不会回滚。

创建正式 Artifact 时，`family` 放在 request body 中，服务端生成 `artifact_id` 并提交 Revision 1：

```http
POST /v1/scopes/scp_01J/artifacts
Content-Type: application/json
```

```json
{
  "family": "company.example.decision",
  "content": {
    "title": "退款人工复核约束",
    "decision": "退款必须经过人工复核"
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

Artifact 首期不定义顶层 `metadata` 或 `schema_version`。标题、标签和其他 Family-specific 属性属于
`content`，由对应 Family 的模型负责验证。

## List 与 Search

List 和 Search 使用同一个类型集合 URI：

```http
GET /v1/scopes/scp_01J/sources/content?limit=50
GET /v1/scopes/scp_01J/sources/content?query=退款&mode=auto&limit=20

GET /v1/scopes/scp_01J/artifacts/company.example.decision?limit=50
GET /v1/scopes/scp_01J/artifacts/company.example.decision?query=退款&mode=auto&limit=20
```

省略、空字符串或仅空白的 `query` 表示 List；非空 `query` 表示 Search。两种行为统一返回
`query + mode + items + next_cursor`。List 的 `query`、`mode` 和 `score` 为 `null`，`snippets` 为 `[]`。

# Reference-level explanation

## Scope、层级与 canonical URI

`scope_id` 是资源 owner、授权边界和公开身份的一部分。Scope 的创建、读取、列举、组织关系和 binding 由
[RFC 1345](1345_scope_organization_and_agent_integration.md) 及其实现负责；本 RFC 不定义 Scope API，只定义
已有 Scope 下的 Source 和 Artifact 子资源。

所有新增业务 API 遵循：

```text
{scheme}://{endpoint}/{resource-path}?{query-string}
```

- 生产环境使用 `https`；endpoint 只表示部署地址，不承载业务语义；
- path 使用小写复数名词，多单词静态 segment 使用 `kebab-case`；
- JSON 与 query 参数使用 `snake_case`，URI 末尾不加 `/`；
- path 不出现 `/add`、`/get`、`/update` 或 `/delete` 等 CRUD 动词；
- query string 只承载查询、搜索模式和分页，不承载具名资源的公开唯一键；
- `source_type` 和 `family` 必须编码为单个 path segment，不能包含未转义的 `/`。

本文允许的 resource path 为：

```text
/v1/scopes/{scope_id}/sources
/v1/scopes/{scope_id}/sources/{source_type}
/v1/scopes/{scope_id}/sources/{source_type}/{source_id}

/v1/scopes/{scope_id}/artifacts
/v1/scopes/{scope_id}/artifacts/{family}
/v1/scopes/{scope_id}/artifacts/{family}/{artifact_id}
/v1/scopes/{scope_id}/artifacts/{family}/{artifact_id}/revisions/{revision}
```

Create 在父集合 `/sources` 或 `/artifacts` 上执行，分类由 body 中的 `source_type` 或 `family` 指定。类型集合
GET 位于 `/sources/{source_type}` 或 `/artifacts/{family}`。具名 Source、Artifact head 和 Artifact Revision
的完整复合身份都进入 Path。

如果未来一个资源可共享给其他 Scope，canonical URI 仍使用 owner Scope。授权不能为同一资源生成第二个 Scope
路径。改变 owner Scope、`source_type` 或 `family` 会改变公开身份，应视为创建新资源或执行显式迁移。

## 新增 operation

本文提供 9 个 HTTP operation，覆盖 11 项基础能力：

| 对象 | 能力 | operationId | HTTP 方法与 URI | 输入 | 成功返回 |
| --- | --- | --- | --- | --- | --- |
| Source | Create | `create_source` | `POST /v1/scopes/{scope_id}/sources` | body：`source_type?`、`content`、`metadata?` | `201 SourceRecord` + `Location` |
| Source | Get | `get_source` | `GET /v1/scopes/{scope_id}/sources/{source_type}/{source_id}` | 完整复合身份位于 Path | `200 SourceRecord` |
| Source | List/Search | `list_sources` | `GET /v1/scopes/{scope_id}/sources/{source_type}` | query：`query?`、`mode?`、`limit?`、`cursor?` | `200 SourcePage` |
| Artifact | Create | `create_artifact` | `POST /v1/scopes/{scope_id}/artifacts` | body：`family`、`content`、引用 | `201 ArtifactRevision` + `Location` + `ETag` |
| Artifact | Get head | `get_artifact` | `GET /v1/scopes/{scope_id}/artifacts/{family}/{artifact_id}` | `If-None-Match?` | `200 ArtifactRevision` + `ETag` 或 `304` |
| Artifact | Get Revision | `get_artifact_revision` | `GET /v1/scopes/{scope_id}/artifacts/{family}/{artifact_id}/revisions/{revision}` | 完整 Revision 身份位于 Path | `200 ArtifactRevision` |
| Artifact | List/Search | `list_artifacts` | `GET /v1/scopes/{scope_id}/artifacts/{family}` | query：`query?`、`mode?`、`limit?`、`cursor?` | `200 ArtifactPage` |
| Artifact | Replace | `replace_artifact` | `PUT /v1/scopes/{scope_id}/artifacts/{family}/{artifact_id}` | `If-Match`；完整 replacement body | `200 ArtifactRevision` + 新 `ETag` |
| Artifact | Delete | `delete_artifact` | `DELETE /v1/scopes/{scope_id}/artifacts/{family}/{artifact_id}` | `If-Match` | `204 No Content` |

OpenAPI 同一个 method/path 只定义一个 operation。集合 GET 的 operationId 分别固定为 `list_sources` 和
`list_artifacts`；非空 `query` 改变查询语义，但不创建第二个 method/path，也不引入 `type=list|search`。

## Wire schemas

### Source schemas

`CreateSourceRequest`：

```json
{
  "source_type": "可选 string；缺省为 content",
  "content": "必填 JSON value；由 source_type 对应 adapter 校验",
  "metadata": "可选 object；缺省为 {}，只保存并返回"
}
```

请求不接受 `scope_id` 或 `source_id`。`scope_id` 来自 Path，`source_id` 由服务端生成。所有通过该通用 API
开放的 Source adapter 必须无损保存并返回 `metadata`，不能静默丢弃。

`SourceRecord`：

```json
{
  "scope_id": "string；owner Scope",
  "source_type": "string；Source adapter 名称和类型集合",
  "source_id": "string；集合内稳定 ID",
  "content": "JSON value；持久化后的 canonical content",
  "metadata": "object；缺省为 {}",
  "created_at": "RFC 3339 UTC date-time；服务端持久化时间",
  "position": "integer；Scope Source journal 位置",
  "content_digest": "sha256:<64 lowercase hexadecimal characters>"
}
```

`SourceCollectionItem` 不返回完整 `content`：

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

`CreateArtifactRequest`：

```json
{
  "family": "必填 string；Artifact Family",
  "content": "必填 object；Revision 1 的完整 Family content",
  "source_refs": "可选 SourceReference[]；缺省为 []",
  "artifact_refs": "可选 ArtifactReference[]；缺省为 []"
}
```

`ReplaceArtifactRequest` 不重复 Path 身份：

```json
{
  "content": "必填 object；下一 Revision 的完整 Family content",
  "source_refs": "可选 SourceReference[]；省略时恢复为 []",
  "artifact_refs": "可选 ArtifactReference[]；省略时恢复为 []"
}
```

`ArtifactRevision`：

```json
{
  "scope_id": "scp_01J",
  "artifact_ref": {
    "family": "company.example.decision",
    "artifact_id": "dec_01J",
    "revision": 2
  },
  "content": {
    "title": "退款人工复核约束",
    "decision": "退款必须经过人工复核"
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

`artifact_ref` 本身不包含 `scope_id`；只有与顶层 `scope_id` 组合后才构成完整公开身份。`source_refs` 和
`artifact_refs` 同样继承当前 Artifact 的 Scope，本 RFC 不表达跨 Scope lineage。

`ArtifactCollectionItem` 只表示未删除 Artifact 的当前 head，不返回完整 `content` 或历史 Revision：

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

### Source Get 和集合 GET

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
    "request": "GET /v1/scopes/scp_01J/sources/content?query=退款&mode=auto&limit=20",
    "success": "200 SourcePage<SourceCollectionItem>"
  }
]
```

### Artifact Get 和集合 GET

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
    "request": "GET /v1/scopes/scp_01J/artifacts/company.example.decision?query=退款&mode=auto&limit=20",
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
    "title": "退款人工复核约束",
    "decision": "退款必须经过人工复核",
    "rationale": "满足资金安全要求"
  },
  "source_refs": [],
  "artifact_refs": []
}
```

PUT 是完整替换。成功时创建 Revision 2，返回 `200 ArtifactRevision` 和新的 ETag。省略可选引用数组表示恢复为
`[]`，不表示保留上一 Revision；接口不支持 merge patch 或自动合并。

### Artifact Delete

```http
DELETE /v1/scopes/scp_01J/artifacts/company.example.decision/dec_01J
If-Match: "revision:2"
```

成功逻辑删除返回 `204 No Content`。历史 Revision 保留，本 RFC 不提供 restore 或 purge。

## 集合查询和 Cursor

集合 GET 接受：

| 参数 | 必填性 | 含义 |
| --- | --- | --- |
| `query` | 可选 | 规范化后为空时 List，非空时 Search。 |
| `mode` | 可选 | 期望的检索模式；`auto` 允许服务端选择实际模式。仅在 `query` 非空时有效。 |
| `limit` | 可选 | 本页最多返回的 item 数量。 |
| `cursor` | 可选 | 上一页返回的不透明游标，必须与当前调用方、集合路径和查询条件一致。 |

统一 response envelope：

```json
{
  "query": null,
  "mode": null,
  "items": [],
  "next_cursor": null
}
```

Search 返回规范化后的 `query`、实际 `mode`、每个 item 的 `score` 和 `snippets`。普通 List 的 `query`、
`mode` 和 `score` 为 `null`，`snippets` 为 `[]`。Response 不返回 `total`。

Cursor 绑定调用方、endpoint、完整集合路径、规范化查询、过滤条件、排序和实际搜索模式。List 与 Search 的 cursor
不能交叉使用。v0.1 只支持向后翻页；非法或参数不匹配返回 `400 invalid_cursor`，过期返回
`410 cursor_expired`。HTTP pagination cursor 与内部 `pc_source_cursors.cursor` 没有映射关系；后者保存领域
binding 对 Source journal 的消费进度。

## 请求、响应和错误

- “请求组成”中的 Path、Query、Header 和 Body 是参数位置，不是一个整体 JSON payload；
- GET 和 DELETE 没有 request body；
- Request schema 默认 `additionalProperties: false`，明确的 Source `metadata` 对象除外；
- Response 允许未来增加可选字段，客户端必须忽略未知响应字段；
- Source `metadata` 缺省 `{}`，引用数组和 `snippets` 缺省 `[]`，无排名时 `score` 为 `null`；
- 时间使用 RFC 3339 UTC，枚举使用 `lower_snake_case`；
- 所有响应都返回 `X-PowerContext-Request-ID`。

| 状态码 | 语义 |
| --- | --- |
| `200` | Get、List、Search 或 Replace 成功。 |
| `201` | Source 或 Artifact 已同步创建；必须返回 `Location`。 |
| `204` | Delete 成功且无 response body。 |
| `304` | `If-None-Match` 命中。 |
| `400` | Query、格式或 cursor 非法。 |
| `401` | 未认证；返回 `WWW-Authenticate`。 |
| `403` | 无权访问显式指定的 Scope。 |
| `404` | 资源不存在或对调用方隐藏。 |
| `405` | Family 不支持该操作；返回 `Allow`。 |
| `409` | 资源身份或生命周期状态冲突。 |
| `410` | Cursor 已过期。 |
| `412` | `If-Match` 与当前 ETag 不一致。 |
| `413` | Request body 过大；不用于表示 response 过大。 |
| `422` | 字段或 Family content 校验失败。 |
| `428` | 缺少必须的 `If-Match`。 |
| `429` | 请求限流；返回 `Retry-After`。 |
| `503` | 声明的能力暂时不可用。 |

错误统一返回：

```json
{
  "error": {
    "code": "invalid_request",
    "message": "The request is invalid.",
    "details": {}
  }
}
```

错误不得放在 `200` 成功 envelope 中。

## 创建重试、缓存和并发

Source Create 和 Artifact Create 都不接受 `Idempotency-Key`。每次成功调用都创建一个新资源；请求结果未知时直接
重试可能产生重复资源。ID 由服务端生成，并通过 response body 和 `Location` 返回。

Artifact Create、Get head 和 Replace 返回 ETag。Get head 可携带 `If-None-Match`，命中时返回无 body 的
`304`。Replace 和 Delete 必须携带 `If-Match`；缺失返回 `428`，与当前 head 不匹配返回 `412`。

Delete 第一次成功返回 `204`；服务端能够确认是同一次删除的重试时仍返回 `204`。资源从未存在、已无法确认重试
身份或对调用方不可见时返回 `404`。

## Family capability boundaries

固定 Artifact URI 不表示每个 Family 都允许直接写入：

| Family 类型 | Read | Create/Replace/Delete |
| --- | --- | --- |
| Direct | 读取已提交 Artifact | 按 Family capability 开放。 |
| Review | 只读取审批后的 Artifact | 返回 `405 operation_not_supported`，继续使用 Candidate Review。 |
| Memory | 读取 Artifact head，不替代 Entry API | 继续使用 Memory 领域命令。 |
| Handoff | 读取已提交 Handoff | 继续使用 prepare/finalize/commit workflow。 |

Candidate 不是 Artifact；pending 或 rejected Candidate 不进入 Artifact List/Search。

## API 字段与持久化映射

以下表名和列名描述当前 `SHARED_METADATA` 的实现映射，不是客户端契约。实现可以重构内部表，但必须保持 OpenAPI
字段语义。

映射状态：

```json
{
  "direct": "直接读写现有关系表列",
  "encoded": "包含在现有 canonical payload/content 二进制列中",
  "relation": "API 数组拆分为有序关系表记录",
  "derived": "根据持久化数据确定性生成，无需独立列",
  "runtime": "只在 HTTP、搜索或分页过程中使用",
  "new_column": "当前 master 缺失，保留 API 语义时必须增加"
}
```

### Source 字段映射

| API 字段 | 持久化字段 | 映射 | 含义 |
| --- | --- | --- | --- |
| `scope_id` | `pc_sources.scope_id` | `direct` | owner Scope、授权边界和复合身份分量；最长 256 字符，按字节精确比较。 |
| `source_type` | `pc_sources.source_type` | `direct` | adapter 稳定名称和类型集合；最长 128 字符，Create 缺省 `content`。 |
| `source_id` | `pc_sources.source_id`；类型化 Source 的 `name` 与其一致 | `direct` | 集合内稳定 ID；服务端生成，最长 256 字符。 |
| `content` | `pc_sources.payload` | `encoded` | 完整类型化 Source 模型中的证据内容；`content` adapter 对应 `ContentSource.content`。 |
| `metadata` | `pc_sources.payload` 中的 Source metadata | `encoded` | 只保存并返回的扩展属性；不建立独立列，当前 API 不按 metadata 查询、排序或索引。 |
| `created_at` | 目标 `pc_sources.created_at` | `new_column` | Source 首次成功持久化的服务端 UTC 时间。 |
| `position` | `pc_sources.journal_position` | `direct` | Scope journal 中单调递增且唯一的位置。 |
| `content_digest` | 无独立列 | `derived` | canonical API `content` 的 SHA-256 摘要。 |

`pc_source_journal_heads.position` 是 Scope journal 高水位和位置分配依据，不是单条 Source 的 response 字段。

### Artifact 字段映射

| API 字段 | 持久化字段 | 映射 | 含义 |
| --- | --- | --- | --- |
| `scope_id` | Artifact、head 和 lineage 表的 `scope_id` | `direct` | owner Scope、授权边界和复合身份分量；最长 256 字符。 |
| `artifact_ref.family` | `pc_artifacts.family`、`pc_artifact_heads.family` | `direct` | Family 和 adapter 路由；最长 128 字符。Create 的 `family` 来自 body。 |
| `artifact_ref.artifact_id` | `pc_artifacts.artifact_id`、`pc_artifact_heads.artifact_id` | `direct` | 生命周期稳定 ID；服务端生成，最长 128 字符。 |
| `artifact_ref.revision` | `pc_artifacts.revision`；head 由 `pc_artifact_heads.revision` 指向 | `direct` | 从 1 开始递增的不可变 Revision。 |
| `artifact_ref` | 无单独 JSON 列 | `derived` | 由 family、artifact ID 和 Revision 组装，并与顶层 Scope 共同定位。 |
| `content` | `pc_artifacts.content` | `encoded` | 通过 Family content model 校验后的 canonical JSON bytes。 |
| `source_refs` | `pc_artifact_lineage_sources` | `relation` | 按数组顺序保存的同 Scope Source 引用。 |
| `artifact_refs` | `pc_artifact_lineage_artifacts` | `relation` | 按数组顺序保存的同 Scope 上游 Artifact Revision 引用。 |
| `created_at` | 目标 `pc_artifacts.created_at` | `new_column` | 当前 Revision 成功提交的服务端 UTC 时间。 |
| `content_digest` | 无独立列 | `derived` | canonical Artifact content 的 SHA-256 摘要。 |

Artifact 不定义顶层 `metadata`，因此不新增 `pc_artifacts.metadata`，也不改变 `pc_artifacts.content` 的现有
Family content 序列化格式。

`source_refs` 按以下关系列保存：

```json
{
  "child_identity": [
    "scope_id",
    "family",
    "artifact_id",
    "revision"
  ],
  "ordinal": "服务端根据数组顺序生成",
  "source_refs[].source_type": "source_type",
  "source_refs[].source_id": "source_id"
}
```

`artifact_refs` 按以下关系列保存：

```json
{
  "child_identity": [
    "scope_id",
    "family",
    "artifact_id",
    "revision"
  ],
  "ordinal": "服务端根据数组顺序生成",
  "artifact_refs[].family": "upstream_family",
  "artifact_refs[].artifact_id": "upstream_artifact_id",
  "artifact_refs[].revision": "upstream_revision"
}
```

### 运行时和内部字段

| 字段 | 持久化关系 | 含义 |
| --- | --- | --- |
| `query`、`mode`、`limit` | `runtime` | 只控制本次集合查询。 |
| `cursor`、`next_cursor` | `runtime` | HTTP 分页令牌，不写入业务资源。 |
| `score`、`snippets` | `runtime` | Search 排名和命中展示信息，不写回资源。 |
| `Location` | `derived` | 根据完整公开身份组装 canonical URI。 |
| `ETag` | `derived` | 根据当前 `pc_artifact_heads.revision` 生成。 |
| `If-Match`、`If-None-Match` | `runtime` | 与当前 ETag 比较，不单独保存。 |
| `X-PowerContext-Request-ID` | `runtime` | 单次请求追踪 ID。 |
| `pc_artifact_heads.searchable_text` | Artifact Search 内部投影 | 当前 head 的检索文本；每个可搜索 Family 提供确定性 projector。 |
| Source 搜索投影 | Source Search 内部投影 | master 当前无通用列；v0.1 可读取 payload 检索，扩展时可增加内部投影/索引。 |
| 目标 `pc_artifact_heads.deleted_at` | Artifact 生命周期 | `null` 表示有效，非 `null` 表示逻辑删除时间；保留 head Revision。 |

说明性文档中的 `status`、`notes`、`precondition_errors`、`retry` 和 `not_found` 不是实际 response body 字段，
不映射数据库列。

### 必要的表结构适配

| 表 | 新字段 | 必要性 | 迁移规则 |
| --- | --- | --- | --- |
| `pc_sources` | `created_at` | 必须 | 新写入记录 UTC 时间；历史行无法可靠恢复时允许 `null`。 |
| `pc_artifacts` | `created_at` | 必须 | 每个新 Revision 记录 UTC 提交时间；历史行无法可靠恢复时允许 `null`。 |
| `pc_artifact_heads` | `deleted_at` | 必须 | 未删除 head 为 `null`；Delete 写入 UTC 时间并保留当前 Revision。 |

`content_digest`、ETag、Location、搜索信息和 pagination cursor 都可派生或只在请求期间存在，不增加数据库列。

Digest 计算规则：

```json
{
  "algorithm": "sha256",
  "input": "API content 的 UTF-8 canonical JSON bytes",
  "object_key_order": "lexicographic",
  "insignificant_whitespace": "removed",
  "included_fields": [
    "content"
  ],
  "output": "sha256:<64 lowercase hexadecimal characters>"
}
```

## 既有接口兼容性

本 RFC 只定义新增接口。既有接口的 path、request、response、状态码、引用 schema 和领域行为均不修改。新增入口
必须读写相同的权威 Source journal、Artifact Revision、lineage 和授权结果，不能创建第二套数据或身份空间。

新增 API 采用服务端生成 ID，而现有领域入口是否由调用方提供稳定 ID 不属于本 RFC。两类入口可以在应用服务层
适配，但必须最终遵守同一组持久化唯一键和读写不变量。

## 实现与验收

实现顺序：

1. 在 `openapi/powercontext.yaml` 增加本文 9 个 operation 和独立 request/response schema；
2. 生成 checked-in HTTP 模型和 operation；
3. 复用现有 Source repository、Artifact repository、lineage 和授权服务；
4. 增加 `created_at` 和 `deleted_at` 持久化字段及 SQLite/OceanBase 迁移检查；
5. 实现稳定 List/Search cursor、ETag 和条件请求；
6. 运行 `make api-generate`、`make contract-test`、`make test` 和 `make docs-test`。

验收条件：

- 仅在本文列出的两棵 Scope 子资源树新增 operation，不重复定义 Scope API；
- Source 只提供 Create、Get、List/Search，Create 不接收 `source_id`；
- Artifact 提供 Create、Get head、Get Revision、List/Search、Replace 和 Delete，Create 不接收 `artifact_id`；
- Create 不接受 `Idempotency-Key`，并返回服务端生成 ID 和 `Location`；
- 具名 GET 的完整复合身份位于 Path；
- 非空 `query` 执行 Search，否则执行 List；不出现 `type=list|search`；
- Replace 创建下一不可变 Revision，并通过 ETag/If-Match 防止并发覆盖；
- Artifact 不出现顶层 `metadata` 或 `schema_version`；
- Source `metadata` 无损写入和返回，并复用 `pc_sources.payload`；
- Review Family 不能通过基础 API 绕过 Candidate approval；
- SQLite 与 OceanBase 通过相同 contract 和行为测试。

# Drawbacks

- 复合身份使 URI 较长；owner Scope、Source type 或 Artifact Family 变化时 canonical URI 也会变化。
- Family-specific `content` 在通用 generated Client 中只能表现为 JSON object，静态类型弱于专用 Family API。
- Source List 为返回 metadata 需要解码类型化 payload；通用 Source Search 在增加投影前可能需要扫描 payload。
- Create 不提供幂等键；网络结果未知时客户端重试可能创建重复资源。
- Source Create 与后续生成不是事务，客户端必须处理生成失败和重试。
- 逻辑删除及稳定时间字段需要持久化迁移，历史记录无法可靠补回原始时间。

# Rationale and alternatives

## 不增加统一 Resource API

Source 是不可变证据，Artifact 是带 Revision 和生命周期的正式制品；二者的更新、删除和 lineage 语义不同。统一
`/resources` 会迫使客户端使用 selector 或 union schema，并把 Family 能力边界推迟到运行时错误，因此保留两组
固定资源 API。

## 使用 Scope 子资源和完整 Path 身份

把 `scope_id`、`source_type`/`family` 和 ID 放入具名资源 Path，使 canonical URI、权限审计、缓存键和日志都包含
完整公开身份。将身份分量放在必填 query 中虽然可以路由，但会让 path 只表示“半个资源”，不采用该方案。

Create 在 `/sources` 和 `/artifacts` 父集合执行，因为服务端生成 ID，且 `source_type`/`family` 在创建时来自 body。
创建后分类成为资源身份，因此出现在类型集合和 item URI 中。

## 合并 List 与 Search

独立 `/search-results` 可以提供不同 response schema，但会增加额外集合路径和 generated Client operation。本 RFC
选择统一 `SourcePage`/`ArtifactPage`，让 `query`、`mode`、`score` 和 `snippets` 在 List 时使用明确的空值，
从而允许同一个集合 GET 同时提供稳定 List 和相关性 Search。GET request body 和 `type=list|search` 都不采用。

## 服务端生成 ID，但不提供创建幂等键

服务端生成 ID 简化调用方并避免要求外部系统构造内部 identity。首期不提供 `Idempotency-Key`，代价是结果未知的
重试可能重复创建；这是显式接受的 v0.1 限制，而不是隐式幂等保证。

## Source metadata 复用 payload

当前 API 只保存并返回 Source metadata，不按其过滤、排序或索引。`ContentSource` 已把 metadata 包含在
`pc_sources.payload` 中，因此不增加独立列。Artifact 没有等价的通用 metadata 语义，首期直接删除该字段，
而不是改变 `pc_artifacts.content` 的 Family-specific 存储格式。

# Prior art

本设计直接建立在 PowerContext 已有的 Scope、Source journal、Artifact Repository、ArtifactRef、SourceRef、
lineage、Candidate Review 和领域命令之上。Source journal position 已提供稳定处理边界；Artifact head 与不可变
Revision 已提供修订和并发基础；本 RFC 只为这些现有领域对象增加一致的基础 HTTP surface。

HTTP 方法、名词资源路径、`Location`、ETag 条件请求、RFC 3339 时间和标准错误状态码沿用通用 HTTP/REST 约定，
但本文的复合身份、Family capability 和生成边界由 PowerContext 领域模型决定。

# Unresolved questions

本 RFC 没有阻塞合并的未决问题。以下实现选择不影响公开契约，可以在实现 PR 中确定：

- 服务端生成 ID 的具体算法，只要值是不透明、path-safe 且满足长度限制；
- Cursor 的签名和编码格式，只要保持不透明、绑定查询上下文并具有规定的错误语义；
- Source Search 在 v0.1 使用 payload 扫描还是内部投影，只要结果契约保持一致；
- 历史 `created_at` 无法恢复时在迁移和 response 中采用 nullable 兼容的具体落地方式。

跨 Scope 共享与授权、跨 type/family Search、复杂 POST Search、Artifact restore、retention、管理员 purge 和批量
mutation 明确不属于本 RFC，需要独立设计。

# Future possibilities

- 为 Source 和更多 Artifact Family 增加独立全文或向量检索投影；
- 当复杂条件无法由 query string 稳定表达时，单独设计无创建副作用的 POST Search；
- 增加跨 type、跨 Family 的统一 ranking，但不改变具名资源 URI；
- 增加 Artifact restore、retention 和管理员 purge；
- 在独立 RFC 中定义 owner Scope 之外的 read/write grant 和跨租户授权；
- 在有明确重试需求后，为 Create 增加有 TTL 和原始响应重放语义的幂等键。
