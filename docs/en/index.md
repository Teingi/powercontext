---
template: home.html
title: PowerContext
description: Choose a supported agent and complete project Memory, cross-session recovery, and Handoff step by step.
hide:
  - navigation
  - toc
  - footer
home:
  hero:
    label: Open source · Project scoped · Local by default
    title:
      - Start a new session.
      - Keep moving.
    lead: PowerContext keeps project decisions, constraints, next steps, and work boundaries outside the chat. Choose Codex, Claude Code, DSH, OpenCode, or another supported agent and complete one inspectable cross-session loop.
    note: Multiple agents connect to one Server; Memory, automatic recall, and Handoff follow each host's actual capabilities.
    actions:
      - label: Choose your agent
        href: en/docs/tutorials/agent-quickstart/
        kind: primary
      - label: How work crosses agents
        href: en/docs/explanation/memory-and-handoff/
        kind: secondary
  continuity:
    label: One project, multiple sessions
    title: One agent stops. Work continues.
    lead: Different agents can implement, review, and validate compatibility. Handoff transfers an inspected boundary; a human decides whether to continue.
    steps:
      - title: Agent A implements
        description: Record decisions, constraints, and next steps, then assemble the objective, changes, checks, and omissions as a Handoff.
      - title: Agent B checks independently
        description: Receive the exact Revision in another host and verify its evidence and risks against the current repository.
      - title: A human decides
        description: Confirm scope, capability, and authorization, then continue, request clarification, or decline. Receipt is not completion.
  ownership:
    label: Memory and Handoff
    title:
      - Keep what lasts.
      - Hand off the work.
    lead: Memory keeps decisions, constraints, conventions, and next steps in a searchable history. Revise or retire an entry without losing the record.
    handoff: A Handoff captures the current objective, verified progress, blockers, and next action. Commit it when the work becomes a project milestone.
    result: "LOCOMO: 90.78% correct · 1.38 s p95 search latency"
    command: powercontext server run
    primary_action:
      label: Open the Agent quickstart
      href: en/docs/tutorials/agent-quickstart/
    secondary_action:
      label: Explore documentation
      href: en/docs/
---
