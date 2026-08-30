- Proposal Name: `handoff_access_control`
- RFC Number: 1396
- Start Date: 2026-08-30
- Status: Draft
- RFC PR: [oceanbase/powercontext#1396](https://github.com/oceanbase/powercontext/pull/1396)
- Tracking Issue: [oceanbase/powercontext#1395](https://github.com/oceanbase/powercontext/issues/1395)
- Related RFCs: [RFC 0011](0011_remote_access_architecture.md)、[RFC 0048](0048_handoff_artifact.md)、
  [RFC 0082](0082_handoff_report.md)、[RFC 1223](1223_human_agent_work_continuity.md)

# Summary

本 RFC 为 PowerContext Server 定义独立的 Access Control 边界，并把 Handoff 作为第一种资源级授权场景。它回答一个
具体问题：当用户 A 把一份 Handoff 交给用户 B 时，B 可以看到什么、可以做什么，以及这些权限如何撤销和审计。

Handoff 内容不保存用户、角色或 ACL。`scope_id` 继续表示 Workstream 的稳定业务分区，不是用户身份、tenant、角色或
安全边界。身份认证和权限判定发生在 Server：认证层得到可信 Principal，Policy Enforcement Point（PEP）把
Principal、action 和 resource 交给可替换的 `AuthorizationProvider`，得到允许或拒绝决定后，才调用现有 Runtime
application service。

```text
Identity Provider or static credential
                |
                v
        Authenticated Principal
                |
                v
       PowerContext Server PEP
                |
                v
       AuthorizationProvider  <---->  Policy or relationship store
                |
          allow or deny
                |
                v
       Existing application service
```

用户 A 可以选择两种交接方式：

- 为长期协作者授予 Workstream 级角色；
- 只把一个已提交的精确 Handoff Revision 授予 B。

第二种方式是首版的最小权限路径。B 可以读取该 Handoff、通过 Handoff resolver 检查其中明确引用的 evidence，并对
同一个精确 Revision 留下 Receipt；B 不会因此看到同一 scope 的其他 Handoff、Memory 或 Source，也不会获得提交
新 Handoff、记录 Task Outcome、使用工具、访问网络或读取凭据的权限。`accepted` Receipt 记录接收结果，不授予权限。

PowerContext 定义稳定的授权 request/decision、内置角色、Access API 和 OpenAPI extension，但不绑定一个策略引擎。
首版提供内置 Role Binding Store；Casbin、OpenFGA 和兼容 OpenID AuthZEN Authorization API 的 Policy Decision
Point（PDP）可以通过 adapter 接入。

# Motivation

PowerContext 已经拥有临时 Prepared Handoff、不可变 Handoff Revision、Continue、Receipt 和 Task Outcome，但现有
Server 认证是可选的全局静态 Bearer。一个有效 token 可以访问所有受保护 operation，Server 无法表达：

- A 可以管理 Workstream，而 B 只能看一份交接；
- B 可以确认接收，但不能提交新的里程碑；
- 团队成员可以查看 Handoff Report，但不能审批 Experience 或 Skill；
- 被撤销的接收方不能继续读取后续 Revision；
- HTTP、MCP 和 Dashboard 对同一个 Principal 得到相同判定。

RFC 0048 要求接收方能够读取 Handoff 所属 scope 及其 evidence。直接把 B 加入整个 scope 虽然满足该要求，却会暴露
与这次交接无关的 Memory、Source 和历史。只把 Handoff 正文复制给 B 又会丢失 exact evidence、Receipt 和撤销能力。

RFC 1223 中 `acknowledge_handoff` 的 authorization check 是接收方对实时环境的观察。它用于判断“当前是否具备继续
条件”，不认证 B 的身份，也不是 ACL。自然语言里的 `receiver`、`authorization_notes` 或 “请继续执行”同样不能
成为权限凭据。

因此，Handoff 需要一个独立于内容和 Runtime domain API 的授权层。这个层必须同时支持最小权限分享、团队角色、外部
PDP、列表过滤、审计和 fail-closed 行为，而不能让 Agent、请求 body 或 `scope_id` 自行决定权限。

# Guide-level explanation

## 建立直觉：交接内容和交接权限是两件事

Handoff 回答“工作到了哪里”；Access Binding 回答“谁现在可以对这份交接做什么”。两者具有不同生命周期：

```text
Prepared Handoff -> Commit -> immutable Handoff Revision
                                  |
                                  +-> Access Binding for user B
                                           |
                                  read / inspect / acknowledge
                                           |
                                    expire or revoke
```

提交新 Handoff 不会自动分享，分享也不修改 Handoff 内容或 Revision。撤销 Binding 不删除 Handoff、Receipt 或审计事件。

## A 把一份精确 Handoff 交给 B

假设 A 负责 `project:payments` Workstream，并已完成一份交接。正常流程如下：

1. A 检查并提交 Prepared Handoff，得到不可变 `ArtifactReference`：

   ```json
   {
     "family": "handoff",
     "artifact_id": "project:payments",
     "revision": 12
   }
   ```

2. A 明确选择接收方 B。Dashboard 或集成层把 B 从企业身份目录解析为可信的 canonical Principal；模型输出、显示名或
   邮箱文本不能替代该解析。
3. Server 检查 A 对 `project:payments` 是否拥有 `scope.delegate`。
4. Server 创建角色为 `handoff.receiver` 的 Access Binding，资源是上面的精确 Revision，可选设置过期时间。
5. B 使用自己的凭据登录。`resources/list` 返回 B 有权读取的精确 Handoff，B 不需要知道 A 的 token，也不接收新的
   bearer share link。
6. B 使用 exact selection 调用 Continue。Server 读取同一 Revision，并只解析它明确引用的 evidence。
7. B 检查当前 workspace、能力和授权状态后，可以对同一 Revision 留下 `accepted`、`needs_clarification` 或
   `declined` Receipt。

创建 Binding 的请求示例为：

```json
{
  "subject": {
    "type": "user",
    "issuer": "https://id.example.com/",
    "id": "00u-bob"
  },
  "resource": {
    "type": "handoff",
    "scope_id": "project:payments",
    "reference": {
      "family": "handoff",
      "artifact_id": "project:payments",
      "revision": 12
    }
  },
  "role": "handoff.receiver",
  "expires_at": "2026-09-06T12:00:00Z",
  "reason": "Continue the payment retry investigation",
  "idempotency_key": "transfer-payments-12-to-bob"
}
```

`granted_by`、创建时间和 policy revision 由 Server 填充，调用方不能伪造。

## B 能看到什么

`handoff.receiver` 是精确资源角色，不是 scope role：

| 操作 | 结果 | 原因 |
| --- | --- | --- |
| 读取 Handoff Revision 12 | 允许 | Binding 指向该精确 Revision |
| 通过 Continue 检查 Revision 12 的引用 | 允许 | `handoff.evidence.read` 只覆盖该 Revision 的 citation manifest |
| Acknowledge Revision 12 | 允许 | receiver 可以为已检查的 exact Handoff 留 Receipt |
| 请求 `latest` | 拒绝 | latest 可能是 B 未获授权的后续 Revision |
| 读取 Revision 11 或 13 | 拒绝 | 精确 Binding 不继承到其他 Revision |
| 打开聚合 Handoff Report | 拒绝 | Report 包含 scope 级历史和统计 |
| 搜索 scope Memory 或列出 Source | 拒绝 | Handoff Binding 不授予通用 scope read |
| Commit 新 Handoff 或记录 Task Outcome | 拒绝 | 需要 `scope.contribute` |
| 审批 Candidate | 拒绝 | 需要独立的 `scope.review` |

Evidence 的最小权限不是逐条复制 Source 或 Memory，也不是让外部 PDP 保存全部 citation。Server 先从不可变 Handoff
Revision 得到 citation manifest，再检查 B 是否对该 Handoff 拥有 `handoff.evidence.read`，最后只通过 Handoff
resolver 解引用 manifest 中的 exact citation。B 不能把任意 Source ID 填入通用读取 API 来复用这项权限。

如果一条 citation 已被删除、retire、损坏或因更高层策略被拒绝，Continue 把对应 evidence 标记为 unavailable。
Handoff Binding 不覆盖 retention、legal hold、数据分类或显式 deny policy。

## B 真正接手 Workstream

查看交接不等于获得执行权。若 B 将长期推进该 Workstream，A 或管理员需要另行授予 `scope.contributor`：

```text
handoff.receiver
  = read one exact Handoff + inspect its citations + acknowledge it

scope.contributor
  = read the Workstream + contribute Sources + prepare/commit Handoffs
    + acknowledge Handoffs + record Task Outcomes
```

PowerContext 权限只控制 PowerContext 资源和 operation。修改 Git 仓库、调用云 API、访问生产环境或读取凭据仍由宿主、
操作系统和外部服务授权。Handoff、Role Binding 和 Receipt 都不能扩大这些权限。

## 长期团队协作

对固定团队，可以把用户或外部 group 绑定为 scope role，而不是为每个 Revision 创建 Binding：

- `scope.viewer`：读取当前 scope 的 Handoff、Memory、Source 和只读投影；
- `scope.contributor`：在 viewer 基础上写入工作 evidence、Handoff 和 Outcome；
- `scope.reviewer`：在 viewer 基础上评审 Artifact Candidate；
- `scope.delegator`：在 viewer 基础上把精确 Handoff 分享给接收方；
- `scope.admin`：管理该 scope 的全部角色和策略。

固定角色是 wire-contract vocabulary，不要求外部 PDP 使用相同内部存储。外部系统可以把企业角色、团队或关系映射为
这些 action。

## 撤销和过期

A 或 scope admin 可以撤销 A 创建的精确 Handoff Binding。撤销后：

- B 的后续 read、Continue 和 acknowledge 返回 403；
- B 不再从 `resources/list` 看到该 Handoff；
- 已保存的 Handoff、Receipt 和 Access Audit 不被删除；
- 已经展示、导出或复制给 B 的内容无法被远程收回。

过期时间由 PDP 使用可信 Server time 判断。Adapter 不支持条件或 expiration 时必须拒绝创建带过期时间的 Binding，
不能静默创建永久授权。

角色变更使用 revoke + create，不原地把 `handoff.viewer` 升级为 `handoff.receiver`。撤销使用 `expected_version`，并发
修改返回 409。

## 授权服务不可用

授权是安全依赖。配置为 enforced mode 时：

- 没有或无法验证身份返回 401；
- 身份有效但权限不足返回 403；
- PDP、Binding Store 或安全资源过滤不可用返回 503；
- Server 不会因为 PDP 故障而回退到全局 token、空 Principal 或 allow-all；
- `/health/live` 仍反映进程存活，`/health/ready` 报告 required authorization dependency 未就绪。

403 不区分“资源不存在”和“资源存在但不可见”。只有通过授权后，Repository 才可以返回 404，避免资源枚举。

# Reference-level explanation

## Goals and non-goals

本 RFC 的目标是：

- 在 HTTP、MCP 和 Dashboard 前建立同一个 Server PEP；
- 从认证凭据建立不可由请求覆盖的 Principal；
- 支持 scope 级 RBAC 和精确 Handoff receiver Binding；
- 允许安全解引用精确 Handoff 已引用的 evidence，而不开放整个 scope；
- 提供可替换的判定接口和可选的关系写入接口；
- 提供自助检查、资源发现、Binding 管理和审计 API；
- 对直接读取、列表、分页、内部 MCP bridge 和后台 operation fail closed；
- 保留当前 Runtime、Source、Memory、Handoff 和 Work application API 的领域纯度。

本 RFC 不定义：

- 用户注册、密码、MFA、OIDC Provider 或 token issuance；
- 自定义 role DSL、wildcard scope、组织层级或 group directory；
- 匿名 bearer share link 或把授权嵌入 Handoff 内容；
- Git、文件系统、工具、网络、模型 Provider 或凭据授权；
- 数据脱敏、cross-organization export、legal hold 或 retention policy；
- 审批工作流、临时提权流程或 Agent 自动请求更高权限；
- 把 PowerContext 改造成通用 IAM 产品。

## Trust model and invariants

实现必须维持以下不变量：

1. `scope_id` 是业务分区值，不是授权证明。
2. Principal 只来自认证 middleware 或可信 internal bridge context。
3. 请求 body 中的 `receiver`、`subject`、`actor`、role text 或 Handoff 自然语言不能替换当前 Principal。
4. Handoff 和 Memory 是 `untrusted_history`，不能授予 action。
5. `is_internal_bridge()` 只能跳过重复 transport authentication，不能跳过 authorization。
6. 每个受保护的 operation 在访问 Repository 或 application service 前完成判定。
7. 精确 Handoff grant 不允许 `latest`，不自动覆盖同 Artifact 的其他 Revision。
8. `accepted` Receipt 不创建、更新或继承 Access Binding。
9. 模型可以建议接收方或解释拒绝原因，但不能自行确定 canonical Principal 或调用 allow-all fallback。
10. Public error、log、metric 和 trace 不包含 credential、Handoff 正文、Memory、Source body 或 PDP 原始响应。

## Principal model

`PrincipalRef` 使用认证 Provider 给出的稳定 opaque identity：

```json
{
  "type": "user",
  "issuer": "https://id.example.com/",
  "id": "00u-bob"
}
```

字段语义如下：

| Field | Semantics |
| --- | --- |
| `type` | `user`、`service` 或后续注册的 Principal type |
| `issuer` | 建立该 identity 的可信 issuer；本地凭据使用 deployment-specific issuer |
| `id` | issuer 内稳定 opaque subject，不使用显示名或 email |

Agent 名称、host、session ID 和模型名称属于 provenance，不默认成为 Principal。若企业 token 明确证明 on-behalf-of actor，
认证 adapter 可以在可信 request context 中附加 `actor`；PDP 可以同时约束 subject 和 actor。客户端不能通过 JSON body
声明该 actor。

现有 Handoff Receipt 的 `receiver` 字段继续作为记录内容。Server 另外记录产生 Receipt 的 authenticated Principal，
两者不一致时拒绝 `accepted` 或在非 accepted Receipt 中明确标记 mismatch；绝不能把自由文本 `receiver` 当作 Principal。

## Resource model

内部授权 request 使用结构化 `ResourceRef`，避免把包含 `:`、`/` 或用户数据的标识直接拼成策略字符串：

| Resource type | Identity | Parent |
| --- | --- | --- |
| `server` | deployment identifier | none |
| `scope` | exact `scope_id` | server |
| `handoff` | exact Handoff `ArtifactReference` plus `scope_id` | scope |

Handoff resource 必须包含 `family`、`artifact_id` 和 `revision`。Prepared Handoff 没有持久化 identity，不能创建精确
Access Binding。跨用户最小权限分享必须先 commit；Prepared Handoff 仍可由已经共享同一 trust domain 的调用方显式
传输，但接收方需要独立的 scope 权限才能读取 evidence。

Adapter 负责把结构化 ResourceRef 映射成外部 PDP object ID。映射必须 canonical、可逆或稳定，并避免把 email、token、
Handoff 文本或其他 PII 写入 Casbin policy、OpenFGA tuple 或 audit key。

## Action vocabulary

首版 action 是稳定、小写、点分隔的字符串：

| Action | Resource | Meaning |
| --- | --- | --- |
| `server.observe` | server | 读取服务级运行状态和观测数据 |
| `server.admin` | server | 管理 deployment access configuration |
| `scope.read` | scope | 读取该 Workstream 的通用只读资源和投影 |
| `scope.contribute` | scope | 写入 Source、Memory contribution、Handoff 和 Outcome |
| `scope.review` | scope | 评审该 scope 的 Artifact Candidate |
| `scope.delegate` | scope | 为精确 Handoff 创建 viewer 或 receiver Binding |
| `scope.admin` | scope | 管理该 scope 的角色、Binding 和 policy |
| `handoff.read` | exact handoff | 读取一个精确 Handoff Revision |
| `handoff.evidence.read` | exact handoff | 通过 Handoff resolver 解引用该 Revision 的 citation manifest |
| `handoff.acknowledge` | exact handoff | 对该 Revision 创建 Handoff Receipt |

业务 operation 检查 action，不检查 role name。这样可以调整外部角色或关系模型，而不改 application code。

`scope.read` 可以通过策略蕴含 scope 下 Handoff 的 `handoff.read` 和 `handoff.evidence.read`；
`scope.contribute` 可以蕴含 acknowledge、prepare、commit 和 Outcome 写入。反向蕴含不成立：精确 `handoff.receiver`
不能得到 `scope.read` 或 `scope.contribute`。

## Built-in roles

| Role | Granted actions |
| --- | --- |
| `handoff.viewer` | `handoff.read`, `handoff.evidence.read` on one exact Handoff |
| `handoff.receiver` | viewer actions plus `handoff.acknowledge` on one exact Handoff |
| `scope.viewer` | `scope.read` |
| `scope.contributor` | `scope.read`, `scope.contribute` |
| `scope.reviewer` | `scope.read`, `scope.review` |
| `scope.delegator` | `scope.read`, `scope.delegate` |
| `scope.admin` | all scope actions, including delegation and Binding administration |
| `server.observer` | `server.observe` |
| `server.admin` | all server and scope actions |

首版不允许通过公共 API 创建新 role 或修改 role-to-action mapping。固定角色让 OpenAPI、Dashboard 和 adapter
conformance test 拥有稳定语义；企业 PDP 可以在外部把自定义组织角色映射为这些 action。

拥有 `scope.delegate` 的 Principal 只能创建 `handoff.viewer` 或 `handoff.receiver`，且只能针对该 scope 中已经存在的
精确 Handoff。创建 scope role 需要 `scope.admin`；创建 `server.admin` 需要现有 `server.admin` 和 deployment policy
允许。任何 Principal 都不能授予自己高于调用方管理边界的权限。

## Authorization request and decision

PowerContext 的判定模型与 OpenID AuthZEN Authorization API 的 subject、action、resource、context 形状对齐，但
Python protocol 不要求 PDP 使用 HTTP：

```python
class AuthorizationProvider(Protocol):
    async def check(self, request: AccessRequest, /) -> AccessDecision: ...

    async def check_batch(
        self,
        requests: Sequence[AccessRequest],
        /,
    ) -> Sequence[AccessDecision]: ...

    async def list_resources(
        self,
        request: ResourceSearchRequest,
        /,
    ) -> AuthorizedResourcePage: ...
```

规范化 request 示例：

```json
{
  "subject": {
    "type": "user",
    "issuer": "https://id.example.com/",
    "id": "00u-bob"
  },
  "action": {"name": "handoff.read"},
  "resource": {
    "type": "handoff",
    "scope_id": "project:payments",
    "reference": {
      "family": "handoff",
      "artifact_id": "project:payments",
      "revision": 12
    }
  },
  "context": {
    "request_id": "pc-01K...",
    "transport": "mcp"
  }
}
```

`AccessDecision` 至少包含：

```json
{
  "allowed": true,
  "reason_code": "role_binding",
  "policy_revision": "42"
}
```

`reason_code` 是稳定、低敏感度枚举，用于 audit 和诊断；business 403 response 不返回 provider rule、tuple、URL、堆栈或
原始 body。`policy_revision` 允许审计和缓存关联到确定策略，但它不是授权 token。

`check_batch` 必须保持输入顺序，并对每项返回独立决定。Adapter 不能因为一个 allow 而允许整批资源。

`list_resources` 是安全列表功能的必要能力。它先从授权系统得到允许的 resource identity，再把有界 identity set 交给
Repository 查询。只支持 point check、无法安全产生 resource filter 的 Provider 不得先查询全部 Handoff/Project/Scope
再逐项过滤；对应 list operation 应返回 503 或在配置阶段被判为不具备所需 capability。

## Relationship administration

AuthZEN 定义判定接口，不定义所有 PDP 的关系写入方式。因此管理能力与判定能力分开：

```python
class RelationshipWriter(Protocol):
    async def create_binding(
        self,
        request: CreateAccessBinding,
        /,
    ) -> AccessBinding: ...

    async def revoke_binding(
        self,
        binding_id: str,
        /,
        *,
        expected_version: int,
    ) -> AccessBinding: ...
```

内置 Provider、Casbin adapter 和 OpenFGA adapter 可以同时提供 `AuthorizationProvider` 与 `RelationshipWriter`。
OPA、Cerbos 或通用 AuthZEN adapter 可以只提供 decision；此时 PowerContext 的 Binding mutation endpoint 明确返回
`relationship_management_unavailable`，管理员通过外部系统配置关系。Server 不能声称 grant 成功后再只写本地影子记录。

## Access Binding model

内置 Binding Store 至少保存：

| Field | Requirement |
| --- | --- |
| `binding_id` | Server-generated opaque ID |
| `subject` | canonical `PrincipalRef` |
| `resource` | canonical exact `ResourceRef` |
| `role` | one fixed role name |
| `granted_by` | authenticated Principal recorded by Server |
| `reason` | optional bounded human explanation |
| `created_at` | trusted Server time |
| `expires_at` | optional trusted expiration |
| `state` | `active` or `revoked` |
| `version` | monotonically increasing CAS version |
| `policy_revision` | policy version after mutation when available |
| `idempotency_key` | bounded caller key scoped to grantor and resource |

Role、subject 或 resource 变化必须 revoke old + create new。相同 grantor、idempotency key 和相同 payload 的重试返回
原 Binding；同 key 不同 payload 返回 409。过期不删除记录，判定时视为 deny。

内置 Binding Repository 属于 Server access-control component，不加入 Runtime 的 `context`、`source`、`memory`、
`handoff` 或 `work` application object。它可以与 Server 使用相同数据库部署，但拥有独立 schema、migration 和 API。

## Public Access API

OpenAPI source of truth 增加以下 operation：

| Operation | Purpose | Authorization |
| --- | --- | --- |
| `GET /v1/access/me` | 返回当前 Principal 和 access-control capability | authenticated Principal |
| `POST /v1/access/check` | 检查当前 Principal 的一个 action/resource | current Principal only |
| `POST /v1/access/check-batch` | 批量检查当前 Principal | current Principal only |
| `POST /v1/access/resources/list` | 列出当前 Principal 可访问的资源 identity | current Principal only |
| `POST /v1/access/roles/list` | 返回固定角色及 action vocabulary | authenticated Principal |
| `POST /v1/access/bindings/list` | 列出调用方可管理的 Binding | `scope.delegate`, `scope.admin`, or `server.admin` |
| `POST /v1/access/bindings/create` | 创建精确 Handoff 或管理级 Binding | resource-specific administration action |
| `POST /v1/access/bindings/revoke` | CAS revoke 一个 Binding | same administration boundary |
| `POST /v1/access/audit/list` | 查询安全审计事件 | `scope.admin` or `server.admin` |

`check`、`check-batch` 和 `resources/list` 不接受 client-specified subject，只检查当前 authenticated Principal，防止普通
用户把 API 当作人员权限枚举器。管理员代查其他 Principal、subject search 和 directory integration 留给后续 RFC。

`bindings/create` 必须接收目标 subject，因为分享需要指定 B；调用方仍然只能在自己拥有管理权限的 resource 上创建固定
角色。Server 在写入前重新读取精确 Handoff identity，确认它存在并属于目标 scope。

公共 `check` 可以用 HTTP 200 返回 `allowed=false`。业务 operation 的相同拒绝返回 403，并且不调用 application
service。Access API 只用于解释和 UI preflight，不能替代业务请求时的实时 enforcement。

## Handoff operation requirements

首版 Handoff 映射如下：

| Operation | Required authorization |
| --- | --- |
| `prepare_handoff`, `finalize_handoff`, `handoff_current_work` | `scope.contribute` on request `scope_id` |
| `commit_handoff` | `scope.contribute` on request `scope_id` |
| `continue_handoff(selection=latest)` | `scope.read` on request `scope_id` |
| `continue_handoff(selection=exact)` | `scope.read` or `handoff.read` on exact Revision |
| `continue_handoff(selection=prepared)` | `scope.read` on request `scope_id` |
| `acknowledge_handoff` with exact receipt | `scope.contribute` or `handoff.acknowledge` on exact Revision |
| `record_task_outcome` | `scope.contribute` on request `scope_id` |
| aggregated Handoff Report queries | scope-level read; exact Handoff grant is insufficient |
| Handoff Report administration | `scope.admin` or appropriate server administration action |

当 exact receiver 调用 Continue 时，请求必须提供 `selection=exact` 和 exact `ArtifactReference`。Server 先建立 Handoff
ResourceRef 并判定，再读取 Revision。它不能先解析 latest 再检查，也不能在 exact 缺失时回退到 latest。

Prepared Handoff 可以包含由调用方提交的完整内容，因此窄授权模式不接受 `selection=prepared`。只有已经拥有
`scope.read` 的 Principal 才能用 prepared selection 解引用 scope evidence。

## OpenAPI access metadata

每个受保护 operation 在 `openapi/powercontext.yaml` 中声明 `x-powercontext-access`。生成器把该 extension 生成到
`Operation.access`，Server `_add_route()` 使用它组装 PEP wrapper。示例：

```yaml
/v1/handoff/commit:
  post:
    operationId: commit_handoff
    x-powercontext-access:
      action: scope.contribute
      resource:
        type: scope
        scope-id-from: body.scope_id
```

具有 selection-dependent policy 的 operation 使用已注册 resolver name，而不是在 YAML 中嵌入可执行表达式：

```yaml
x-powercontext-access:
  resolver: continue_handoff_access
```

Resolver 是 Server-owned、经过单元测试的确定性函数。它只能从已验证 request model 和 route metadata 建立
AccessRequest，不能读取业务 Repository 后才决定是否授权。

Health endpoint、静态 page shell 和认证 callback 可以显式声明 public。没有 access metadata 的新增业务 operation
使 contract generation 或 contract test 失败，不能默认 public。

## Server PEP

请求顺序固定为：

```text
transport authentication
  -> bind Principal and trusted request context
  -> validate request schema
  -> resolve action and resource
  -> AuthorizationProvider decision
  -> application service
  -> response
```

Schema validation 可以在判定前完成，以安全获得 resource identity；验证错误不得包含资源内容。任何 Repository lookup、
Handoff resolution、Memory search、Report aggregate 或 mutation 都在 allow 之后发生。

PEP 位于 Server adapter，不向 `application.context.for_scope(...)`、Source、Memory、Handoff、Work 或 Review domain method
添加 `principal`、role 或 permission 参数。Local in-process Runtime 调用不自动获得 Server authentication；需要安全边界
的本地集成应调用同一 Access Control service 或通过 Server。

## HTTP, MCP, and Dashboard parity

HTTP 是完整远程 contract，MCP 和 Dashboard 复用同一 operation 和 PEP：

- HTTP authentication 建立 Principal 后，授权 wrapper 对每个 operation 执行；
- MCP internal ASGI bridge 把原 Principal、actor 和 request ID 放入 request-local context；
- `is_internal_bridge()` 可以避免再次解析同一个外部 credential，但授权 wrapper仍执行；
- MCP tool discovery 可以根据当前 Principal 过滤不可用工具，但隐藏工具只是 UX，调用时仍必须判定；
- Dashboard 根据 `access/me` 和 batch check 禁用或隐藏操作，同时不能绕过 API enforcement；
- background job 必须携带创建 job 时绑定的 service Principal 或显式 system Principal，不使用空 identity。

HTTP 和 MCP 对同一 Principal、action、resource、policy revision 必须得到相同 allow/deny。Adapter conformance test 覆盖
这一保证。

## Listing and pagination

列表最容易泄漏 Project 名称、scope ID、Handoff objective 或 Candidate metadata。安全顺序为：

```text
AuthorizationProvider.list_resources
  -> bounded authorized identity filter
  -> Repository query restricted by that filter
  -> stable pagination
  -> response
```

禁止以下实现：

```text
Repository.list_all -> page -> check each item -> remove denied rows
```

这种实现会泄漏总数、cursor、空洞和时序，也可能让授权用户永远看不到后面的记录。`total`、cursor 和 page boundary
必须只描述授权后的集合。

精确 Handoff receiver 通过 `/v1/access/resources/list` 发现授权 Revision；它不会因此出现在聚合 Project 或 Workstream
列表。只有 scope-level read 才允许进入 Handoff Report 聚合查询。

## Audit and diagnostics

Access Audit 是 append-only Server security record，至少包含：

- request ID、time、transport 和 operation ID；
- Principal opaque identifier 和可信 actor identifier（若存在）；
- action、resource type 和 opaque resource identity；
- allow/deny、稳定 reason code 和 policy revision；
- Binding create/revoke 的 binding ID、grantor、target、role 和 expected/result version。

Audit 不包含：

- Bearer token、cookie、client secret 或 PDP credential；
- Handoff objective/state/next action；
- Source、Memory、PreparedContext 或 citation body；
- 任意 exception fields、configured PDP URL 或 provider 原始 response；
- email、display name 或不必要的目录属性。

普通 log、metric 和 trace 使用同样的数据最小化边界。Public readiness 只返回稳定 component state 和安全 reason，详细
provider diagnostics 留在受保护的 operator channel。

## Consistency and failure recovery

Commit Handoff 与创建外部授权关系不是跨系统原子事务。UI 中的“发送给 B”按以下可恢复步骤执行：

1. commit 或复用同一精确 Handoff Revision；
2. 使用稳定 idempotency key 创建 Binding；
3. 只有两步都成功才显示“已分享”；
4. 第二步失败时显示“交接已保存，但 B 尚不可见”，并只重试 Binding create；
5. 不重新 prepare、commit 或创建另一个 Revision。

Binding 已成功而客户端丢失响应时，同一 idempotency key 返回原 Binding。外部 RelationshipWriter 无法提供等价幂等
保证时，adapter 必须先执行安全的 exact relationship lookup，或声明不支持 self-service mutation。

Receipt 创建仍使用现有 exact-selection 和 evidence rules。授权判定发生在 Receipt transaction 前；授权在判定后立即
被并发撤销时，Provider 和 Binding Store 应在同一 deployment 中使用 policy revision 或 transaction fence 防止明显
越权。跨网络 PDP 的剩余 TOCTOU 窗口必须有界并记录 decision revision；首版不缓存 allow decision。

## Provider profiles

### Built-in provider

内置 profile 使用固定角色和 Server-owned Binding Store，支持 point check、batch check、authorized resource listing、
create、revoke 和 audit。它是本地部署和 conformance test 的参考语义，不提供用户密码、目录或自定义 policy language。

### Casbin adapter

Casbin adapter 可以使用带 domain 的 RBAC：

- subject 映射为 issuer-scoped opaque ID；
- domain 映射为 canonical scope resource namespace；
- object 映射为 scope 或 exact Handoff resource key；
- action 使用本 RFC 的 action vocabulary；
- role assignment 和 policy mutation 通过 Casbin management API 与持久化 adapter 完成。

Casbin domain 是 adapter policy namespace，不把 `scope_id` 变成认证或 tenant 证明。Adapter 仍从 Server 传入的可信
ResourceRef 建立 domain。

### OpenFGA adapter

OpenFGA 适合表达用户、group、scope 和 exact Handoff 的关系。概念模型如下：

```text
type user

type scope
  relations
    define viewer: [user]
    define contributor: [user]
    define reviewer: [user]
    define delegator: [user]
    define admin: [user]
    define can_read: viewer or contributor or reviewer or delegator or admin
    define can_contribute: contributor or admin
    define can_review: reviewer or admin
    define can_delegate: delegator or admin

type handoff
  relations
    define parent: [scope]
    define viewer: [user]
    define receiver: [user]
    define can_read: viewer or receiver or can_read from parent
    define can_acknowledge: receiver or can_contribute from parent
```

Adapter 使用固定 authorization model ID 执行 Check、ListObjects 和 tuple write。Tuple 只保存 opaque ID，不保存 email
或 Handoff 文本。Model migration 在 deployment configuration 中显式切换，不自动使用“latest model”。

### AuthZEN, OPA, and Cerbos adapters

AuthZEN adapter 把 `AccessRequest` 映射为 Authorization API 的 subject、action、resource、context，把 decision 映射回
`AccessDecision`。OPA adapter 可以把相同结构作为 input document；Cerbos adapter 可以映射为 principal、resource
和 actions。

这些 adapter 的 decision interoperability 不代表 policy administration interoperability。若组织在 GitOps、IAM 或
独立管理面维护 policy，PowerContext 只消费判定和安全 resource search，不写 policy。部署必须明确
`relationship_management=false`，Dashboard 不显示成功的 self-service share control。

## Configuration and compatibility

Server 提供三种显式 mode：

| Mode | Behavior |
| --- | --- |
| `disabled` | 保持单用户、单 trust-domain 的现有行为；Access API 不可用，不宣称多用户隔离 |
| `legacy-static-admin` | 现有静态 Bearer 映射为 deployment-local `server.admin` Principal |
| `enforced` | 认证 Provider 和 AuthorizationProvider 都是 required dependency，所有业务 operation 执行 PEP |

升级不能因为配置了外部身份但漏配 PDP 而回退到 `disabled`。Mode 必须显式，capabilities 和 readiness 报告当前 mode 与
是否支持 relationship management、batch check 和 safe resource listing。

`disabled` 只适用于调用方已经信任整个进程和 catalog 的本地场景。文档不能把它描述为多用户安全配置。远程、多用户或
共享 Dashboard 部署应使用 `enforced`。

现有 OpenAPI operation 首次增加 authorization metadata 不改变 request/response domain schema，但会增加 403 response
并改变未授权行为。Generated Client 把 401、403 和 503 映射为稳定、不同的 exception；不能把 403 当作空结果。

## Implementation slices

实现按以下可独立验证的 slice 推进：

1. **Contract and Principal**：OpenAPI Access model、operation metadata、generated `Operation.access`、可信 request
   Principal 和 stable errors。
2. **Built-in PEP/PDP**：固定角色、Binding Store、`_add_route()` authorization wrapper、point/batch check、audit。
3. **Handoff exact receiver**：commit 后创建 Binding、exact Continue、citation-manifest resolver、exact acknowledge、
   revoke 和 expiration。
4. **Safe listing and UI**：authorized resource listing、Handoff inbox、Dashboard permission projection、授权后分页。
5. **MCP parity**：Principal 通过 internal bridge 传播、tool discovery UX 和调用时 enforcement。
6. **External adapters**：先完成 Casbin 或 OpenFGA 之一，再用同一 conformance suite 验证 AuthZEN-compatible PDP。
7. **Migration**：legacy static admin、configuration validation、readiness、operator documentation。

每个 slice 都保持 Server 可运行，不能先发布只隐藏 Dashboard 按钮或只保护 HTTP、不保护 MCP 的中间状态。

## Test and acceptance plan

RFC 实现完成需要通过以下 observable scenarios：

- 无身份访问受保护 operation 返回 401；
- A 有 `scope.delegate` 时可以把已存在的 exact Revision 授予 B，缺少该 action 时返回 403 且不写 Binding；
- B 可以读取、Continue 和 acknowledge 被授予的 exact Revision；
- B 请求 latest、相邻 Revision、聚合 Handoff Report、Memory list、Source list 和 Task Outcome write 均被拒绝；
- B 只能通过被授权 Handoff 的 resolver 读取 manifest citation，不能用任意 citation 调用通用读取接口；
- `handoff.viewer` 不能 acknowledge，`handoff.receiver` 可以；
- `accepted` Receipt 不产生新的 Binding 或 scope role；
- revoke 或 expiration 后，B 的后续 access 被拒绝，authorized resource list 不再包含该 Revision；
- Binding create/revoke 的 CAS、idempotency 和 audit 行为稳定；
- 403 不泄漏资源是否存在，list cursor 和 total 只描述授权集合；
- PDP unavailable 返回 503，且 application service、Repository 和 mutation 未被调用；
- MCP internal bridge 使用原 Principal 并执行与 HTTP 相同的 deny；
- Dashboard 隐藏控制失效或被绕过时，API 仍拒绝请求；
- legacy static token 只在显式 mode 中映射为 local admin；
- Built-in、Casbin/OpenFGA 和 AuthZEN adapter 对同一 conformance vector 返回相同结果；
- Access Audit 不包含 token、Handoff 正文、Memory、Source body 或 PDP 原始错误。

Cross-component acceptance scenarios 放在 `tests/e2e/`，并通过公开 HTTP/MCP contract 断言行为。Focused tests 覆盖
resource resolver、role mapping、Binding CAS、provider failure 和 citation membership，不冻结 private call order。

# Drawbacks

每个业务请求增加一次授权判定，外部 PDP 还会增加网络依赖和延迟。安全列表要求 Provider 支持 resource search 或可下推
filter，只有 point-check 的简单 adapter 无法支持全部 Dashboard 列表。

精确 Handoff 分享必须先 commit，因此不能把临时 Prepared Handoff 直接变成可撤销的跨用户资源。这增加一步持久化，
但避免为临时 payload 发明第二套 identity 和 ACL。

判定和关系管理分离使 adapter interface 比单一 `check()` 更复杂；另一方面，假设所有外部 PDP 都允许 PowerContext 写
policy 会制造错误的可移植性承诺。

撤销只能阻止未来访问，无法删除接收方已经阅读、截图或导出的信息。包含高度敏感内容的 Handoff 仍需要最小化内容、
外部数据分类和导出控制。

固定首版角色限制了组织自定义体验。企业可以在外部 PDP 映射自己的角色，但 PowerContext 公共 API 不立即提供自定义
role editor。

# Rationale and alternatives

## Chosen: independent Server PEP plus replaceable PDP

该设计保持 Handoff 和 Runtime model 与身份系统解耦，同时让 HTTP、MCP 和 Dashboard 共用 enforcement。稳定 action
vocabulary 比稳定外部 role name 更容易跨 Casbin、OpenFGA、OPA、Cerbos 和企业 IAM 映射。

AuthZEN-compatible request shape 使网络 PDP 有标准接入点；独立 RelationshipWriter 则诚实表达 grant mutation 并未被
AuthZEN 统一。

## Alternative: put ACL fields on Handoff or scope

在 Handoff 增加 `allowed_users`，或把 owner/tenant 编入 `scope_id`，实现看似直接，但会把身份生命周期、group expansion、
撤销、外部 policy revision 和审计塞进领域数据。不可变 Handoff 也不适合随成员变更而创建新 Revision。该方案被拒绝。

## Alternative: only use scope-level roles

只授予 `scope.viewer` 容易实现，但 B 会看到整个 Workstream 的 Memory、Source、历史和 Report。对于临时接力不符合最小
权限原则。Scope roles 保留给长期协作，精确 Handoff Binding 负责一次性交接。

## Alternative: send an anonymous capability URL

Bearer share link 把“知道 URL”变成身份。链接可能进入聊天、日志、浏览器历史或模型上下文，难以确认实际接收者，也难以
执行企业 group policy 和个人审计。首版要求 B 使用自己的认证凭据，不提供匿名 capability URL。

## Alternative: copy a redacted Handoff document

复制 Markdown 可以减少 Server 权限工作，但会失去 exact Revision、evidence availability、Receipt、并发和撤销语义。
导出仍可作为显式的外部发布功能，不能替代 PowerContext 内部交接。

## Alternative: hide unauthorized Dashboard controls

UI 隐藏只能改善体验，HTTP 或 MCP 调用仍可绕过。所有 enforcement 必须发生在 Server PEP，Dashboard 仅消费相同判定。

## Alternative: require one policy engine

Casbin 适合 embedded RBAC，OpenFGA 适合关系和 group，OPA/Cerbos 适合已有 policy platform。强制一个实现会增加部署成本或
限制企业集成。PowerContext 定义语义和 conformance contract，不选择唯一 engine。

## Alternative: store roles in access token

Token role 简单但对 exact Handoff grant、撤销、large resource set 和 policy update 不友好。Token 可以携带可信 identity
和 group claims，最终 resource decision 仍由 PDP 完成。

## Alternative: authorize inside every Runtime method

把 Principal 参数传入 Context、Source、Memory、Handoff 和 Work 会扩散 transport policy，容易让 HTTP 与 MCP 产生不同
实现，也破坏本地 domain API。Server PEP 是当前远程 trust boundary 的单一 enforcement point。

# Prior art

PowerContext [RFC 0011](0011_remote_access_architecture.md) 已定义 HTTP 完整 contract、generated Client 和 MCP 投影共享
Server application semantics。本 RFC在同一 Server boundary 增加 authentication 和 authorization，不创建平行 MCP
policy service。

[RFC 0048](0048_handoff_artifact.md) 定义 Prepared Handoff、不可变 Handoff Revision、Continue 和 exact evidence；
[RFC 1223](1223_human_agent_work_continuity.md) 定义 Receipt 和 Task Outcome，并明确交接不能授予工具、网络或凭据权限；
[RFC 0082](0082_handoff_report.md) 提供 scope 和 Project 级聚合视图。本 RFC 为这些读取和写入补充 Principal-aware
visibility。

[OpenID AuthZEN Authorization API 1.0](https://openid.net/specs/authorization-api-1_0.html) 定义 PEP 与 PDP 之间的
subject、action、resource、context 和 decision contract。本 RFC 对齐其信息模型，但保留 embedded Provider。

[Casbin RBAC with Domains](https://casbin.apache.org/docs/rbac-with-domains/) 展示 domain-scoped role assignment；
[OpenFGA concepts](https://openfga.dev/docs/concepts) 使用 user、relation、object tuple 表达 object-level authorization；
[OPA](https://www.openpolicyagent.org/docs/integration) 提供通用 policy decision integration；
[Cerbos CheckResources](https://docs.cerbos.dev/cerbos/latest/api/index.html) 提供 principal、resource 和 action 的批量判定。
这些系统是 adapter 目标，不改变 PowerContext 的 Handoff lifecycle。

# Unresolved questions

以下问题需要在 RFC 合并前确认，但不改变核心安全边界：

- 首个外部 conformance adapter 选择 Casbin 还是 OpenFGA；
- 内置 Provider 是否随默认 Server extra 安装，还是作为独立 optional extra；
- Dashboard 如何从部署方的身份目录选择 canonical recipient；目录搜索本身不由本 RFC 的 Access API 提供；
- enforced deployment 是否要求 Provider 同时支持安全 resource listing，还是允许禁用相关 Dashboard 列表；
- `handoff.receiver` 的产品默认过期时间是否由 deployment policy 决定，还是 UI 必须每次显式选择；
- exact receiver 创建 Receipt 后，UI 是否建议管理员另行授予 `scope.contributor`，但不能自动执行该升级。

以下问题明确推迟：custom role、organization hierarchy、cross-tenant export、anonymous share link、temporary elevation、approval
workflow 和通用 Source/Memory object-level ACL。它们需要独立威胁模型和 RFC。

# Future possibilities

后续可以在不改变 subject/action/resource contract 的前提下增加：

- group、team 和 organization relation；
- Project 到 Workstream 的继承策略和显式 deny；
- 管理员代查、subject/resource search 和 access review campaign；
- 带审批的临时 scope elevation；
- AuthZEN Search API、obligation 和 richer decision metadata；
- policy bundle、signed decision metadata 和跨服务 audit correlation；
- 对 Handoff 导出的独立脱敏、watermark 和 data-loss-prevention policy；
- 更多 Artifact Family 的 exact-resource grant；
- 在有明确 revocation-staleness guarantee 后增加 bounded decision cache。

这些扩展不能改变首版不变量：`scope_id` 不是 ACL，Handoff 内容不授予权限，Receipt 不升级权限，所有 transport 在
Server PEP fail closed。
