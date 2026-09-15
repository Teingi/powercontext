---
title: 代码上下文验收
description: Git 仓库理解的真实引擎、服务、宿主验收和 12 个跨模块任务配对结果。
---

# 代码上下文验收

当前代码补充适合作为显式启用的代码定位能力。2026-09-16 的首轮任务评估未证明端到端效率或 token 收益，
因此功能保持默认关闭；不能据此宣称更快完成任务或可以安全减少测试。

## 环境与可重复运行

验收使用 Linux x64、Python 3.14、CodeGraph 1.6.0 standalone。发布包摘要和部署步骤见
[在上下文中使用当前代码](../workflows/git-repository-understanding.md)。配置中的 OceanBase、generation model 和 embedding
model 均实际调用；配置与凭据不写入报告。数据库验收创建独立随机数据库，并在结束时删除及核对。

```bash
export POWERCONTEXT_TEST_CODEGRAPH_EXECUTABLE=/srv/powercontext/tools/codegraph-linux-x64/bin/codegraph
uv run pytest tests/builtin/code tests/e2e/test_code_context.py -q
POWERCONTEXT_TEST_NATIVE_CODEX=1 uv run pytest \
  tests/e2e/real_experience_skill/test_code_context.py \
  --run-real-e2e --real-e2e-env-file .env -q -s
```

第二条测试需要已登录的 Codex。它安装隔离插件，复制必要身份配置到私有测试目录，不改用户 Codex 配置。
测试实际经过 OceanBase、embedding/向量召回、HTTP、Client、MCP、原生 Codex Hook 和模型。
Codex 修改夹具、执行 Python 检查；保存并继续 Handoff 后，重新构建索引并核对新代码指纹。
最后清理代码缓存，再读取此前显式保存的 Source。测试输出报告包含检查项和数据库清理结果。

日常自动化未提供真实引擎或 `--run-real-e2e` 时会跳过对应验收；普通单元测试通过不代表这些真实路径已运行。

## 已验证的行为

- Git 的暂存、未暂存、未跟踪、忽略、删除及实际内容摘要；路径逃逸、链接和凭据排除。
- 小预算、中文、长行、恶意 Markdown、完整出处、统一字节及条数预算。
- 独立查询、根目录和嵌套测试、同名定义的不确定关系、缓存失效和旧指纹拒绝。
- 中断构建与重新打开、并发刷新/查询、查询后发生编辑、超时、完整缓存发布。
- HTTP Scope 授权先于目录访问；Context Reference 和 Handoff-only 权限不能读取仓库。
- 正常 prepare 不写 Source/Artifact；代码 Source 不进入自动处理，后续普通 Source 正常推进游标。
- 旧 Server 协议降级、新 Client 默认请求兼容、MCP 操作必填字段及只读标注、宿主原样交付。

## 仓库规模与查询成本

在 PowerContext 源码中实际纳入 791 个 Python 文件，省略 798 个文件，其中 795 个为不支持的语言、3 个被排除。
一次全量构建为 28.476 秒，三次 prepare 代码查询分别为 4.467、2.695、3.684 秒，均在默认 5 秒预算内。
该观测不代表其他主机、并发负载或更大仓库的延迟保证。解析错误计数为 0 也不证明静态图完整。

## 12 个配对任务

`scripts/code_context_tasks.py` 提供自有 Python 夹具：价格计算、订单入口、重试延迟、标签规范化及跨文件测试，
另含 24 个无关模块。任务覆盖三类定义定位、三条调用路径、两次测试线索查询、三个行为修改和一次接口修改后的继续工作。
每任务开/关各运行两次，共 48 次真实模型运行；修改任务在每组共 8 次，均运行不变的回归测试及行为验收。

```bash
uv run python scripts/evaluate_code_context.py \
  --env-file .env \
  --codegraph "$POWERCONTEXT_TEST_CODEGRAPH_EXECUTABLE" \
  --output /absolute/new/code-evaluation \
  --repeats 2 --concurrency 2
```

固定同一配置模型 `openai:qwen3.7-plus`、temperature=0、提示、read/search/write/check 工具、Memory 内容、初始文件和 8000 字节预算。
每次使用独立 SQLite、Scope、仓库和缓存；第二轮反转开关顺序。配对实验中的历史召回不调用 embedding，真实 embedding
由前述配置服务验收覆盖。模型使用提示约束的 JSON 输出，因为配置模型不接受强制输出工具。
已完成的结果会复用，不重复收费；要重新运行模型请使用新输出目录。

| 指标 | 关闭代码 | 开启代码 |
| --- | ---: | ---: |
| 运行次数 | 24 | 24 |
| 正确定义文件集合 | 22/24 | 23/24 |
| 正确调用方集合 | 20/24 | 22/24 |
| 正确测试文件集合 | 20/24 | 20/24 |
| 额外调用方 / 测试文件数 | 2 / 2 | 1 / 4 |
| 补丁行为检查 | 8/8 | 8/8 |
| 原有回归和测试文件保持不变 | 24/24 | 24/24 |
| prepare 中位耗时 | 0.12 秒 | 2.24 秒 |
| Agent 中位耗时 | 16.14 秒 | 20.30 秒 |
| prepare + Agent 中位耗时 | 16.32 秒 | 22.36 秒 |
| 注入字节中位数 | 410.5 | 3166 |
| 成功输出的输入 token 中位数 | 6097.5 | 14240 |
| 成功输出的输出 token 中位数 | 826.5 | 1160 |

“正确定义文件”允许文件名附带符号或行号，原始回答及格式评分均保留。回答失败按未完成计入分母。
关闭组有 2 次模型输出不符合结构；开启组有 1 次超过调用/token 限额，该次补丁已通过外部行为检查，但最终回答未完成。
token 统计只覆盖有完整 usage 的 22/23 次运行，不用 0 填补失败调用。

首次定义线索的时间从模型开始计量：初始注入已包含目标文件则为 0，否则以首次读取目标文件计时。
两轮中位数分别为关闭 4.58/5.35 秒、开启 2.02/0 秒；这衡量线索何时可见，不证明模型此刻已理解正确。
两轮 Agent 耗时中位数为关闭 15.64/16.44 秒、开启 23.07/18.09 秒，说明结果存在波动。
全量索引成本另计，两组中位数约 3.22 秒；在线 prepare 不隐式包含建图。

## 结论与限制

这组任务验证了代码线索可交付、补丁没有退化，但增加了上下文、模型消耗和端到端耗时。
静态测试线索仍有漏报和误报，尚无减少测试数量的依据。小型自有夹具不等同于真实大型项目修改成功率；
PowerContext 源码测量验证了部署和查询成本，没有用模型批量修改 PowerContext 作为 benchmark。
推广前应在自己的代表性任务中继续比较候选相关性、预算占用和端到端收益。
