---
title: 配置 DeepSeek Harness
description: 安装 PowerContext DeepSeek Harness 插件并控制其本地行为。
---

# 配置 DeepSeek Harness

## 安装或刷新插件

先安装 DeepSeek Harness，并确保 web profile 可用。然后根据已安装的 PowerContext 工具选择对应命令：

```bash
# 从 PyPI 安装的 PowerContext 0.1.0
powercontext setup dsh --source oceanbase/powercontext --ref powercontext-v0.1.0

# 从 Git 安装的最新未发布 PowerContext
powercontext setup dsh --source oceanbase/powercontext --ref master
```

该命令会从 `integrations/dsh/plugins/powercontext` 安装插件，并创建用户数据目录。该目录必须包含已构建的 `lib/index.js`。重复执行是安全的：有效 checkout 会复用，同一 ref 下的残缺 checkout 会被替换。`--ref` 应与安装 PowerContext 工具时使用的 ref 一致。`--source` 可以是 GitHub slug，也可以是 `https://github.com/...` URL。

本地 checkout 同样可以：

```bash
powercontext setup dsh --source .
```

`setup dsh` 内部会执行 `dsh plugin --profile web add`。完成下面的启动和检查步骤后，再打开新的 `dsh web` 会话。

## 启动并验证集成

在单独的终端中启动 Server，并保持该进程运行：

```bash
powercontext server run
```

启动成功后会输出本地 Dashboard 地址。在另一个终端中检查 Server 和已安装的 DSH 插件，然后打开新的 DSH 会话：

```bash
powercontext doctor
powercontext doctor dsh
dsh web
```

在 DSH 中运行 `/pc doctor`，结果应显示 Server 的 liveness 和 readiness 检查成功。插件不会在每次普通对话中都显示
成功提示；Server 不可用时，召回和采集会正常降级，让 DSH 可以在没有 PowerContext 的情况下继续工作。请使用
`/pc doctor` 区分正常降级和已经建立的连接。

## 理解插件行为

插件通过两条路径访问同一个 Server：

- 每轮模型开口前，先请求 Runtime 准备一个最终、有界的上下文值，再把用户输入采集为 Source 证据；
- 具名 `pc_*` 工具通过公开 HTTP API 记忆、检索、修订、停用和审计 Memory。

存在 Git remote 时，Memory scope 根据规范化后的 remote 生成；否则根据会话工作区路径生成。会话没有工作区 cwd、或 scope 必须独立于这两者时，设置 `POWERCONTEXT_DSH_SCOPE_ID`。插件不会把 Harness 进程目录当成项目 scope。

插件在模型分析提示词前只调用一次 `POST /v1/context/prepare`。显式 `remember_memory` 不需要模型。

## 控制提示词采集

默认开启提示词采集。如果当前工作不应被记录，请在启动 DeepSeek Harness 前关闭：

```bash
export POWERCONTEXT_DSH_CAPTURE_PROMPTS=false
dsh web
```

仅在测试时让插件等待 Source 处理完成：

```bash
export POWERCONTEXT_DSH_FLUSH_ON_CAPTURE=true
```

这会给每个提示词增加推理延迟，不是日常交互设置。`timeoutMs`、`requestTimeoutMs`、`maxBytes` 和 `flushMaxCalls` 是插件 patch 配置，不是环境变量。

## 连接启用鉴权的本地 Server

```bash
export POWERCONTEXT_SERVER_AUTH_ENABLED=true
export POWERCONTEXT_SERVER_AUTH_TOKEN="$POWERCONTEXT_LOCAL_TOKEN"
powercontext server run
```

在包含匹配 Authorization header 的环境中启动 DeepSeek Harness：

```bash
export POWERCONTEXT_DSH_AUTHORIZATION="Bearer $POWERCONTEXT_LOCAL_TOKEN"
dsh web
```

不要把 token 写进 patch 文件或 Server URL。Server 不可用时，召回和采集会正常降级。插件加载仍然需要 DeepSeek Harness 的 peer 模块。
