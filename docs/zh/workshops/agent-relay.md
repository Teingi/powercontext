# 实验：Agent 接力——聊天清空后还能继续吗？

在上海外滩大会 Workshop 中，参与者使用 PowerContext，
接力完成上海三日旅行方案。
实验主线约 15 分钟；完成接力后，可继续体验 Experience 与 Skill 拓展。

**完整教材与代码：[agent-relay.ipynb](../../../examples/workshops/agent-relay/agent-relay.ipynb)。**
安装、启动、配置、体验、原理与自由探索都在一个 Notebook 内；上传这一份 `.ipynb` 即可。

## 参与者体验

| 部分 | 参与者做什么 | 观察什么 |
| --- | --- | --- |
| 准备环境 | 安装发布包、在 Notebook 填写三项模型配置、启动本地 Server | 安装显示 `Dependencies ready`，模型请求成功，服务显示 `PowerContext ready` |
| 第一棒 | 自拟旅行代号和个人要求，让规划师做前两天 | 具体方案已保存，第三天和费用表仍是待办 |
| 清空对照 | 用没有旧聊天、没有恢复内容的新会话询问原任务 | 模型的真实回答是否有依据 |
| 第二棒 | 从交接恢复，将预算改为 2600 元、第二天改为雨天 | 个人要求保留，新的条件生效 |
| 第三棒 | 行程检查员读取交接，补上剩余工作 | 方案延续、第三天和费用补齐 |
| 原理 | 查看实际 Memory、Handoff 和会话记录 | 要求与进度的区别，以及同一任务如何持续推进 |
| 经验与 Skill（可选） | 填写实际观察，提交并审核经验与 Skill，再由新会话读取应用 | pending 与正式版本的区别，经验依据、操作步骤及实际使用记录 |

教材采用“环境准备 → 先体验 → 代码拆解 → 经验与 Skill 拓展”的结构，编排参考
[最小 AI 编程智能体 — 从零理解 Agent Loop](https://www.modelscope.cn/gallery/donggua0311/agent_loop_demo)。
完整 Agent 定义直接放在 Notebook 内，体验时可先折叠，理解原理时再展开。
旅行方案使用自然语言输出，参与者可以直接阅读并判断。
每一棒前后穿插 PowerContext 的能力讲解：第一棒说明 Memory、Source 与 Handoff 的用途，
清空对照说明保存与恢复的区别，第二棒说明要求修订，第三棒说明进度和待办如何帮助接手者继续。
教材通过文字和对照表解释三类记录、Memory 修订和保存恢复流程。
原理部分用实际记录对应关键调用，并解释 Scope 的任务组织作用；完整教材与代码均在同一个 Notebook 中。

## 实现与接续边界

主接力中，Memory 保存有效要求；Handoff 保存已生成方案和下一步。
预算变化通过修订同一条 Memory 生效，方案保存为 Source，再准备并提交 Handoff。
提交后读取确认，接收方按精确引用读取交接，并检查对应 Memory 仍然有效。

| 操作 | 公开 HTTP API |
| --- | --- |
| 保存要求 | `POST /v1/memory/remember` |
| 修订要求 | `POST /v1/memory/entries/revise` |
| 读取要求 | `POST /v1/memory/entries/get` |
| 保存方案 | `POST /v1/sources/content` |
| 准备交接 | `POST /v1/work/handoffs/prepare-current` |
| 提交交接 | `POST /v1/handoff/commit` |
| 恢复交接 | `POST /v1/handoff/continue` |
| 提交经验候选 / 读取经验 | `POST /v1/experience/propose`、`POST /v1/experience/get` |
| 提交 Skill 候选 / 读取 Skill | `POST /v1/skill/propose`、`POST /v1/skill/get` |
| 读取 / 批准候选 | `POST /v1/artifact-candidates/get`、`POST /v1/artifact-candidates/approve` |

接口以 [OpenAPI 合同](../../../openapi/powercontext.yaml) 为准。
保存与恢复由实验代码明确调用，模型负责规划、修改和检查，不把模型的口头承诺当作持久保存。

每个 Agent 实例有自己的角色与聊天列表。对照不携带旧消息或恢复材料；接收方通过 PowerContext 读取资料。
本地 `*-answer.json` 只用于重试与人工核对，恢复方不会将其作为上下文来源。
同一实验的 Scope 自动创建并记录，参与者不填写 Scope ID 或服务 Token。

Notebook 中的 A、B 是职责不同、历史独立的 Agent 实例。第二棒后可以重启 Kernel，重新运行环境和 Agent 定义，
直接从第三棒继续；这验证跨会话持久化，不宣称跨厂商宿主的互操作验证。

## 环境与分发

需要 Linux / Python 3.11+ 的 CPU Notebook 环境及模型 API Key。
安装固定的 `powercontext[cli,server]==1.0.0` 发布包，服务仅监听本实例的回环地址。
在 Notebook 配置格中填写 `RELAY_MODEL_BASE_URL`、`RELAY_MODEL` 和 `RELAY_MODEL_API_KEY`。
模型名和接口地址已提供默认值，Key 留空；配置不读取 `.env` 或环境变量。
Key 会随当前 Notebook 保存，发布原文件前需清空 Key 和执行输出。

默认数据库为 SQLite，不需要 Embedding、GPU 或额外生成模型。
OceanBase PowerContext 是产品名，默认示例不能称为 OceanBase 数据库存储验证。
在环境的持久工作区 `/mnt/workspace/` 中保留 Notebook 及其 `.powercontext/` 数据；实例停止后重新运行启动单元格。

方案和接续记录直接在 Notebook 中展示；继续原任务需要保留原实例的数据库和实验目录。

## 验收与扩展

会话记录展示四次独立会话、旧聊天条数和实际恢复来源。行程本身由参与者核对：
个人要求是否落实，雨天安排是否合理，费用合计是否符合新预算，第三天是否补齐，已有安排的变化是否有理由。
不把生成结束当成验收通过。

第 4 部分将同一次旅行接力延伸到 Experience 与 Skill。参与者填写实际观察与可复用经验，
Notebook 将观察和当前工作保存为 Source，以此和精确 Handoff 引用提交 Experience Candidate。
参与者查看候选内容、证据与版本后显式批准，再从正式 Experience 整理 Skill 的适用场景、操作步骤和验证项。
Skill 同样经过候选审核，引用正式 Experience 作为依据。

两者通过显式 `propose` 提交结构化内容，不依赖 Server 端模型生成。Notebook 在审核请求中携带所查看的
`expected_version`；服务中的候选发生修订时，必须重新查看再审核。已提交候选与审核状态可在重启后读回。

新 Agent 通过 `use_skill()` 从 PowerContext 精确读取已审核 Skill，将步骤和验证项加入本次模型输入，
再恢复旅行交接并处理新的预算或雨天条件。全过程只需这一份 Notebook，不创建外部 Skill 目录。
记录显示实际 Skill 引用与旧聊天条数；参与者核对变更影响表、个人要求、行程和费用，再读取更新后的 Memory。
批准不会自动执行 Skill，读取与使用记录也不等于证明 Skill 提升了模型效果。

组织者发布前须验证包源可安装 1.0.0，并用另一账号从实际 Notebook 入口完成复制、运行、重启接续和追加要求。
模型并发与额度按实际人数彩排。本地开发版验证不能代替发布包或运行平台验收。
现场安排与故障处理见 [讲师手册](../../../examples/workshops/agent-relay/FACILITATOR.md)。
