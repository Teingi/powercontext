# PowerContext × Jev / Laya：跨会话编码与决策示例

通过本地 API 保存上一轮确认的项目约定，再让新的进程召回记忆。随后用同一个生成模型分别编写两份金额转换函数：一份只收到当前任务，另一份还收到 PowerContext 实际召回的上下文。可选用 Jev / Laya 审核两份代码，运行独立测试比较实际表现，再把结果保存为下一轮可召回的记忆。

场景是账单导出：`cents(text: str) -> int` 把金额字符串转换为整数分。团队之前约定使用 `Decimal` 和 `ROUND_HALF_UP`，负数退款采用相同的对称舍入规则，非法文本、`NaN` 和 `Infinity` 抛出 `ValueError`。例如，`1.005` 应得到 `101`，`-1.005` 应得到 `-101`。

记忆、模型响应、代码和测试结果都来自本次执行。示例不预设哪组获胜；两组可能都通过，也可能都失败。

## 启动 API 服务

以下命令从仓库根目录执行。需要 Linux / macOS、Python 3.11+、`uv`，以及一个支持 OpenAI Chat Completions 请求格式的真实生成模型服务。

复制配置模板，填写生成模型及需要启用的审核服务；已有同名配置文件时，请直接补齐变量：

```bash
cp examples/systemone/server.env.example examples/systemone/.env.systemone
```

启动：

```bash
uv run --extra server \
  python -m examples.systemone.server \
  --env-file examples/systemone/.env.systemone \
  --data-dir .powercontext/systemone \
  --port 8765
```

使用 Laya 时，在 `uv run` 后添加 `--with 'transformers>=4,<6'`，用于本地输入长度检查。仅使用 Jev 或不启用审核时，不需要 Transformers。

服务监听 `127.0.0.1`。检查配置和已有实验：

```bash
curl --fail --silent --show-error http://127.0.0.1:8765/api/status
```

`configured` 表示本地配置有效，不代表已经验证远端连通性。服务会执行模型生成的受限金额函数，适合本机运行；执行器不是通用 Python 沙箱，不应作为公共代码执行服务部署。

## 模型配置

API 服务读取 `server.env.example` 中的变量，也可通过进程环境变量提供。它不使用单次决策命令的 `SYSTEMONE_*` 配置。

| 配置 | 用途 |
| --- | --- |
| `GENERATION_ENDPOINT` | 完整的 HTTP(S) Chat Completions 请求地址，例如 `https://your-provider.example/v1/chat/completions`；不能只填域名或 `/v1`，外部服务建议使用 HTTPS |
| `GENERATION_MODEL`、`GENERATION_API_KEY` | 用来生成两份代码的模型及其凭据 |
| `JEV_ENDPOINT`、`JEV_MODEL`、`JEV_API_KEY` | 可选 Jev System One 服务的完整地址、模型及独立凭据 |
| `LAYA_ENDPOINT`、`LAYA_MODEL`、`LAYA_API_KEY` | 可选 Laya 服务的完整地址、模型及服务凭据；未启用鉴权的本机服务可留空 key |
| `LAYA_CHECKPOINT` | 与 Laya 服务端实际模型匹配的本地 checkpoint 目录 |

模板中的 Jev 地址为 `https://zenmux.ai/api/v1/systemone`，模型为 `typesafe/jev-latest`。Laya 默认连接 `http://127.0.0.1:8891/v1/systemone`，使用 `multilingual`。示例连接已有的模型服务，不下载模型权重，不启动 Laya 推理服务，也不会把生成模型的密钥自动用于审核服务。

Laya 的 checkpoint 需要包含：

```text
checkpoint/
├── rl_agent_config.json
└── tokenizer/
    ├── tokenizer_config.json
    └── ...
```

`rl_agent_config.json` 中的 `max_len`、`head_max_len` 和 tokenizer 必须与服务端一致。客户端在发送前检查问题头、选项、完整输入和 mask token；可能被服务端截断的请求会被拒绝，而不是裁掉代码后继续审核。远程 Laya 地址要求 HTTPS，本机回环地址允许 HTTP。

配置后重启 API 服务。未配置生成模型时，可以先运行保存与召回步骤。

## 运行一次完整实验

以下命令在另一个 Bash 终端执行。先创建实验，选择已经配置的审核服务：

```bash
systemone_api=http://127.0.0.1:8765
systemone_run_id="$(
  curl --fail --silent --show-error \
    -H 'Content-Type: application/json' \
    -d '{"providers":["jev","laya"]}' \
    "$systemone_api/api/runs" |
    python3 -c 'import json, sys; print(json.load(sys.stdin)["id"])'
)"
```

只使用一个审核模型时，提交 `{"providers":["jev"]}` 或 `{"providers":["laya"]}`。不启用审核时，提交 `{"providers":[]}`；仍需显式执行 `review` 步骤，它不会调用任何审核服务。

按顺序执行六个步骤。每次请求等待当前步骤完成；下面的循环在 HTTP 请求失败或响应的 `error` 非空时停止：

```bash
set -o pipefail
for step in seed recall generate review verify finish; do
  curl --fail --silent --show-error -X POST \
    "$systemone_api/api/runs/$systemone_run_id/steps/$step" |
    python3 -c '
import json, sys
run = json.load(sys.stdin)
print(json.dumps({key: run[key] for key in ("id", "phase", "error")}, ensure_ascii=False))
sys.exit(1 if run["error"] else 0)
' || break
done
```

| 步骤 | 实际执行 | 记录中的证据 |
| --- | --- | --- |
| `seed` | 独立进程创建 Billing Scope，把确认的金额约定写入 SQLite Memory | 写入进程 PID、Scope、Memory revision |
| `recall` | 关闭写入进程，新进程从同一数据库调用 `context.prepare`，按准确引用回读 Memory | 不同的 PID、完整 PreparedContext、字节数、citations、Scope 隔离对照 |
| `generate` | 同一生成模型接受两次独立请求；A 只收到任务，B 追加完整 PreparedContext | 两份实际源码、输入请求、耗时及服务返回的 token 用量 |
| `review` | 每个启用的 Jev / Laya 审核相同的 A、B 两份代码，依据同一份已回读的项目规则 | `yes` / `no` / `abstain`、置信度、降级状态和用量；未启用提供方时结果为空 |
| `verify` | 两份 `amount.py` 各自在独立 Python 子进程执行相同的 10 个用例 | 每项输入、期望值、实际值或异常，以及通过数 |
| `finish` | 把实际观察结果写回 Memory，再用新进程召回 | 新 revision、结果摘要、回读内容及引用 |

成功完成后的 `phase` 为 `completed`。步骤执行失败时，响应可能仍为 HTTP 200，必须同时检查 `error` 和 `phase`；HTTP 409 表示前置步骤未完成或当前有步骤正在执行。

读取完整结果并下载报告：

```bash
curl --fail --silent --show-error \
  "$systemone_api/api/runs/$systemone_run_id" |
  python3 -m json.tool --no-ensure-ascii

curl --fail --silent --show-error \
  "$systemone_api/api/runs/$systemone_run_id/report" \
  -o ".powercontext/systemone/experiment-$systemone_run_id.json"
```

生成的两次请求使用同一模型、系统提示、当前任务和生成参数，差别仅为 B 追加了召回内容。两次调用不共享消息历史，独立测试用例不会发送给生成模型。完整请求保存在报告中，可以直接核对这项差别。

审核阶段的规则来自已经通过精确 citation 回读的完整 Memory 正文；省去的是引用元数据包装，不会裁剪规则或代码。Jev 与 Laya 接收同一组审核材料。它们的意见不会替代测试结果，也不会触发自动修复；测试执行的仍是模型实际生成的源码。

### Scope 隔离对照

示例同时创建独立的 Analytics Scope，保存采用 `ROUND_HALF_EVEN` 的相反规则。两个 Scope 没有 `context_references`。召回步骤分别准备上下文，并在各自 Scope 内按精确 citation 读取正文，检查两个项目各自使用自己的规则。

两个 Scope 都应该能读到自己的 Memory，隔离成功不意味着另一个 Scope 返回空结果。默认 Memory 的 `artifact_id` 可以相同，判断身份必须连同 `scope_id` 一起看。

### 怎样解释结果

`used_fallback=true` 表示本次判断发生降级，常见原因包括超时、服务错误、无效响应或 Laya 输入预算拒绝；这不算模型成功作答。`abstain` 且 `used_fallback=false` 表示模型主动弃权。置信度只是提供方元数据，不能证明代码正确。

测试检查舍入临界值、负数退款、普通金额和非法输入。语法超出示例支持的金额函数范围、运行超时或异常，也会记录实际失败。单次实验可以显示这次上下文对代码的影响，以及审核意见是否与测试相符；它不能推出模型的普遍准确率或长期收益。

## 记录、重试与清理

运行记录保存在 `--data-dir/<run-id>/` 下。`GET /api/status` 列出最近的实验；持有 run ID 时可通过 `GET /api/runs/<id>` 读取记录，并调用步骤接口继续。服务重启时使用相同的数据目录即可读取已有实验。

每次实验的 `run.json` 保留实际生成请求、完整 PreparedContext、精确引用、模型输出、审核结果、测试结果与接续证据；两份代码保存为 `without_memory/amount.py` 和 `with_memory/amount.py`。报告保存模型输入和输出，不保存认证请求头或 API key。

一次完整实验有两次代码生成，每个启用的审核模型另有两次判断。模型服务可能计费；报告记录服务实际返回的 token 用量和耗时，未返回的用量不会被当成零。

生成、审核和测试分别在每组完成后保存结果。失败时可重新调用尚未完成的步骤，已经保存的组不会重复执行；`used_fallback=true` 也会作为一次已完成的判断保存，不自动重试。服务在响应保存前中断或超时，请求仍可能已经计费，再次执行可能产生额外调用。修正连接或凭据后先重启服务，再继续实验；要更换生成模型，请新建实验，避免两组混用模型。

停止服务后，删除本次运行目录即可清理对应数据库、源码和报告；不再需要任何记录时，删除自己指定的整个数据目录。`.powercontext/` 和本地 `.env.systemone` 已被 Git 忽略。

## 只验证一次决策调用

需要单独排查 Jev / Laya 连接时，可以使用命令行入口。以 Jev 为例，创建独立的决策配置文件；如果 `.env_jev` 已存在，直接编辑它，跳过复制命令：

```bash
cp examples/systemone/jev.env.example examples/systemone/.env_jev
```

填写其中的 `SYSTEMONE_*` 配置，在 Bash 中加载后运行：

```bash
set -a
source examples/systemone/.env_jev
set +a
uv run --extra builtin python -m examples.systemone.decision \
  --data-dir .powercontext/systemone/decision
```

调用 Laya 时，改用 `laya.env.example` 中的 `SYSTEMONE_*` 配置，并在命令中添加 `--with 'transformers>=4,<6'` 和 `--checkpoint /absolute/path/to/served-checkpoint`。该命令只输出一次判断的 JSON，不执行完整的编码、记忆和测试闭环；API 服务的 `.env.systemone` 与这里的决策配置相互独立。`.env_jev` 已被 Git 忽略。

## 代码入口与本地验证

| 文件 | 职责 |
| --- | --- |
| `server.py` | 本地实验 API、分步执行和报告 |
| `worker.py` | 各独立进程中的 Memory 写入、召回与精确引用验证 |
| `generation.py` | 两组独立生成请求及完整请求记录 |
| `scenario.py` | 项目约定、代码执行边界与独立测试用例 |
| `adapter.py`、`laya.py` | Jev / Laya 协议适配、Runtime 降级与 Laya 输入预算检查 |
| `decision.py` | 单次决策命令行入口 |

PowerContext 通过当前仓库的 Python Runtime 直接调用；模型服务通过各自的 HTTP 接口访问。所有适配与实验代码均在示例目录内，使用同一 checkout 的最新 Runtime 契约。

```bash
uv run python -m pytest -q tests/examples/systemone tests/e2e/test_systemone_example.py
```

自动化测试覆盖本地行为及受控模型响应。确认真实服务连通、模型生成质量和审核效果，需要填写真实配置后执行 API 实验或决策命令。
