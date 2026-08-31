---
title: PowerContext HTTP API 完整教程
description: 不依赖 Agent Host，从零跑通 Source、Memory、PreparedContext、Work、Handoff、Experience、Skill、Review、Report 和 Stats。
---

# PowerContext HTTP API 完整教程

本教程面向已经有自己的 AI 应用、聊天机器人、工作流或模型调用代码，但不使用 Codex、Claude Code、OpenCode
等 Agent Host 的开发者。你会把 PowerContext 当作独立的上下文服务，通过 HTTP API 跑通一套完整闭环：

```text
检查 Server 与能力
  → 采集 Source 证据
  → 保存、检索和维护 Memory
  → 为每次模型请求准备 PreparedContext
  → 记录 Work、Handoff 和 Task Outcome
  → 从证据生成或提交 Experience Candidate
  → 人工 Review 后形成 approved Experience
  → 从 Experience、Source 或 usage 孵化 managed Skill
  → 人工 Review 后精确读取和使用 Skill Revision
  → 通过 External Skill、Report 和 Stats 运营完整系统
```

教程中的连续示例是一个自建 AI 工程助手。所有主要步骤都使用 `curl` 和 JSON，不要求安装 Agent Host。最后还会
给出可复用的 Python 调用骨架。

## 1. 先理解产品边界

PowerContext 不会把一切内容自动“升级”为 Skill。不同对象有不同职责和授权边界：

| 对象 | 保存什么 | 如何产生 | 何时可用 |
| --- | --- | --- | --- |
| Source | 用户输入、任务结果、文档片段等原始证据 | 采集后立即持久化 | 作为精确 evidence，不直接进入召回 |
| Memory | 以后仍值得记住的事实、决定、偏好和约束 | 显式写入，或配置模型后从 Source 抽取 | active entry 可参与检索和 `PreparedContext` |
| PreparedContext | 当前请求需要的有界、带 citation 历史上下文 | Runtime 请求时临时准备 | 只用于一次模型请求，不持久化 |
| Work/Handoff | 目标、已验证状态、遗漏和下一步 | 应用显式记录、准备、确认和提交 | 用于会话、模型、应用或执行者之间继续工作 |
| Experience | 某个场景下做了什么、结果如何、学到了什么 | 完整 proposal 或模型生成 Candidate，再经 Review | approved current Revision 可参与 `PreparedContext` |
| managed Skill | 下次怎么做以及如何验证 | 根据 Experience、Source 或 usage 生成/提交 Candidate，再经 Review | 只能精确读取或显式发布；不会自动进入 `PreparedContext` |
| external Skill | 当前 Host 上已有的 Agent-native Skill package | 扫描显式配置的本地 target | 只有 fingerprint 和本地绑定都匹配时可解析 |

三个规则贯穿全部 API：

1. `scope_id` 是业务分区，不是访问控制。Gateway 必须验证调用者能否访问该 scope。
2. Candidate 是不可信 proposal。模型不能批准自己的 Candidate，也不能提交最终 Artifact Revision。
3. approved Skill 只是受治理内容，不会获得文件、网络、密钥、工具执行或发布权限。

## 2. 公共 API 全景

当前 OpenAPI 提供 53 个公共 operation：

| 领域 | 路径前缀 | 本教程覆盖 |
| --- | --- | --- |
| 健康与能力 | `/health/*`、`/v1/capabilities` | live、ready、capabilities |
| Source 与 Context | `/v1/sources/*`、`/v1/context/*` | capture、prepare |
| Work | `/v1/work/*` | contract、current Handoff、acknowledgement、outcome |
| 底层 Handoff | `/v1/handoff/*` | activate、prepare、finalize、commit、continue |
| Memory | `/v1/memory/*` | flush、remember、search、list、get、revise、retire、changes |
| Experience | `/v1/experience/*` | propose、generate、get |
| managed Skill | `/v1/skill/*` | propose、generate、get |
| Candidate Review | `/v1/artifact-candidates/*` | list、get、revise、approve、reject |
| External Skill | `/v1/external-skills/*` | scan、list、resolve、import/fork |
| Stats | `/v1/stats` | scoped inventory、model usage、recall estimates |
| Handoff Report | `/v1/handoff-reports/*` | Project、Workstream、Report、Activity、Workspace binding |

本教程解释调用顺序和实际工作流。全部字段限制、enum 和 response schema 仍以
[`openapi/powercontext.yaml`](https://github.com/oceanbase/powercontext/blob/master/openapi/powercontext.yaml) 为准。

## 3. 准备环境

需要 macOS 或 Linux、Python 3.11+、`uv`、`curl` 和 `jq`：

```bash
python3 --version
uv --version
curl --version
jq --version
```

安装 CLI 和 Server：

```bash
uv tool install --force "powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@master"
```

确认安装：

```bash
powercontext --version
powercontext server --help
```

显式 Memory、Source、Work、Handoff、类型化 proposal、Review 和精确读取不要求 generation model。只有
`/experience/generate`、`/skill/generate`、external Skill import/fork、Source-to-Memory 抽取和向量能力需要相应
provider。

## 4. 启动 Server

在**终端 A**持续运行：

```bash
powercontext server run
```

默认地址是 `http://127.0.0.1:8000`，数据保存在 PowerContext 用户数据目录的 SQLite 数据库中。

在**终端 B**设置贯穿教程的变量：

```bash
export POWERCONTEXT_URL=http://127.0.0.1:8000
export POWERCONTEXT_SCOPE=tenant:demo:project:api-tutorial
```

不要使用每次都会改变的会话 ID 作为 `scope_id`。同一项目的 Source、Memory、Experience、Skill 和 Handoff 必须
复用同一个稳定 scope。

## 5. 健康检查、能力与契约

```bash
curl --fail --silent --show-error "$POWERCONTEXT_URL/health/live" | jq .
curl --fail --silent --show-error "$POWERCONTEXT_URL/health/ready" | jq .
curl --fail --silent --show-error "$POWERCONTEXT_URL/v1/capabilities" | jq .
```

成功标准：

- liveness 返回 `200`；
- readiness 返回 `200`，状态为 `ready` 或允许继续使用基础能力的 `degraded`；
- capabilities 列出 `artifact_families`、搜索模式和各类 generation 开关。

当前进程提供的契约位于：

- `/docs`：Swagger UI；
- `/redoc`：ReDoc；
- `/openapi.json`：实际运行进程的 OpenAPI JSON。

## 6. 鉴权与公共请求规则

默认 loopback 开发环境可以不启用 Bearer 鉴权。本教程的主要命令因此省略 `Authorization` header。启用鉴权后，在
除 health 之外的每个请求中增加：

```http
Authorization: Bearer <token>
```

例如：

```bash
export POWERCONTEXT_CLIENT_API_TOKEN='从安全凭据源读取的 token'

curl --fail --silent --show-error \
  --header "Authorization: Bearer $POWERCONTEXT_CLIENT_API_TOKEN" \
  "$POWERCONTEXT_URL/v1/capabilities" \
  | jq .
```

不要把 token 放进 URL、Memory、Source、模型 prompt 或日志。允许远程访问前，在可信 Gateway 或 Service Mesh
终止 TLS，并在那里执行身份验证、scope 授权、限流和审计。

每个响应都有 `X-PowerContext-Request-ID`。需要同时查看 header 和 body 时：

```bash
curl --silent --show-error \
  --dump-header /tmp/powercontext-headers.txt \
  "$POWERCONTEXT_URL/v1/capabilities" \
  | jq .

grep -i '^X-PowerContext-Request-ID:' /tmp/powercontext-headers.txt
```

## 7. 认识四类精确引用

后续请求不会使用模糊名称串联，而是复用 Server 返回的精确引用：

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

- `SourceReference` 指向已采集的原始证据；
- `ArtifactReference` 指向 Experience、Skill、Handoff 或 Memory 的不可变 Revision；
- `MemoryCitation` 进一步指向 Memory Revision 中的不可变 entry version；
- Candidate 写操作使用 `candidate_id + expected_version` 防止审核旧内容。

教程会把响应保存到 `/tmp/powercontext-*.json`，再用 `jq` 构造下一步请求，避免手工抄错 ID。

## 8. 采集第一份 Source

保存一份已经完成的任务结果，作为后续 Work、Experience 和 Skill 的共同证据：

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

成功时返回 `202 Accepted`、`status: "accepted"`、精确 `source` 和 journal `position`。

同一个 `scope_id + source_id` 应稳定表示同一份内容：

- 再次提交相同内容是幂等操作；
- 使用相同 ID 提交不同内容返回 `409`；
- Source 不会同步变成 Memory、Experience 或 Skill；
- 不要默认采集整段聊天，应先完成用户同意、敏感字段过滤和保留期限控制。

## 9. 显式保存 Memory

从任务结果中选择一条以后仍应遵守的决定：

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n \
    --arg scope "$POWERCONTEXT_SCOPE" \
    '{
      scope_id: $scope,
      kind: "decision",
      text: "回答账单问题时，先解释费用构成；只有符合退款政策时才提供退款入口。",
      reason: "用户确认的客服策略"
    }')" \
  "$POWERCONTEXT_URL/v1/memory/remember" \
  | tee /tmp/powercontext-memory.json \
  | jq .
```

响应包含新的 `memory` ArtifactReference 和 `entry.citation`。`remember` 不会创建 Source，也不会调用模型。

### 搜索 active Memory

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n \
    --arg scope "$POWERCONTEXT_SCOPE" \
    '{scope_id: $scope, query: "账单退款应该怎么回复？", limit: 5, mode: "auto"}')" \
  "$POWERCONTEXT_URL/v1/memory/search" \
  | jq .
```

没有匹配时正常返回 `"hits": []`。`mode` 支持 `auto`、`fts`、`vector` 和 `hybrid`，但实际可用模式以
capabilities 为准。

### 列出当前 Memory head

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n --arg scope "$POWERCONTEXT_SCOPE" '{scope_id: $scope}')" \
  "$POWERCONTEXT_URL/v1/memory/entries/list" \
  | jq .
```

审计 inactive 条目时增加 `include_inactive: true`。

### 精确读取不可变 entry version

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

### 修订 Memory

修订会创建新的 entry version，不会覆盖历史：

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  '{
    scope_id: $scope,
    citation: .entry.citation,
    kind: "decision",
    text: "回答账单问题时，先逐项解释费用；只有订单符合当前退款政策时才提供退款入口。",
    reason: "客服策略进一步澄清"
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

后续操作必须使用新响应中的 citation。旧 citation 再次修订会返回 `409`。

### 查看 Revision 变化

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n --arg scope "$POWERCONTEXT_SCOPE" '{scope_id: $scope, since_revision: 0}')" \
  "$POWERCONTEXT_URL/v1/memory/changes" \
  | jq .
```

### 可选：停用过期 Memory

如果你正在连续执行本教程，暂时不要运行停用命令：第 11、12 步还会使用这条 Memory。完成这两步后再运行；
也可以现在运行，只用于验证 inactive entry 的审计行为。

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  '{scope_id: $scope, citation: .entry.citation, reason: "该流程已经停用"}' \
  /tmp/powercontext-memory-revised.json \
  > /tmp/powercontext-memory-retire.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-memory-retire.json \
  "$POWERCONTEXT_URL/v1/memory/entries/retire" \
  | jq .
```

停用不是物理删除。普通 search、list 和 prepare 不再使用该 entry，但精确 get 和
`include_inactive: true` 仍可审计。

## 10. 从 pending Source 抽取 Memory

如果配置了 generation model，`flush` 会处理一个有界 Source window：

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n --arg scope "$POWERCONTEXT_SCOPE" '{scope_id: $scope}')" \
  "$POWERCONTEXT_URL/v1/memory/flush" \
  | jq .
```

响应为 `status: "processed"` 或正常的 `status: "idle"`，并包含 cursor 和处理数量。没有 generation model 时，
显式 `remember` 仍然可用；不要为获得基础 Memory 功能而伪造模型配置。

## 11. 为模型请求准备 PreparedContext

每个用户请求调用一次：

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n \
    --arg scope "$POWERCONTEXT_SCOPE" \
    '{scope_id: $scope, query: "为什么账单这么高，可以退款吗？", max_bytes: 4000}')" \
  "$POWERCONTEXT_URL/v1/context/prepare" \
  | tee /tmp/powercontext-context.json \
  | jq .
```

有结果时：

```json
{
  "schema": "powercontext.prepared-context.v1",
  "status": "ready",
  "content": "BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1\n...\nEND_POWERCONTEXT_PREPARED_CONTEXT_V1",
  "content_bytes": 1024
}
```

没有结果时正常返回：

```json
{
  "schema": "powercontext.prepared-context.v1",
  "status": "empty",
  "content": null,
  "content_bytes": 0
}
```

`content` 是临时、只读、不可信历史数据。保持其中的 trust notice 和 citation，不要把它写回 Memory，也不要让它
覆盖当前 system/developer 指令、用户请求、实时业务数据或现场验证。

## 12. 接入自己的 AI 模型

下面的 Python 标准库代码封装 PowerContext；你只需把现有模型 SDK 接入 `call_your_model`：

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
        # 读取失败可以降级；生产实现还应记录 status、error.code 和 request ID。
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
        # 模型 API 有低权限 context/tool-result 通道时应优先使用。
        messages.append({"role": "user", "content": f"Historical reference data:\n{context}"})
    messages.append({"role": "user", "content": query})
    return call_your_model(messages)
```

读取 `PreparedContext` 可以 fail open；Memory、Candidate、Handoff 等写入不能静默失败。

### 模型 tool calling

只把应用包装函数暴露给模型，不把 token 和任意 `scope_id` 交给模型：

| 模型工具 | 后端 API | 授权策略 |
| --- | --- | --- |
| `search_project_memory(query)` | `/v1/memory/search` | 可自动读，限制 query 和 limit |
| `get_memory(citation)` | `/v1/memory/entries/get` | citation 必须来自当前 scope |
| `propose_memory(kind, text)` | 用户确认后 `/v1/memory/remember` | 模型建议，不自行保存 |
| `propose_experience(...)` | `/v1/experience/propose` | 只创建 pending Candidate |
| `propose_skill(...)` | `/v1/skill/propose` | 只创建 pending Candidate |

Reviewer API 不应暴露给提出 Candidate 的同一模型身份。

## 13. 记录 Work Contract

Work Contract 保存委托边界，但不会授予执行权限：

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  --slurpfile source /tmp/powercontext-source.json \
  '{
    scope_id: $scope,
    source_id: "work-contract:billing-api:1",
    contract: {
      schema: "powercontext.work-contract.v1",
      trust: "untrusted_input",
      objective: "验证账单解释和退款路径的 API 集成",
      facts: [{
        text: "已有一次成功的任务结果",
        basis: "verified",
        evidence: [{kind: "source", source_ref: $source[0].source}]
      }],
      in_scope: ["验证响应内容", "运行契约测试"],
      exclusions: ["修改生产退款政策"],
      completion_criteria: ["契约测试通过", "未泄露敏感信息"],
      authorization_notes: ["只允许读取测试环境"],
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

成功返回 `202` 和 `WorkSourceReceipt`。相同 `source_id` 仍遵循 Source 幂等语义。

## 14. 高层 Work/Handoff 闭环

### 准备当前工作 Handoff

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  --slurpfile source /tmp/powercontext-source.json \
  '{
    scope_id: $scope,
    source_id: "handoff-boundary:billing-api:1",
    handoff: {
      schema: "powercontext.current-work-handoff.v1",
      trust: "untrusted_input",
      objective: "继续验证账单 API",
      state: [{
        text: "账单解释流程已实现并通过契约测试",
        basis: "verified",
        evidence: [{kind: "source", source_ref: $source[0].source}]
      }],
      disposition: "continuable",
      next_action: {
        text: "在测试环境验证退款资格分支",
        basis: "declared",
        evidence: [{kind: "source", source_ref: $source[0].source}]
      },
      omissions: ["尚未验证生产流量"]
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

响应包含 durable `boundary` Source receipt 和临时 `handoff`。准备完成不等于已经形成 durable Handoff milestone。

### 提交 Handoff Revision

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

保存响应中的 `reference`。它是精确、不可变的 Handoff ArtifactReference。

### 精确继续并确认接收

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

接收方必须独立确认 live state、capability 和 authorization：

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
    message: "测试环境和权限已经独立核对。"
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

`accepted` 不是任务完成，只表示接收方确认可以继续。也可以使用 `needs_clarification` 或 `declined`。

### 记录 Task Outcome

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
      objective: "验证退款资格分支",
      status: "succeeded",
      summary: "测试环境的资格与拒绝分支均通过。",
      handoff_receipt_ref: $ack[0].receipt.source,
      observations: [{
        text: "退款资格分支返回预期结构",
        basis: "verified",
        evidence: [{kind: "source", source_ref: $source[0].source}]
      }],
      checks: [{
        name: "billing contract tests",
        status: "passed",
        details: "全部契约用例通过",
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

Task Outcome 是一次尝试的 Source 证据，不会自动批准 Experience 或 Skill。

## 15. 底层 Handoff API

需要自定义 UI 或细粒度状态机时，可以不用高层 `prepare-current`，而是使用：

| 操作 | 请求关键字段 | 结果 |
| --- | --- | --- |
| `/v1/handoff/activate` | boundary Source、objective、可选 evidence | 生成 Draft 或返回已消费的 ignored |
| `/v1/handoff/prepare` | objective、至少一条精确 evidence | 未提交 `HandoffDraft` |
| `/v1/handoff/finalize` | 已检查的完整 Draft | 临时 `PreparedHandoff` |
| `/v1/handoff/commit` | PreparedHandoff | immutable Handoff Revision |
| `/v1/handoff/continue` | `prepared`、`exact` 或 `latest` selection | untrusted HandoffResolution |

直接 prepare 的最小例子：

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  --slurpfile source /tmp/powercontext-source.json \
  '{
    scope_id: $scope,
    objective: "继续验证账单 API",
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

应用必须检查并必要时编辑完整 Draft，再调用 finalize；不要把模型生成的 Draft 直接视为已批准事实。

## 16. 创建 Experience Candidate

Experience 包含 `situation`、`action`、`outcome` 和 `lesson`。两条路径都会只创建 pending Candidate。

### 无模型：提交完整 proposal

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  --slurpfile outcome /tmp/powercontext-task-outcome.json \
  '{
    scope_id: $scope,
    proposal: {
      situation: "账单 API 需要同时解释费用并安全处理退款资格。",
      action: "先验证费用明细契约，再分别测试退款资格和拒绝分支。",
      outcome: "全部契约用例通过，回复不会在资格判断前承诺退款。",
      lesson: "将解释费用与退款资格拆成独立验证步骤，可以减少错误承诺。"
    },
    source_refs: [$outcome[0].source],
    artifact_refs: [],
    reason: "根据已验证 Task Outcome 提交可复用经验"
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

成功返回 `201`、`family: "experience"`、`status: "pending"` 和 `version: 1`。

### 有模型：根据精确 evidence 生成

配置 generation model 并重启 Server 后，确认 `experience_generation: true`：

```bash
export POWERCONTEXT_SERVER_INFERENCE_GENERATION_MODEL=provider:model-name
powercontext server run
```

然后调用：

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  --slurpfile outcome /tmp/powercontext-task-outcome.json \
  '{
    scope_id: $scope,
    source_refs: [$outcome[0].source],
    artifact_refs: [],
    reason: "从已完成任务中提取可复用经验"
  }' \
  > /tmp/powercontext-experience-generate-request.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-experience-generate-request.json \
  "$POWERCONTEXT_URL/v1/experience/generate" \
  | jq .
```

响应可能是 `status: "pending"` 和 Candidate，也可能是正常的 `status: "no_op"`。Generation 不会自动批准。

Memory 的 `memory` ArtifactReference 也属于 Artifact evidence，但它表示整个 Memory Revision；需要精确描述任务发生
了什么时，优先引用 Task Outcome 或其他 Source。

## 17. Review Candidate

### 列出 Review Inbox

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n --arg scope "$POWERCONTEXT_SCOPE" \
    '{scope_id: $scope, status: "pending", family: "experience", limit: 50}')" \
  "$POWERCONTEXT_URL/v1/artifact-candidates/list" \
  | jq .
```

### 精确读取当前 Candidate head

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

Reviewer 应核对 proposal、全部 Source/Artifact lineage、target 和 reason。

### 修订 Candidate

修订必须提交完整 replacement proposal 和 evidence，而不是局部 patch：

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  '{
    scope_id: $scope,
    candidate_id: .candidate_id,
    expected_version: .version,
    proposal: (.proposal + {lesson: "先验证费用明细，再验证退款资格，可以避免错误承诺并提高可解释性。"}),
    source_refs: .source_refs,
    artifact_refs: .artifact_refs,
    target: .target,
    reason: "Reviewer 补充了可解释性要求"
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

### 批准检查过的 version

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

批准会在同一个事务中写入 immutable Experience Revision，并返回 `result_artifact`。如果不应发布，调用
`/v1/artifact-candidates/reject`，传入 `candidate_id`、当前 `expected_version` 和非空 `reason`。

收到 `409` 时重新 get Candidate；不要用旧 version 重试批准。

## 18. 精确读取并召回 Experience

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

approved current Experience 可以参与同 scope 的 `PreparedContext`，但是否被选择仍取决于 query、相关性和 Memory/
Experience 共享的字节预算。pending、rejected 和历史 Experience Revision 不会自动进入召回。

再次调用 context prepare：

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n --arg scope "$POWERCONTEXT_SCOPE" \
    '{scope_id: $scope, query: "怎样安全实现账单解释和退款资格验证？", max_bytes: 8000}')" \
  "$POWERCONTEXT_URL/v1/context/prepare" \
  | jq .
```

## 19. 创建 managed Skill Candidate

Skill proposal 包含 `name`、`description`、`instructions` 和至少一条 `validation`。

### 无模型：提交完整 Skill

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  --slurpfile approved /tmp/powercontext-experience-approved.json \
  '{
    scope_id: $scope,
    proposal: {
      name: "validate-billing-response",
      description: "验证账单解释和退款资格回复是否安全、完整。",
      instructions: "1. 读取费用明细。\n2. 逐项解释费用。\n3. 独立检查退款资格。\n4. 只有资格成立时提供退款入口。\n5. 记录验证结果。",
      validation: [
        "回复必须解释费用明细。",
        "退款入口只能在资格验证通过后出现。",
        "不得在日志或模型上下文中泄露凭据。"
      ]
    },
    source_refs: [],
    artifact_refs: [$approved[0].result_artifact],
    reason: "把 approved Experience 转为可复用操作步骤"
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

### 有模型：按 origin 生成

`/v1/skill/generate` 有三种严格 provenance shape：

| origin | 必需 evidence | 禁止内容 |
| --- | --- | --- |
| `experience` | 一个或多个 approved Experience ArtifactReference | target、非 Experience artifact |
| `source` | 一个或多个 SourceReference | target、任何 artifact |
| `usage` | usage Source、精确 current Skill target，且 target 同时出现在 artifacts | 缺少 target 或 Source |

从 approved Experience 生成：

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  --slurpfile approved /tmp/powercontext-experience-approved.json \
  '{
    scope_id: $scope,
    origin: "experience",
    source_refs: [],
    artifact_refs: [$approved[0].result_artifact],
    reason: "将经过审核的经验转为可复用 Skill"
  }' \
  > /tmp/powercontext-skill-generate-request.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-skill-generate-request.json \
  "$POWERCONTEXT_URL/v1/skill/generate" \
  | jq .
```

Generation 仍只返回 pending Candidate 或 `no_op`。使用第 17 步相同的 Review API 审核 Skill Candidate。

## 20. 批准、读取和使用 Skill

批准本教程的手工 Skill Candidate：

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

精确读取：

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

自己的 AI 应用应通过配置或业务选择器选中一个 exact Skill Revision，再读取并提供给模型。不要让模型在未知
Skill head 上自行选择 latest，也不要把 approved 当作工具执行授权。应用仍需验证：

- 当前用户是否允许使用该 Skill；
- 需要哪些文件、网络、工具和密钥权限；
- instructions 是否适用于当前环境；
- validation 是否真正执行并通过。

managed Skill 不会自动进入 `PreparedContext`。导出到 Codex 等 Host 属于显式 host-local projection，参见
[创建并导出 managed Skill](../how-to/create-and-export-skill.md)。

## 21. 根据 usage 演进 Skill

先保存实际使用结果 Source：

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

再创建 replacement Candidate：

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
    reason: "根据实际使用结果增加负向用例验证"
  }' \
  > /tmp/powercontext-skill-usage-generate-request.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-skill-usage-generate-request.json \
  "$POWERCONTEXT_URL/v1/skill/generate" \
  | jq .
```

只有审核并批准 replacement Candidate，才会在相同 Skill identity 下产生下一 Revision。

## 22. External Skill Registry

External Skill 表示当前 Host 已有的 Agent-native package，不是 managed Skill Revision。先配置显式 target 并重启：

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

扫描和列出：

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

解析 `list` 返回的第一份精确本地 package：

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

只有 Agent、Host、scope、locator、文件内容和 fingerprint 都匹配时，status 才是 `available`。Server 不会远程
查找或安装缺失 package。

如需把这个精确 snapshot 纳入 managed lifecycle，请选择 `import` 或 `fork`，并把它送入 Review：

```bash
jq '. + {
  mode: "fork",
  reason: "为账单 API 项目适配这个本地 package"
}' \
  /tmp/powercontext-external-skill-resolve.json \
  > /tmp/powercontext-external-skill-import.json

curl --fail --silent --show-error \
  --request POST --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-external-skill-import.json \
  "$POWERCONTEXT_URL/v1/external-skills/import" \
  | jq .
```

Import 会捕获 exact local snapshot，并调用 generation model 创建 pending managed Skill Candidate。它不会自动批准、
安装、执行或覆盖原 package。

## 23. Scoped Stats

```bash
curl --fail --silent --show-error \
  --get \
  --data-urlencode "scope_id=$POWERCONTEXT_SCOPE" \
  --data-urlencode 'period=7d' \
  "$POWERCONTEXT_URL/v1/stats" \
  | jq .
```

`period` 支持 `today`、`7d`、`30d`。响应提供当前 inventory、model usage 和 recall token estimates，并带
`Cache-Control: no-store`。统计不应包含 prompt、Memory 正文、token、URL 或内部异常内容。

## 24. Handoff Report API

Report API 是 Handoff 之上的运营投影。只想按 scope 查看 committed Handoff 时，不需要创建 Project：

```bash
curl --fail --silent --show-error \
  --request POST --header 'Content-Type: application/json' \
  --data '{}' \
  "$POWERCONTEXT_URL/v1/handoff-reports/scopes/list-known" \
  | jq .

curl --fail --silent --show-error \
  --request POST --header 'Content-Type: application/json' \
  --data "$(jq -n --arg scope "$POWERCONTEXT_SCOPE" \
    '{scope_id: $scope, locale: "zh-CN", format: "json", include_evidence_checks: true}')" \
  "$POWERCONTEXT_URL/v1/handoff-reports/get" \
  | jq .
```

完整 Project/Workstream 目录流程：

| 顺序 | Operation | 用途 |
| --- | --- | --- |
| 1 | `POST /v1/handoff-reports/projects/create` | 创建 Project，保存 `project_id` 和 `version` |
| 2 | `POST /v1/handoff-reports/projects/list` | 分页查询 Project |
| 3 | `POST /v1/handoff-reports/projects/get` | 按精确 ID 读取 Project |
| 4 | `POST /v1/handoff-reports/projects/update` | 传回完整 `ProjectDescriptor + expected_version` |
| 5 | `POST /v1/handoff-reports/workstreams/register` | 将稳定 `scope_id` 注册到 Project |
| 6 | `POST /v1/handoff-reports/workstreams/list` | 分页查询 Project 的 Workstream |
| 7 | `POST /v1/handoff-reports/workstreams/update` | 传回完整 `WorkstreamDescriptor + expected_version` |
| 8 | `POST /v1/handoff-reports/activities/record` | 使用 `source_event_id` 幂等记录观察结果 |
| 9 | `POST /v1/handoff-reports/activities/list` | 在冻结的 Activity cursor 范围内分页 |
| 10 | `POST /v1/handoff-reports/activities/purge` | 删除 `observed_before` 之前由 Report 管理的行 |
| 11 | `POST /v1/handoff-reports/workspace-bindings/attach` | 使用 version CAS 确认 Workspace 到 Project 的绑定 |
| 12 | `POST /v1/handoff-reports/workspace-bindings/get` | 按 Workspace instance ID 读取绑定 |
| 13 | `POST /v1/handoff-reports/workspace-bindings/detach` | 停用精确 current version 的绑定 |

创建 Project 示例：

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data '{
    "project_key": "billing-api",
    "title": "Billing API",
    "description": "自建 AI 工程助手的账单 API 项目",
    "default_locale": "zh-CN",
    "timezone": "Asia/Shanghai"
  }' \
  "$POWERCONTEXT_URL/v1/handoff-reports/projects/create" \
  | tee /tmp/powercontext-report-project.json \
  | jq .
```

查询、精确读取并更新这个 Project：

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
  project: (. + {description: "账单 API 项目及其 AI 助手工作流"}),
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

注册 Workstream：

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  '{
    project_id: .project_id,
    scope_id: $scope,
    key: "refund-validation",
    title: "退款资格验证",
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

使用精确 current version 查询并更新 Workstream：

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

记录并查询一条不可信的运营观察。复用相同 `source_event_id` 和相同 payload 是幂等操作；复用 ID 但修改内容会冲突：

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
    title: "完成 API 教程",
    summary: "验证账单助手的上下文与 Handoff 流程",
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

`purge` 是管理型 retention 操作。下面的请求特意使用很早的边界；在非临时环境执行前仍要检查目标：

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

最后，绑定、读取并按需停用 Workspace binding。第一次 attach 使用 `expected_version: null`，后续 mutation 使用响应
返回的精确 version：

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

# 只有确实要停用这条绑定时才运行。
curl --fail --silent --show-error \
  --request POST --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-report-workspace-detach.json \
  "$POWERCONTEXT_URL/v1/handoff-reports/workspace-bindings/detach" \
  | jq .
```

Report update、Activity purge 和 workspace detach 都会改变状态，应限制为管理权限。Report 功能被配置关闭时，这组
route 不会注册。

## 25. 错误、并发与重试

稳定错误 envelope：

```json
{
  "error": {
    "code": "invalid_request",
    "message": "The request violates the API contract.",
    "details": {}
  }
}
```

| 状态码 | 常见原因 | 处理方式 |
| --- | --- | --- |
| `401` | Bearer token 缺失或无效 | 不重试，修复凭据 |
| `404` | 精确 Source、Artifact、Candidate 或 binding 不存在 | 重新 list/get，不猜测 ID |
| `409` | Source 内容冲突、旧 citation/version、target head 已推进 | 读取最新状态，让用户重新决定 |
| `413` | Report 输出超过限制 | 缩小选择或输出范围 |
| `422` | JSON 类型、必填字段、长度或 provenance shape 错误 | 修复客户端，不盲目重试 |
| `503` | Runtime capability 或依赖不可用 | 读请求可降级；写请求显式失败 |
| `500` | Server 内部错误 | 记录 request ID，有限退避重试 |

重试规则：

- health、capabilities、search、list、get、prepare 等只读操作可以有限重试；
- Source capture 使用稳定 `source_id`，可以安全重放相同内容；
- Candidate approve/revise、Memory mutate、Report update 必须先刷新 version/citation；
- 不要无限重试无法确认结果的非幂等写入；
- 日志只记录 operation、状态、稳定 error code、延迟和 request ID，不记录用户正文或凭据。

## 26. 生产权限建议

至少分开三类调用身份：

| 身份 | 典型权限 |
| --- | --- |
| AI 请求服务 | prepare、search、exact get；必要时提交 proposal |
| Evidence writer | capture Source、remember、Work/Handoff/Outcome 写入 |
| Reviewer/Admin | Candidate approve/reject/revise、Report update/purge、Skill publication |

不要因为 endpoint 在同一个 Server 上就让同一模型身份拥有所有权限。`scope_id` 也不能代替 ACL。

## 27. 上线检查清单

- [ ] Server 使用持久化数据库、备份、TLS、健康检查和监控；
- [ ] 调用者身份由 Gateway 映射到允许访问的 scope；
- [ ] 模型拿不到 Bearer token、任意 scope、Reviewer 或 Admin 权限；
- [ ] Source 采集经过同意、敏感字段过滤和保留期限控制；
- [ ] 每个模型请求最多调用一次 `/v1/context/prepare`；
- [ ] PreparedContext 保持只读、不可信，当前指令和实时验证优先；
- [ ] Memory 写入是短小、明确、经过授权的长期信息；
- [ ] Candidate 必须由独立 Reviewer 检查 exact version 和 lineage；
- [ ] approved Skill 仍需单独的执行授权和环境验证；
- [ ] 所有 mutation 保存 exact citation、ArtifactRef 或 expected version；
- [ ] 客户端记录 `X-PowerContext-Request-ID`，但不记录正文或凭据；
- [ ] `/openapi.json` 生成的客户端固定并验证契约版本；
- [ ] 完整验证包含重启 Server 后的 Memory、Artifact 和 Handoff 持久化检查。

至此，你已经通过一套连续 HTTP API 流程跑通 PowerContext 的主要数据面、治理面和运营面。需要查找某个字段、
enum、限制或完整响应时，继续使用 [HTTP API 参考](../reference/http-api.md)和当前进程的 `/openapi.json`。
