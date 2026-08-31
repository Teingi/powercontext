---
template: home.html
title: PowerContext
description: 从本地安装开始，逐步跑通 Codex 的项目 Memory、跨会话恢复与 Handoff。
hide:
  - navigation
  - toc
  - footer
home:
  hero:
    label: 开源 · 项目级 · 默认本地
    title:
      - 换一个会话，
      - 项目继续向前。
    lead: PowerContext 把项目决定、约束、下一步和任务边界保存在对话之外。跟着分步教程，先在 Codex 中完成一次可检查的跨会话闭环。
    note: 无需推理模型；本地 SQLite 即可跑通显式 Memory 和 Handoff。
    actions:
      - label: 跟着 Codex 教程操作
        href: zh/docs/tutorials/codex-quickstart/
        kind: primary
      - label: 了解上下文如何延续
        href: zh/docs/explanation/memory-and-handoff/
        kind: secondary
  continuity:
    label: 同一项目，多个会话
    title: 从记录，到交接，再继续。
    lead: 保存长期知识，提交经过检查的工作边界，再让新会话按精确 Revision 核对并继续。
    steps:
      - title: 保存 Memory
        description: 明确记录项目决定、约束和下一步，并保留每条内容的 citation。
      - title: 提交 Handoff
        description: 让 Codex 检查目标、工作区、验证结果和遗漏，形成可追踪的任务里程碑。
      - title: 在新会话接收
        description: 按 exact Revision 读取 Handoff，再用当前仓库、能力和授权重新核对。
  ownership:
    label: Memory 与 Handoff
    title:
      - 留下长期信息，
      - 交接当前工作。
    lead: Memory 保存决定、约束、约定和下一步，并保留可检索的历史。修订或停用条目，不会丢失记录。
    handoff: Handoff 记录当前目标、已验证进展、阻塞项和下一步行动。工作形成项目里程碑后再提交。
    result: "LOCOMO：答对率 90.78% · 搜索 p95 延迟 1.38 秒"
    command: powercontext server run
    primary_action:
      label: 开始分步教程
      href: zh/docs/tutorials/codex-quickstart/
    secondary_action:
      label: 浏览文档
      href: zh/docs/
---
