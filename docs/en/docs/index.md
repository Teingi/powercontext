---
template: docs-overview.html
title: Complete your first Codex loop
description: Install PowerContext step by step, verify cross-session Memory, and commit and receive a Handoff.
page_type: docs-overview
overview:
  intro: If you are new to PowerContext, start with the Codex step-by-step tutorial. It provides commands, expected results, and failure checks from environment setup through a local Memory and Handoff loop.
  sections:
    - title: Recommended learning path
      description: Complete the local loop first, then connect another agent host or adopt the complete work workflow.
      cards:
        - title: Codex step-by-step tutorial
          description: Install from zero, save and revise Memory, commit a Handoff, and receive its exact Revision in a new session.
          href: en/docs/tutorials/codex-quickstart/
        - title: Hand off current work
          description: Use Work Contract, Handoff, Acknowledgement, and Task Outcome for the complete task loop.
          href: en/docs/how-to/handoff-with-codex/
        - title: Continue in Claude Code
          description: Open the same project Memory from Claude Code and Codex.
          href: en/docs/how-to/configure-claude-code/
        - title: Continue in Pi
          description: Open project context in Pi with the native package.
          href: en/docs/how-to/configure-pi/
        - title: Continue in OpenClaw
          description: Open project context in OpenClaw with the memory plugin.
          href: en/docs/how-to/configure-openclaw/
        - title: Continue in OpenCode
          description: Recall and maintain project context with the native OpenCode plugin.
          href: en/docs/how-to/configure-opencode/
        - title: Load an Agent Plugin
          description: Use reusable PowerContext skills and MCP configuration in compatible agents.
          href: en/docs/how-to/configure-agent-plugin/
    - title: Understand and operate
      description: Decide what persists, configure the Server, or resolve a broken setup.
      cards:
        - title: Full-capability Quick Start
          description: Generate one validated configuration and verify extraction, vector search, and an Agent loop.
          href: en/docs/how-to/full-capability-runtime/
        - title: Core concepts
          description: Understand scopes, evidence, revisioned Artifacts, prepared context, and work continuity.
          href: en/docs/explanation/core-concepts/
        - title: Memory and Handoff
          description: Learn what belongs in durable Memory and what should remain a temporary Handoff.
          href: en/docs/explanation/memory-and-handoff/
        - title: Experience and Skill lifecycle
          description: Understand how evidence becomes a reviewed Artifact Revision and when it becomes available.
          href: en/docs/explanation/experience-and-skill-lifecycle/
        - title: Configuration
          description: Set storage, providers, interfaces, and runtime behavior.
          href: en/docs/reference/configuration/
        - title: Deploy the Server
          description: Run a persistent Server with health checks, authentication, and a safe network boundary.
          href: en/docs/how-to/deploy-server/
        - title: HTTP API
          description: Call the Server from any language and find the complete OpenAPI contract.
          href: en/docs/reference/http-api/
        - title: Review Candidates
          description: Inspect, revise, approve, or reject pending Experience and Skill proposals.
          href: en/docs/how-to/review-candidates/
        - title: Create an Experience
          description: Generate an Experience from exact evidence, review it, and verify the approved Revision.
          href: en/docs/how-to/create-and-review-experience/
        - title: Create a managed Skill
          description: Generate and review a managed Skill, then export one exact Revision to Codex.
          href: en/docs/how-to/create-and-export-skill/
        - title: Handoff Report
          description: Inspect scopes, save Handoff Revisions, and understand current report availability.
          href: en/docs/how-to/use-handoff-report/
        - title: Troubleshoot
          description: Diagnose connection, configuration, and integration problems.
          href: en/docs/how-to/troubleshoot/
---
