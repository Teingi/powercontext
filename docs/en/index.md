---
template: home.html
title: PowerContext
description: Start locally and complete a Codex project Memory, cross-session recovery, and Handoff loop step by step.
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
    lead: PowerContext keeps project decisions, constraints, next steps, and work boundaries outside the chat. Follow the tutorial to complete one inspectable cross-session loop in Codex.
    note: No inference model required; local SQLite is enough for explicit Memory and Handoff.
    actions:
      - label: Follow the Codex tutorial
        href: en/docs/tutorials/codex-quickstart/
        kind: primary
      - label: How context carries over
        href: en/docs/explanation/memory-and-handoff/
        kind: secondary
  continuity:
    label: One project, multiple sessions
    title: Record. Hand off. Continue.
    lead: Save durable knowledge, commit an inspected work boundary, and let a new session verify the exact Revision.
    steps:
      - title: Save Memory
        description: Explicitly record project decisions, constraints, and next steps with a citation for each entry.
      - title: Commit a Handoff
        description: Have Codex inspect the objective, worktree, checks, and omissions to create a traceable milestone.
      - title: Receive in a new session
        description: Read the exact Revision, then verify it against the current repository, capabilities, and authorization.
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
      label: Start the step-by-step tutorial
      href: en/docs/tutorials/codex-quickstart/
    secondary_action:
      label: Explore documentation
      href: en/docs/
---
