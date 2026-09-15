---
title: Code context validation
description: Real engine, service, host acceptance and paired results for twelve cross-module tasks.
---

# Code context validation

Current code supplementation is an opt-in code-location capability. The initial evaluation on 2026-09-16 did not
establish end-to-end efficiency or token savings. The feature remains disabled by default; these results support
neither faster task completion claims nor safely reducing test coverage.

## Environment and reproduction

Acceptance used Linux x64, Python 3.14, and CodeGraph 1.6.0 standalone. See
[Use current code in prepared context](../workflows/git-repository-understanding.md) for the archive digest and setup.
Configured OceanBase, generation, and embedding services were called directly. Credentials and configuration are
excluded from reports. Database acceptance creates a random isolated database and verifies its removal afterward.

```bash
export POWERCONTEXT_TEST_CODEGRAPH_EXECUTABLE=/srv/powercontext/tools/codegraph-linux-x64/bin/codegraph
uv run pytest tests/builtin/code tests/e2e/test_code_context.py -q
POWERCONTEXT_TEST_NATIVE_CODEX=1 uv run pytest \
  tests/e2e/real_experience_skill/test_code_context.py \
  --run-real-e2e --real-e2e-env-file .env -q -s
```

The second test needs an authenticated Codex installation. It installs an isolated plugin and copies necessary
identity configuration into a private test directory without modifying user Codex state. It exercises OceanBase,
embeddings/vector recall, HTTP, Client, MCP, the native Codex hook, and models. Codex repairs the fixture and executes
Python checks. After committing and continuing a Handoff, a fresh index and fingerprint verify later code changes.
The test then deletes the cache and reads the previously saved Source. Its report includes checks and database cleanup.

Without the real engine or `--run-real-e2e`, the corresponding acceptance tests are skipped. Passing ordinary unit
tests does not mean these real paths ran.

## Verified behavior

- Staged, unstaged, untracked, ignored, and deleted Git content; digests, path confinement, link and credential exclusion.
- Small budgets, Chinese text, long lines, malicious Markdown, complete citations, shared byte and entry limits.
- Independent queries, root/nested tests, uncertain same-name relationships, invalidation, and stale fingerprint rejection.
- Interrupted builds and reopening, concurrent refresh/query, edits after queries, timeouts, complete cache publication.
- Scope authorization before directory access; Context References and Handoff-only grants do not expose repositories.
- No Source/Artifact writes during prepare; saved code skips automatic processing while later ordinary Sources advance.
- Older Server negotiation, default Client compatibility, required MCP operation fields and read-only annotations,
  unchanged host delivery.

## Repository size and query cost

A real PowerContext source capture included 791 Python files and omitted 798 files: 795 unsupported languages and
3 exclusions. One full build took 28.476 seconds; three prepare code queries took 4.467, 2.695, and 3.684 seconds,
within the default 5-second budget. These measurements are not latency guarantees for other machines, concurrent
loads, or larger repositories. Zero parse failures does not prove a complete static graph.

## Twelve paired tasks

`scripts/code_context_tasks.py` contains an owned Python fixture covering pricing, order entry, retry delays, label
normalization, cross-file tests, and 24 unrelated modules. Tasks cover three definition locations, three call paths,
two test-discovery questions, three behavior changes, and continuation with an interface change. Each task runs
twice with code enabled and twice disabled: 48 real-model runs. Each group has eight patch runs, checked against
unchanged regression tests and separate behavior acceptance.

```bash
uv run python scripts/evaluate_code_context.py \
  --env-file .env \
  --codegraph "$POWERCONTEXT_TEST_CODEGRAPH_EXECUTABLE" \
  --output /absolute/new/code-evaluation \
  --repeats 2 --concurrency 2
```

Both conditions use `openai:qwen3.7-plus`, temperature=0, prompt, read/search/write/check tools, Memory content,
initial files, and 8000-byte budget. Every run has isolated SQLite, Scope, repository, and cache. The second repetition
reverses on/off order. Paired historical recall does not call embeddings; configured-service acceptance covers real
embeddings separately. Output is prompt-constrained JSON because the configured model does not accept a forced
output tool. Completed results are reused without new model charges; use a new output directory for fresh runs.

| Metric | Code disabled | Code enabled |
| --- | ---: | ---: |
| Runs | 24 | 24 |
| Exact definition file set | 22/24 | 23/24 |
| Exact caller set | 20/24 | 22/24 |
| Exact test file set | 20/24 | 20/24 |
| Extra callers / test files | 2 / 2 | 1 / 4 |
| Patch behavior checks | 8/8 | 8/8 |
| Regressions pass and test files unchanged | 24/24 | 24/24 |
| Median prepare time | 0.12 s | 2.24 s |
| Median Agent time | 16.14 s | 20.30 s |
| Median prepare + Agent time | 16.32 s | 22.36 s |
| Median injected bytes | 410.5 | 3166 |
| Median input tokens, completed answers | 6097.5 | 14240 |
| Median output tokens, completed answers | 826.5 | 1160 |

Definition file scoring accepts optional symbol or line suffixes; raw answers and strict-format scores are retained.
Failed answers count as incomplete in denominators. The disabled group had two invalid structured outputs; the
enabled group exceeded its request/token limit once. That run's patch passed external behavior checks, but its final
answer was incomplete. Token statistics cover the 22/23 runs with complete usage; failed calls are not counted as zero.

First definition availability starts when the model starts: zero if the initial injection contains a target file,
otherwise the time of its first read. Per-repetition medians were 4.58/5.35 seconds disabled and 2.02/0 enabled.
This measures evidence availability, not when the model understood it correctly. Agent time medians were
15.64/16.44 seconds disabled and 23.07/18.09 enabled, showing run variation. Full index cost is separate, with a
median of about 3.22 seconds in both groups. Online prepare does not implicitly build an index.

## Conclusion and limits

These tasks demonstrate delivery of code evidence and no patch regression, while increasing context, model usage,
and end-to-end time. Static test discovery still has omissions and false positives; test-count reduction is unproven.
Small owned fixtures do not establish patch success on large real projects. The PowerContext source measurement
validates deployment/query cost; it did not benchmark model-generated PowerContext patches. Evaluate candidate
relevance, budget consumption, and end-to-end benefit on representative tasks before broader rollout.
