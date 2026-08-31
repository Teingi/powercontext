---
title: 用 HTTP API 为自己的 AI 接入 Memory
description: 不依赖 Agent Host，通过 PowerContext HTTP API 为自己的 AI 应用保存、召回、注入、修订和停用长期记忆。
---

# 用 HTTP API 为自己的 AI 接入 Memory

本教程面向已经有 AI 应用、聊天机器人、工作流或模型调用代码，但不使用 Codex、Claude Code、OpenCode
等 Agent Host 的开发者。你会把 PowerContext 当作独立的 Memory 服务，通过 HTTP API 接入现有 AI 请求链。

完成后，你的应用会具备下面的闭环：

```text
用户请求
  → 应用调用 POST /v1/context/prepare
  → 应用把返回的只读历史上下文交给模型
  → 模型回答
  → 用户或应用策略确认值得长期保留的内容
  → 应用调用 POST /v1/memory/remember
```

这个流程不要求安装任何 Agent Host，也不要求为显式 Memory 配置 generation model。PowerContext 负责持久化、
检索、精确 citation 和修订历史；你的应用仍然负责身份、权限、当前指令、模型调用以及哪些内容可以写入 Memory。

## 本教程使用的接口

| 方法与路径 | 作用 | 是否改变持久化状态 |
| --- | --- | --- |
| `GET /health/live` | 检查 Server 进程 | 否 |
| `GET /health/ready` | 检查必需 Runtime 绑定 | 否 |
| `GET /v1/capabilities` | 查看当前启用的 Runtime 能力 | 否 |
| `POST /v1/memory/remember` | 保存一条已经整理和授权的 Memory | 是 |
| `POST /v1/memory/search` | 按问题检索 active Memory | 否 |
| `POST /v1/memory/entries/list` | 列出当前 Memory head | 否 |
| `POST /v1/memory/entries/get` | 按 citation 读取不可变版本 | 否 |
| `POST /v1/context/prepare` | 为一次模型请求准备有界上下文 | 否 |
| `POST /v1/memory/entries/revise` | 基于精确 citation 创建修订版本 | 是 |
| `POST /v1/memory/entries/retire` | 停用条目但保留历史 | 是 |
| `POST /v1/sources/content` | 可选地保存原始证据 | 是 |

## 1. 先理解三个边界

### `scope_id` 是数据分区，不是权限

同一个用户、项目或业务空间的所有 Memory 请求必须使用稳定的 `scope_id`。例如：

```text
tenant:acme:user:42
```

不要使用每次都会变化的会话 ID。`scope_id` 只告诉 PowerContext 去哪个分区读写数据，不会证明调用者有权访问该
分区。生产环境必须由你的认证层、API Gateway 或 Service Mesh 验证调用者，并将调用者映射到允许访问的 scope。

### `PreparedContext` 是不可信历史数据

`POST /v1/context/prepare` 返回的是带 citation、有字节上限、只在本次请求中使用的历史上下文。它不是当前用户
指令，也不能覆盖 system/developer 指令、仓库规则或实时验证结果。PowerContext 返回的 `content` 已包含信任边界
说明；应用应保持原文，不要把它改写成更高优先级的指令。

### 读取可以降级，写入必须明确

如果准备上下文暂时失败，AI 应用通常可以在没有历史上下文的情况下继续回答，并记录请求 ID 以便排查。写入、
修订或停用失败时，不应伪装成成功。除非产品已经有明确、可审计的写入策略，否则让用户确认后再保存长期 Memory。

## 2. 准备环境

需要：

- macOS 或 Linux；
- Python 3.11 或更高版本；
- [`uv`](https://docs.astral.sh/uv/)；
- `curl`；
- `jq`，用于查看响应和复用精确 citation。

检查本地工具：

```bash
python3 --version
uv --version
curl --version
jq --version
```

安装 PowerContext CLI 和 Server：

```bash
uv tool install --force "powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@master"
```

确认安装成功：

```bash
powercontext --version
powercontext server --help
```

## 3. 启动并检查 Server

准备两个终端。在**终端 A**持续运行：

```bash
powercontext server run
```

默认 Server 监听 `http://127.0.0.1:8000`，并使用本机 PowerContext 数据目录中的 SQLite 数据库持久化数据。

在**终端 B**设置本教程使用的变量：

```bash
export POWERCONTEXT_URL=http://127.0.0.1:8000
export POWERCONTEXT_SCOPE=tenant:demo:user:42
```

检查进程与 Runtime：

```bash
curl --fail --silent --show-error "$POWERCONTEXT_URL/health/live" | jq .
curl --fail --silent --show-error "$POWERCONTEXT_URL/health/ready" | jq .
curl --fail --silent --show-error "$POWERCONTEXT_URL/v1/capabilities" | jq .
```

**成功标准：** liveness 请求返回 `200`；readiness 返回 `200`，且状态不是 `not_ready`；capabilities 能列出当前
Runtime 能力。显式 Memory 即使没有 generation model 也可以工作；模型抽取和向量检索属于可选能力。

## 4. 保存第一条显式 Memory

先保存一条已经由用户或业务规则确认的长期信息：

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n \
    --arg scope "$POWERCONTEXT_SCOPE" \
    --arg kind decision \
    --arg text '回答账单问题时，先解释费用构成，再提供退款入口。' \
    --arg reason '用户确认的客服策略' \
    '{scope_id: $scope, kind: $kind, text: $text, reason: $reason}')" \
  "$POWERCONTEXT_URL/v1/memory/remember" \
  | tee /tmp/powercontext-remember.json \
  | jq .
```

响应结构类似下面这样。ID 由 Server 生成，每次运行都会不同：

```json
{
  "memory": {
    "family": "memory",
    "artifact_id": "memory-example",
    "revision": 1
  },
  "entry": {
    "citation": {
      "memory_ref": {
        "family": "memory",
        "artifact_id": "memory-example",
        "revision": 1
      },
      "entry_id": "entry-example",
      "entry_version_id": "entry-version-example"
    },
    "version": 1,
    "kind": "decision",
    "text": "回答账单问题时，先解释费用构成，再提供退款入口。",
    "state": "active",
    "source_refs": [],
    "artifact_refs": []
  }
}
```

`memory.revision` 表示这次写入后的 Memory Revision。`entry.citation` 精确指向一个不可变条目版本；读取、修订和
停用都要传回完整 citation，不能只保存 `entry_id`。

`remember` 只保存已经整理好的 Memory，不会创建 Source，也不会调用 generation model。需要保留原始证据时，
使用第 11 步的 Source 接口。

## 5. 搜索、列出和精确读取 Memory

### 搜索与当前问题相关的条目

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n \
    --arg scope "$POWERCONTEXT_SCOPE" \
    --arg query '用户问账单和退款时应该怎么回答？' \
    '{scope_id: $scope, query: $query, limit: 5, mode: "auto"}')" \
  "$POWERCONTEXT_URL/v1/memory/search" \
  | jq .
```

响应中的 `hits` 只包含 active 条目。每个 hit 都有 `citation`、`text`、`score` 和 `matched_by`。`mode: "auto"`
会使用当前 Runtime 可用的检索模式；没有匹配项时正常返回 `"hits": []`，不是错误。

### 列出当前 Memory head

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n --arg scope "$POWERCONTEXT_SCOPE" '{scope_id: $scope}')" \
  "$POWERCONTEXT_URL/v1/memory/entries/list" \
  | jq .
```

审计时可以增加 `"include_inactive": true`，查看当前 head 中已停用的条目。默认不会返回它们。

### 按精确 citation 读取

下面的命令从第 4 步保存的响应构造请求：

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  '{scope_id: $scope, citation: .entry.citation}' \
  /tmp/powercontext-remember.json \
  > /tmp/powercontext-get.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-get.json \
  "$POWERCONTEXT_URL/v1/memory/entries/get" \
  | jq .
```

精确读取返回 citation 指向的不可变版本，即使以后该条目已经被修订或停用，也不会悄悄换成另一个版本。

## 6. 在每次模型请求前准备上下文

应用收到用户问题后，调用一次 `POST /v1/context/prepare`：

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n \
    --arg scope "$POWERCONTEXT_SCOPE" \
    --arg query '我的账单为什么这么高？如果不认可可以退款吗？' \
    '{scope_id: $scope, query: $query, max_bytes: 4000}')" \
  "$POWERCONTEXT_URL/v1/context/prepare" \
  | tee /tmp/powercontext-prepared.json \
  | jq .
```

有相关内容时，响应为：

```json
{
  "schema": "powercontext.prepared-context.v1",
  "status": "ready",
  "content": "BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1\n…\nEND_POWERCONTEXT_PREPARED_CONTEXT_V1",
  "content_bytes": 987
}
```

没有可用内容时，这是正常结果：

```json
{
  "schema": "powercontext.prepared-context.v1",
  "status": "empty",
  "content": null,
  "content_bytes": 0
}
```

应用只在 `status == "ready"` 且 `content` 为字符串时注入。不要把 `PreparedContext` 再写回 Memory；它是本次
请求的临时组合结果，不是新的事实。

## 7. 接入现有 AI 调用代码

下面使用 Python 标准库完成 PowerContext 请求，并把模型调用留在一个明确的适配函数中。这样可以继续使用你已经
选定的模型 SDK，而不会让 Memory 层绑定某一家模型服务。

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


def prepare_context(user_query: str) -> str | None:
    try:
        prepared = powercontext_post(
            "/v1/context/prepare",
            {
                "scope_id": POWERCONTEXT_SCOPE,
                "query": user_query[:8192],
                "max_bytes": 4000,
            },
        )
    except (HTTPError, URLError, TimeoutError):
        # 读取失败可以降级：记录错误和 request ID，然后让主模型请求继续。
        return None

    if prepared.get("status") != "ready":
        return None
    content = prepared.get("content")
    return content if isinstance(content, str) else None


def ask_ai(
    user_query: str,
    call_your_model: Callable[[list[dict[str, str]]], str],
) -> str:
    messages = [
        {
            "role": "system",
            "content": "Follow current application policy and the user's current request.",
        }
    ]

    context = prepare_context(user_query)
    if context is not None:
        # 如果模型 API 有低权限的 context/tool-result 通道，优先使用它。
        # 使用 messages API 时，不要把历史内容升级成 system/developer 指令。
        messages.append({"role": "user", "content": f"Historical reference data:\n{context}"})

    messages.append({"role": "user", "content": user_query})
    return call_your_model(messages)
```

把你现有的模型调用封装成 `call_your_model(messages) -> str`，然后调用：

```python
answer = ask_ai("我的账单为什么这么高？", call_your_model)
```

关键约束：

- 一个用户请求只调用一次 `prepare`，不要先 search 再让 `prepare` 重复检索；
- 保留 PowerContext 返回的 `content`，让其中的 citation 与信任说明保持完整；
- 当前用户请求和实时业务数据始终高于历史 Memory；
- 上下文读取可以 fail open，写操作不能静默失败；
- 不要把 PowerContext token、数据库连接串或内部身份信息交给模型。

## 8. 让模型通过工具主动查找或建议 Memory

如果模型支持 function/tool calling，可以把你自己的包装函数暴露给模型，但不要让模型直接持有 Server token 或
任意填写 `scope_id`。应用应从已认证会话注入这两个值。

建议只暴露下面三类工具：

| 模型工具 | PowerContext API | 调用策略 |
| --- | --- | --- |
| `search_project_memory(query, limit)` | `POST /v1/memory/search` | 可自动调用；限制 query 长度和 limit |
| `get_memory(citation)` | `POST /v1/memory/entries/get` | 可自动调用；citation 必须来自同一 scope 的响应 |
| `propose_memory(kind, text, reason)` | 经用户确认后调用 `POST /v1/memory/remember` | 模型只能提出建议，应用负责确认和写入 |

包装函数示例：

```python
def search_project_memory(query: str, limit: int = 5) -> dict[str, Any]:
    return powercontext_post(
        "/v1/memory/search",
        {
            "scope_id": POWERCONTEXT_SCOPE,
            "query": query[:8192],
            "limit": max(1, min(limit, 50)),
            "mode": "auto",
        },
    )


def remember_after_approval(kind: str, text: str, reason: str) -> dict[str, Any]:
    # 在进入这个函数之前，由 UI 或业务规则产生可审计的批准结果。
    return powercontext_post(
        "/v1/memory/remember",
        {
            "scope_id": POWERCONTEXT_SCOPE,
            "kind": kind[:128],
            "text": text,
            "reason": reason[:512],
        },
    )
```

不要把“模型调用了 `propose_memory`”本身当作授权。应用可以先在 UI 中显示建议内容，让用户选择保存、编辑或忽略。
也不要保存模型的整段回答；长期 Memory 应是短小、明确、以后仍然成立的决定、偏好、约束、状态或下一步。

## 9. 修订错误 Memory

Memory 条目不会原地覆盖。修订会创建新版本并保留历史。下面使用第 4 步的精确 citation：

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  --arg text '回答账单问题时，先解释费用构成；只有符合退款政策时才提供退款入口。' \
  '{
    scope_id: $scope,
    citation: .entry.citation,
    kind: "decision",
    text: $text,
    reason: "客服政策已澄清"
  }' \
  /tmp/powercontext-remember.json \
  > /tmp/powercontext-revise.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-revise.json \
  "$POWERCONTEXT_URL/v1/memory/entries/revise" \
  | tee /tmp/powercontext-revised.json \
  | jq .
```

响应中的 `entry.citation` 指向新版本。后续修订或停用必须使用这个新 citation；继续使用旧 citation 会收到 `409`
冲突，防止并发请求覆盖更新后的内容。

## 10. 停用过期 Memory

停用不会物理删除历史。下面使用修订响应中的最新 citation：

```bash
jq --arg scope "$POWERCONTEXT_SCOPE" \
  '{
    scope_id: $scope,
    citation: .entry.citation,
    reason: "该客服流程已经下线"
  }' \
  /tmp/powercontext-revised.json \
  > /tmp/powercontext-retire.json

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data @/tmp/powercontext-retire.json \
  "$POWERCONTEXT_URL/v1/memory/entries/retire" \
  | jq .
```

停用后，普通 search、list 和 prepare 不再使用该条目；`include_inactive: true` 的 list 和精确 get 仍可用于审计。

## 11. 可选：保存原始 Source 证据

如果需要保留某次用户确认、文档片段或业务事件作为后续处理的证据，可以调用：

```bash
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "$(jq -n \
    --arg scope "$POWERCONTEXT_SCOPE" \
    --arg source_id 'support-chat:session-7:turn-12' \
    --arg content '用户确认：以后账单回复必须先解释费用构成。' \
    '{
      scope_id: $scope,
      source_id: $source_id,
      content: $content,
      metadata: {channel: "support-chat", consent: true}
    }')" \
  "$POWERCONTEXT_URL/v1/sources/content" \
  | jq .
```

成功时返回 `202 Accepted`。同一个 `source_id` 应稳定指向同一份内容，以支持幂等采集。

Source 是原始证据，不等于 Memory。这个接口不会同步调用模型，也不会立即把内容变成可召回 Memory。需要自动抽取时，
必须另外配置 generation model，并使用 Runtime 的 flush 或 scheduler 流程；参见[完整功能 Quick Start](../how-to/full-capability-runtime.md)。

不要默认采集整段对话。先做用户同意、敏感字段过滤、保留期限和用途限制，再把必要证据写入 Source。

## 12. 验证跨进程持久化

1. 停止终端 A 中的 Server；
2. 再次运行 `powercontext server run`；
3. 重复第 5 步的 search 或 list 请求。

只要使用同一数据目录和同一 `scope_id`，之前保存的 active Memory 仍然存在。不要把容器临时文件系统或测试数据库
误当作生产持久化；服务化部署参见[部署 Server](../how-to/deploy-server.md)。

## 13. 启用鉴权或远程访问

默认 loopback 开发环境可以不启用 Server Bearer 鉴权。启用后，在除 health 之外的每个请求中增加：

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

Python 示例会在设置 `POWERCONTEXT_CLIENT_API_TOKEN` 后自动发送该 header。不要把 token 放进 URL、Memory、Source、
日志或模型 prompt。允许远程访问前，应在可信网关终止 TLS，并在那里执行身份验证、scope 授权、限流和审计。

## 14. 处理错误

错误响应使用稳定 envelope：

```json
{
  "error": {
    "code": "invalid_request",
    "message": "The request violates the API contract.",
    "details": {}
  }
}
```

每个响应都包含 `X-PowerContext-Request-ID`。生产客户端应记录状态码、稳定的 `error.code` 和 request ID，不要依赖
内部异常文本。

| 状态码 | 常见原因 | 应用处理 |
| --- | --- | --- |
| `401` | 缺少或使用了无效 Bearer token | 不重试；修复凭据 |
| `404` | citation 指向的不可变值不存在 | 重新读取列表或搜索结果 |
| `409` | 使用了过期 citation 或发生不可变状态冲突 | 重新读取最新 entry，让用户重新决定 |
| `422` | 字段缺失、超长、为空或类型错误 | 修复客户端输入，不盲目重试 |
| `503` | 必需 Runtime 绑定或依赖不可用 | 读取路径可降级；写路径报告失败并稍后重试 |
| `500` | Server 内部错误 | 记录 request ID，有限退避重试 |

网络超时也应有限重试。不要自动重试一次非幂等写入直到确认前一次请求是否已经成功；可先按业务键搜索或使用明确
的幂等 Source `source_id`。

## 15. 上线检查清单

- [ ] `scope_id` 来自可信的用户、租户或项目映射，不接受模型任意指定；
- [ ] Gateway 对每个调用者执行 scope 授权，因为 `scope_id` 本身不是 ACL；
- [ ] 每个模型请求最多调用一次 `/v1/context/prepare`；
- [ ] `PreparedContext` 保持只读、不可信，当前指令和实时数据优先；
- [ ] prepare 超时不会阻断主模型请求，写入失败不会被吞掉；
- [ ] 模型只能建议 Memory，保存、修订和停用遵循可审计的用户或业务授权；
- [ ] token、密码、连接串、私钥和受保护原文不会进入 Memory、Source、prompt 或日志；
- [ ] 客户端保存精确 citation，并在 `409` 后重新读取而不是覆盖；
- [ ] 设置连接、读取和总请求超时，并记录 `X-PowerContext-Request-ID`；
- [ ] Server 使用持久化数据库、备份、TLS、监控和合理的限流；
- [ ] 使用 `/openapi.json` 或仓库中的 `openapi/powercontext.yaml` 生成客户端时，固定并验证契约版本。

至此，你的 AI 应用已经不依赖任何 Agent Host，能够通过 HTTP 完成长期 Memory 的保存、请求时召回、模型注入、
精确读取、修订和停用。全部路径、字段限制和响应 schema 见 [HTTP API 参考](../reference/http-api.md)。
