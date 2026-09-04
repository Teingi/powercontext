- Proposal Name: `scope_owned_prompt_management`
- Start Date: 2026-09-05
- RFC PR: [oceanbase/powercontext#0000](https://github.com/oceanbase/powercontext/pull/0000)
- Tracking Issue: [oceanbase/powercontext#1465](https://github.com/oceanbase/powercontext/issues/1465)
- Related RFCs: [RFC 0014](0014_memory_layer_design.md), [RFC 0016](0016_pydantic_ai_inference_integration.md), [RFC 0051](0051_experience_skill_artifact_families.md), [RFC 0080](0080_memory_search_reranking.md), [RFC 1396](1396_handoff_access_control.md), [RFC 1437](1437_source_artifact_rest_api.md)

# Summary

This RFC defines Scope-owned, versioned management for the operational prompts used by the built-in PowerContext
Runtime. A registered operational Prompt is stored as an Artifact with `family=prompt`; its stable `artifact_id` is a
Server-registered prompt key such as `memory.extract`. Scope remains the only ownership and isolation boundary. Agent
or user integrations first resolve their existing Scope binding and do not create a second Prompt binding model.
Here isolation means the durable persistence and resolution partition; authentication and authorization remain
separate Server concerns.

A Prompt revision has one canonical content shape: `schema_version`, `mode`, `instructions`, and
`demonstrations`. A demonstration is a typed input and expected output pair. Product surfaces may present
output-producing and no-op demonstrations as positive and negative groups, but the wire and persistence contracts do
not use informal `*_examples` fields.

The design adds no database tables and no Prompt-specific CRUD surface. It reuses the existing Artifact create,
current read, conditional replace, current-family list, and exact-revision read operations. It adds exactly two HTTP
operations: a generic Artifact revision-history list and a Prompt demonstration generator that never saves its result.
Rollback reads an immutable old revision and writes its content as a new monotonically increasing revision.

At inference time the Runtime resolves and freezes one exact Prompt selection for the operation's Scope. Editable
instructions replace only the operation's tunable guidance. Server-owned trust rules, structured input and output
schemas, credentials, model settings, tool authority, and resource limits remain outside Prompt content.

# Motivation

The built-in Runtime currently has six prompt-driven operation types and seven built-in instruction variants:

| Prompt key | Operation | Current built-in variants |
| --- | --- | --- |
| `memory.extract` | Extract durable Memory candidates from bounded evidence | `coding`, `conversation` |
| `memory.rerank` | Rerank coarse Memory search candidates | listwise reranking |
| `experience.incubate` | Propose Experience candidates from Task Outcomes | incubation |
| `experience.generate` | Generate one Experience proposal from selected evidence | explicit generation |
| `skill.generate` | Generate one managed Skill proposal | explicit generation |
| `handoff.generate` | Generate one Handoff from bounded evidence | handoff generation |

These instructions are versioned in source code and bound to structured generators when the Runtime is composed. This
is safe and deterministic for one deployment, but it cannot meet four product requirements:

1. different Scopes cannot define different extraction or generation guidance;
2. an operator cannot inspect the complete history of a Scope's prompt changes;
3. a previous configuration cannot be restored without changing deployment configuration; and
4. an inference trace cannot distinguish a built-in selection from a particular custom Prompt revision.

Putting `agent_id` or `user_id` on a Prompt record would conflict with the PowerContext ownership model. Agents and
users may be mapped to different Scopes through `ScopeBinding`, but durable state is owned by the resolved Scope. A
dedicated Prompt table and a parallel set of Prompt CRUD endpoints would duplicate the revision, head, optimistic
concurrency, lineage, and Scope isolation already provided by Artifact.

The design therefore makes operational Prompt configuration one more Scope-owned Artifact family while retaining a
small, explicit Runtime extension boundary.

# Guide-level explanation

## User model

The Dashboard presents one configuration page for the current Scope. Each registered prompt key has two modes:

- **Auto** uses the built-in instructions selected by the deployed Runtime; and
- **Custom** uses Scope-owned instructions and demonstrations.

For `memory.extract`, a custom editor can show three sections:

1. extraction instructions;
2. positive demonstrations whose expected output contains one or more Memory candidates; and
3. negative demonstrations whose expected output contains no candidates.

All demonstrations are persisted in one ordered `demonstrations` array. The Prompt Definition for the operation
classifies a valid expected output as output-producing or no-op when a UI needs grouping. Classification is derived
from the typed output and is not a second persisted policy field.

For example, the stored content is:

```json
{
  "schema_version": "powercontext.prompt.v1",
  "mode": "custom",
  "instructions": "Keep durable testing preferences and verified failure lessons. Ignore transient requests.",
  "demonstrations": [
    {
      "input": {
        "evidence": [
          {
            "evidence_id": "source-1",
            "text": "Before every release I run the core smoke test; it takes about 20 minutes."
          }
        ],
        "current_entries": []
      },
      "expected_output": {
        "candidates": [
          {
            "kind": "preference",
            "text": "The user runs the core smoke test before every release; it takes about 20 minutes.",
            "evidence_ids": ["source-1"],
            "intent": "add"
          }
        ]
      }
    },
    {
      "input": {
        "evidence": [{"evidence_id": "source-2", "text": "Please send me the code from the previous message."}],
        "current_entries": []
      },
      "expected_output": {"candidates": []}
    }
  ]
}
```

`input` and `expected_output` must validate against the registered schemas for `memory.extract`. The Server does not
accept free-form demonstration labels as a substitute for a valid expected output.

## Scope selection

A Prompt is addressed as:

```text
ArtifactAddress(
  scope_id,
  ArtifactRef(family="prompt", artifact_id=prompt_key, revision=revision),
)
```

The complete identity of a Prompt revision therefore includes the Scope. The same `memory.extract` key may have
different revisions in two Scopes without sharing state.

An Agent-facing or user-facing integration performs this sequence:

```text
Agent or user identity
        |
        v
existing ScopeBinding resolution
        |
        v
one resolved scope_id
        |
        v
Scope-owned Prompt head
```

There is no implicit parent-Scope inheritance, cross-Scope `latest`, or Agent/User fallback. A copied configuration is
a new Artifact revision in the destination Scope and has an independent future lifecycle.

## Create and update

The existing generic Artifact API creates a custom Prompt head:

```http
POST /v1/scopes/project:payments/artifacts
Content-Type: application/json
```

```json
{
  "family": "prompt",
  "prompt_key": "memory.extract",
  "content": {
    "schema_version": "powercontext.prompt.v1",
    "mode": "custom",
    "instructions": "Keep durable payment debugging decisions and verified failure lessons.",
    "demonstrations": []
  }
}
```

The Server uses `prompt_key` as `artifact_id` and commits revision 1. Unknown or disabled prompt keys are rejected.
Callers cannot allocate arbitrary operational Prompt identities.

Updating a Prompt uses the existing conditional replacement operation:

```http
PUT /v1/scopes/project:payments/artifacts/prompt/memory.extract
If-Match: "revision:4"
Content-Type: application/json
```

The body contains the complete replacement `content`. A successful request commits revision 5; revision 4 remains
immutable and readable. Concurrent replacement with a stale ETag fails with `412 Precondition Failed`.

Switching back to Auto is also a revisioned change:

```json
{
  "content": {
    "schema_version": "powercontext.prompt.v1",
    "mode": "auto",
    "instructions": "",
    "demonstrations": []
  }
}
```

When no Prompt Artifact exists, behavior is also Auto. Persisting an Auto revision is useful when an operator wants the
history to show an explicit return to the built-in selection.

## Generate demonstrations

The only Prompt-specific endpoint generates editable demonstration suggestions:

```http
POST /v1/scopes/project:payments/prompts/memory.extract/demonstrations
Content-Type: application/json
```

```json
{
  "instructions": "Keep durable testing preferences and verified failure lessons.",
  "demonstration_count": 6
}
```

The response contains exactly six schema-valid demonstrations:

```json
{
  "prompt_key": "memory.extract",
  "demonstrations": [
    {
      "input": {"evidence": [], "current_entries": []},
      "expected_output": {"candidates": []}
    }
  ]
}
```

The shortened array above illustrates the item shape only. The endpoint does not create or replace an Artifact,
advance a head, or silently combine its output with current content. The caller reviews and edits the suggestions, then
uses the normal Artifact create or replace operation to save them.

## Inspect history and roll back

The generic revision-history endpoint lists immutable revisions newest first:

```http
GET /v1/scopes/project:payments/artifacts/prompt/memory.extract/revisions?limit=50
```

Each item includes the exact identity, content digest, and lineage identities. Full content is retrieved through the
existing exact-revision operation:

```http
GET /v1/scopes/project:payments/artifacts/prompt/memory.extract/revisions/2
```

Rollback is deliberately not a history rewrite and does not require a third endpoint:

1. read the old exact revision;
2. read the current head and ETag;
3. replace the current head with the old revision's `content` and the current ETag; and
4. receive a new revision whose content digest matches the restored revision.

For example, restoring revision 2 while revision 5 is current creates revision 6. Revisions 2 through 5 remain
readable. Generic request audit identifies the actor and request; equality with the restored content is visible through
the content digest. The Server never moves the head pointer backward.

# Reference-level explanation

## Terminology and boundaries

| Term | Meaning |
| --- | --- |
| Operational Prompt | Scope-owned configuration for one registered built-in inference operation |
| Prompt key | Stable Server-registered operation identifier used as the Prompt Artifact ID |
| Prompt Definition | Server-owned typed contract for a prompt key |
| Prompt revision | One immutable `family=prompt` Artifact revision in one Scope |
| Built-in selection | Server-shipped default guidance and version used by Auto mode |
| Compiled prompt | Invariant instructions, selected guidance, demonstrations, and structured schema contract used for one call |

An operational Prompt is not ordinary user input, Source evidence, a managed Skill, a model credential, or an
arbitrary system message. A managed Skill tells an Agent when and how to perform a reusable capability. An operational
Prompt tunes one fixed PowerContext inference operation without adding tools or authority.

RFC 1396 reserved a future `family=prompt` lifecycle for reusable parameterized task templates and classified current
internal generation prompts as Server-only configuration. This RFC changes the latter boundary only: registered
operational prompts may be customized by Scope-owned Prompt Artifacts. It does not introduce the reusable task-template
lifecycle, approval state, `prompt.use`, or exact Prompt sharing described as future work in RFC 1396.

## Prompt Definitions

The Server registers Prompt Definitions during Runtime composition. Registration is fixed for the lifetime of the
composed Runtime. Each Definition provides:

```python
class PromptDefinition(Protocol):
    key: str
    definition_version: str
    input_type: type[BaseModel]
    output_type: type[BaseModel]
    builtin_version: str
    invariant_instructions: str
    default_instructions: str

    def is_noop_output(self, output: BaseModel, /) -> bool: ...
```

The initial registry contains exactly the six keys listed in Motivation. `memory.extract` retains the deployment's
validated `coding` or `conversation` profile as its Auto selection, so the six logical operations still account for
seven current built-in instruction variants.

The registry, not persisted Prompt content, owns:

- structured input and output types;
- invariant evidence, safety, secret, citation, and identity rules;
- built-in selection and built-in version;
- model and request settings;
- input and output size limits;
- demonstration no-op classification; and
- compatibility with a Prompt content schema version.

Two Definitions cannot register the same key. An unknown key, duplicate key, incompatible Definition, or missing
built-in selection fails Runtime composition rather than being accepted as untyped configuration.

## Prompt Artifact content

`PromptContent` is strict and rejects unknown fields:

```python
class PromptDemonstration(BaseModel):
    input: JsonValue
    expected_output: JsonValue


class PromptContent(BaseModel):
    schema_version: Literal["powercontext.prompt.v1"]
    mode: Literal["auto", "custom"]
    instructions: str
    demonstrations: tuple[PromptDemonstration, ...]
```

The following validation rules are part of the public contract:

- all four fields are required;
- `auto` requires empty `instructions` and an empty `demonstrations` array;
- `custom` requires instructions with at least one non-whitespace character;
- instructions are trimmed NFC text and are limited to 32,768 characters;
- demonstrations preserve caller order and are limited to 50 items;
- every `input` and `expected_output` validates strictly against the Prompt Definition's registered types;
- each demonstration is limited to 64 KiB of canonical JSON; and
- the complete canonical Prompt content is limited to 256 KiB.

Demonstrations contain desired behavior only. A negative demonstration is represented by an input whose valid
`expected_output` is the operation's no-op result, not by storing an intentionally wrong output. This prevents the
compiler from teaching the model invalid behavior and keeps the representation valid across all prompt keys.

## Persistence and identity

No database tables or Prompt binding records are added. Persistence reuses:

| Existing storage | Prompt use |
| --- | --- |
| `pc_artifacts` | Immutable Prompt content by `(scope_id, prompt, prompt_key, revision)` |
| `pc_artifact_heads` | Current Prompt revision by `(scope_id, prompt, prompt_key)` |
| existing Artifact lineage tables | Exact Artifact inputs when Prompt configuration participates in generated lineage |
| existing system provenance Source | Canonical create or replace request provenance |

The Prompt family adds a family-owned writer and registered content model to the existing Artifact repository. It does
not add Prompt-specific repositories, head logic, revision counters, or transactions.

Prompt keys use the existing Artifact ID syntax and are additionally allow-listed by the Runtime registry. The initial
keys are globally stable wire vocabulary. Renaming a key is a compatibility change; aliases require an explicit future
migration and must not silently merge histories.

RFC 1437 generates Artifact IDs and fixes the Create outer shape to `family` plus `content` for its four families,
with Handoff as a Server-known singleton exception. This RFC narrowly amends that rule for the new Prompt family.
`CreatePromptArtifactRequest` adds the required top-level `prompt_key`; the family writer validates it against the
fixed registry and uses it as `artifact_id`. Existing family request shapes do not change. The caller selects a known
operation but still cannot allocate an arbitrary Artifact ID. Hiding this resource selector inside Prompt content
would duplicate identity and make replacement content depend on the Create transport shape.

## Revision semantics

The normal Artifact guarantees apply:

- create commits revision 1 and fails with `409 Conflict` when the key already has a head in the Scope;
- replace commits one complete next revision atomically;
- revisions are immutable positive integers and never reused;
- the head advances only after content, lineage, and derived state are durable;
- `If-Match` is required for replacement;
- an exact-revision read never resolves `latest`; and
- there is no physical delete or history rewrite in this RFC.

Replacing a Prompt with canonically identical content is allowed and produces another revision. This preserves an
explicit operator action and keeps rollback behavior uniform. Clients may compare `content_digest` before writing when
they want to avoid a no-op revision.

## Runtime resolution and compilation

Prompt resolution occurs per inference operation after `scope_id` is fixed and before the first model request. It does
not occur only once at Runtime composition.

The resolver returns one immutable value:

```python
class ResolvedPrompt(BaseModel):
    key: str
    definition_version: str
    selection: Literal["built_in", "artifact"]
    artifact: ArtifactRef | None
    selected_version: str
    compiled_digest: str
    instructions: str
    demonstrations: tuple[PromptDemonstration, ...]
```

Resolution follows this algorithm:

1. select the registered Prompt Definition for the operation;
2. read the current `family=prompt` head for `(scope_id, prompt_key)`;
3. use the built-in selection when no head exists or its mode is Auto;
4. otherwise validate the custom revision against the selected Definition;
5. compile Server-owned invariant instructions, the selected guidance, demonstrations, and the structured output
   contract in a fixed order;
6. compute a canonical compiled digest; and
7. freeze the result for the complete logical operation, including retries.

A head change during an in-flight extraction, rerank, generation, or Handoff operation affects only the next logical
operation. A Memory flush freezes its Prompt before processing its bounded Source window. Existing Memory and other
Artifacts are not automatically regenerated when a Prompt head changes.

The compiler never concatenates custom text ahead of higher-priority invariants. If the inference adapter supports
typed example messages, it emits demonstrations through that mechanism. Otherwise it serializes them with a
Server-owned delimiter and canonical JSON encoding that user text cannot terminate or reinterpret.

Implementations may cache compiled prompts by `(definition_version, selection identity, compiled_digest)`. They must
invalidate head lookup by the same consistency rules as Artifact current reads and must never use a head from another
Scope.

## Provenance and observability

Every inference span records:

- `powercontext.prompt.key`;
- `powercontext.prompt.selection` as `built_in` or `artifact`;
- exact Artifact family, ID, and revision when custom;
- built-in and Definition versions;
- compiled prompt digest; and
- demonstration count.

Prompt bodies and demonstration bodies are not logged or emitted as metric labels.

When a durable generated Artifact already records Artifact inputs, its lineage includes the exact custom Prompt
`ArtifactRef` used for generation. This is configuration lineage, not factual evidence: it grants no transitive read,
does not satisfy a Source citation requirement, and does not allow Prompt instructions to support a factual claim.
Built-in selections have no synthetic ArtifactRef and remain identifiable through the recorded built-in version and
compiled digest. Ephemeral outputs such as Memory rerank decisions record the same identity only on the operation
trace.

## HTTP contract

The complete v1 HTTP surface is:

| Status | Method and path | operationId | Purpose |
| --- | --- | --- | --- |
| Existing, extended | `POST /v1/scopes/{scope_id}/artifacts` | `create_artifact` | Accept `family=prompt` and a registered `prompt_key` |
| Existing, extended | `GET /v1/scopes/{scope_id}/artifacts/prompt` | `list_artifacts` | List current Prompt heads in the Scope |
| Existing, extended | `GET /v1/scopes/{scope_id}/artifacts/prompt/{prompt_key}` | `get_artifact` | Read the current Prompt head and ETag |
| Existing, extended | `PUT /v1/scopes/{scope_id}/artifacts/prompt/{prompt_key}` | `replace_artifact` | Commit a complete next Prompt revision |
| Existing, extended | `GET /v1/scopes/{scope_id}/artifacts/prompt/{prompt_key}/revisions/{revision}` | `get_artifact_revision` | Read one exact immutable revision |
| **New** | `GET /v1/scopes/{scope_id}/artifacts/{family}/{artifact_id}/revisions` | `list_artifact_revisions` | List immutable revisions for any Artifact family |
| **New** | `POST /v1/scopes/{scope_id}/prompts/{prompt_key}/demonstrations` | `generate_prompt_demonstrations` | Generate validated suggestions without saving |

The new endpoint count is exactly two. There is no Prompt-specific list, get, create, update, rollback, publish,
validate, preview, activate, or delete endpoint.

The additional Create union member is:

```json
{
  "family": "prompt",
  "prompt_key": "memory.extract",
  "content": {
    "schema_version": "powercontext.prompt.v1",
    "mode": "custom",
    "instructions": "Keep durable preferences.",
    "demonstrations": []
  }
}
```

`prompt_key` is present only on Prompt Create. Replace selects the same identity from the path and continues to accept
only `content`, consistent with RFC 1437. The generated system Source is target-bound to the resulting
`artifact_id=prompt_key` and revision using the existing lineage-only mechanism.

`list_artifact_revisions` accepts the existing bounded `limit` and opaque `cursor` pagination model. It orders by
revision descending and returns an `ArtifactRevisionPage` whose items contain `scope_id`, `family`, `artifact_id`,
`revision`, `sources`, `artifacts`, and `content_digest`; it omits content. A cursor is bound to the complete Scope,
family, Artifact ID, authorization constraint, filter, and snapshot boundary.

`generate_prompt_demonstrations` accepts this strict request:

```json
{
  "instructions": "non-blank custom instructions",
  "demonstration_count": 6
}
```

`demonstration_count` is an integer from 1 through 20. The response returns the path `prompt_key` and exactly that
many typed demonstrations. The Server validates and normalizes model output before responding. It retries only within
the configured inference request budget; an incomplete or invalid result fails the whole request and is never saved.

## Error and concurrency semantics

| Condition | HTTP result |
| --- | --- |
| Scope, Prompt head, or exact revision is not visible or does not exist | `404 Not Found` |
| Prompt head already exists during create | `409 Conflict` |
| Missing `If-Match` on replace | `428 Precondition Required` |
| Stale or mismatched `If-Match` | `412 Precondition Failed` |
| Unknown prompt key, invalid mode/content, schema-invalid demonstration, or unsupported family/key combination | `422 Unprocessable Entity` |
| Invalid or expired pagination cursor | existing `400` or `410` cursor semantics |
| Required inference provider is unavailable for demonstration generation | `503 Service Unavailable` |
| Provider output remains invalid within the request budget | `500 Internal Server Error` with a stable public error code |

Errors do not echo Prompt or demonstration bodies. A caller cannot distinguish a hidden Scope or Prompt from a missing
one through response details.

## Authorization and trust boundary

Operational Prompt configuration changes the behavior of every compatible inference operation in a Scope. Under the
access-control model, current read, history list, and exact read require the corresponding Scope read authority;
create, replace, and demonstration generation require `scope.admin`. The legacy static bearer continues to map to its
configured administrative Principal. A family-specific writer enforces this stronger mutation rule instead of
weakening all generic Artifact writes.

The Runtime's internal use of the current Scope Prompt is part of the already-authorized domain operation. It is not an
implicit exact-resource share. Operational Prompt revisions are not shareable through `prompt.user` in this RFC, and
the Prompt access profile advertises no grantable exact roles for them.

Custom Prompt content is untrusted configuration. It cannot:

- override evidence-as-data treatment, citation requirements, secret exclusion, or identity allocation rules;
- change the registered input or output schema;
- select a model, provider, credential, header, timeout, retry budget, or token budget;
- enable tools, network, filesystem access, publication, or another capability;
- resolve or reference another Scope implicitly; or
- cause generated demonstrations to be saved without an explicit Artifact write.

The demonstration generator treats supplied instructions as data within a Server-owned meta-prompt. Generated
examples undergo the same secret and size validation as manually supplied demonstrations.

## Non-HTTP surfaces

The Dashboard uses the HTTP operations above. Its Agent or user selector resolves to a Scope before it reads or writes
Prompt state. The three-section editor is a presentation of one `PromptContent`; it is not another API contract.

The Python Runtime gains the Prompt Definition registry, Scope Prompt resolver, compiler, and family writer described
in this RFC. Public Python callers may use the existing generic Artifact client for persistence. There is no new MCP
tool, CLI command, or host-specific configuration file in v1.

## Compatibility and migration

This design is backward compatible for Scopes that have no Prompt Artifact. They continue to use the exact built-in
selection chosen today, including the configured `memory_extraction_profile` and rerank enablement.

Implementation requires:

1. splitting each current instruction constant into immutable invariants and replaceable default guidance without
   changing Auto-mode compiled behavior;
2. registering the six Prompt Definitions;
3. adding `prompt` to the base Artifact family contract, generated HTTP models, mapper, repository type registry, and
   family management writer registry;
4. resolving Prompt state per Scope at the six inference entry points;
5. adding the two OpenAPI operations and regenerating checked-in HTTP sources; and
6. emitting the Prompt identity and digest in tracing and generated Artifact lineage where applicable.

No SQL migration or content backfill is required. Existing deployments need no Prompt rows. An implementation must
prove that Auto mode compiles to behavior-equivalent instructions before custom mode is enabled.

## Validation requirements

The implementation is complete only when tests demonstrate:

- two Scopes can hold different current revisions for the same prompt key without leakage;
- an Agent or user binding resolves to the expected Scope before Prompt lookup;
- absent and explicit Auto configurations preserve current built-in behavior;
- custom instructions and typed demonstrations reach the correct generator only;
- all six registered keys resolve, and unknown keys fail closed;
- a revision is immutable, history pagination is stable, and exact reads do not follow the head;
- stale replacement fails and a rollback creates a new revision without deleting history;
- a Prompt changed during an in-flight operation is used only by the next operation;
- generated demonstrations validate against the registered input/output schemas and are never persisted implicitly;
- custom content cannot change invariant instructions, structured schemas, model settings, tools, or authority;
- traces contain exact Prompt identity or built-in version and digest without Prompt bodies; and
- the OpenAPI contract, generated HTTP sources, unit tests, and at least one real Runtime end-to-end scenario pass.

# Drawbacks

Adding `prompt` to Artifact expands the meaning of Artifact lineage beyond factual evidence to include an explicitly
classified configuration input. Consumers must continue to distinguish configuration lineage from Source citations.

Per-operation Prompt resolution adds a repository read or cache validation to inference paths. Correct caching is
Scope-sensitive and must not trade isolation for fewer reads.

Custom guidance can reduce output quality even when it remains within hard invariants and schemas. Version history and
rollback limit the operational impact but cannot guarantee that a custom prompt is useful. The demonstration generator
also consumes inference capacity and may fail when the provider is unavailable.

The initial design deliberately lacks drafts and approval. A `scope.admin` change becomes current immediately after
the Artifact transaction commits.

# Rationale and alternatives

## Reuse Artifact rather than add Prompt tables

Artifact already provides the required Scope key, immutable revisions, current head, atomic replacement, ETag
concurrency, content digest, lineage, and exact reads. Reimplementing these semantics in `prompts`, `prompt_versions`,
and `prompt_bindings` would add synchronization and migration risk without creating a distinct domain guarantee.

## Reuse generic CRUD rather than add Prompt CRUD

Prompt-specific create, get, update, history, rollback, and delete endpoints would duplicate the Artifact contract.
Only history listing is missing generically, and every Artifact family benefits from it. Demonstration generation is a
real Prompt-specific action and therefore receives the only Prompt-specific endpoint.

## Scope ownership rather than Agent or user ownership

PowerContext state is isolated by Scope. Agent and user identity are integration and authorization concerns. Reusing
ScopeBinding keeps one durable ownership model and allows two Agents to share Prompt behavior intentionally by sharing
a Scope, or to differ by using separate Scopes.

## Typed demonstrations rather than example strings

Free-form positive and negative strings do not state the complete model input/output contract and are hard to validate.
Typed `input` and `expected_output` pairs can be compiled deterministically, tested, and reused across all six
operations. No-op expected output represents a negative case without teaching an invalid answer.

## New revision rather than moving the head backward

A backward-moving head would erase the sequence of operator decisions and create ambiguous cache and audit behavior.
Copying old content into a new conditional replacement preserves monotonic history and uses the same failure semantics
as every update.

## Alternatives not selected

- **Deployment-only prompt configuration:** cannot vary by Scope or provide Scope-local history.
- **A raw prompt field on every inference request:** weakens authorization, audit, caching, and reproducibility.
- **Parent-Scope inheritance:** makes effective configuration depend on a moving graph and complicates isolation.
- **A mutable cross-Scope Prompt reference:** lets one Scope change another Scope's behavior without a local revision.
- **A Prompt DSL or variables:** increases compiler and injection complexity before concrete use cases require it.
- **Draft, review, and activation workflows:** duplicate Candidate/Review concepts and are not needed for the first
  administrative vertical slice.
- **A dedicated rollback endpoint:** adds an action whose safe semantics are already expressed by exact read plus
  conditional replacement.

Doing nothing leaves operational prompts fixed at deployment composition and forces customers to fork Runtime code or
run separate deployments for different prompt behavior.

# Prior art

PowerContext's Memory, Experience, Skill, and Handoff families already use immutable Artifact revisions and current
heads. The base Artifact REST API already exposes create, current read, conditional replacement, family list, and exact
revision read. This RFC applies those established primitives to operational Prompt configuration rather than creating
a parallel management system.

The current source code also versions every built-in instruction string. Those versions remain useful as the identity
of Auto selections and as part of the compiled-prompt trace.

# Unresolved questions

There are no unresolved questions required to implement this RFC. The following subjects are explicit non-goals and
require later design work if demanded:

- reusable parameterized task Prompt Artifacts and `prompt.use` sharing;
- draft, approval, scheduled activation, or staged rollout;
- parent-Scope inheritance or organization-level defaults;
- automatic evaluation, quality scoring, or A/B traffic allocation;
- cross-Scope import and publication workflows; and
- a general Prompt templating language.

# Future possibilities

A later RFC may add Prompt evaluation cases kept separate from demonstrations, compare revisions against a stable
dataset, and gate activation on explicit quality thresholds. Another may define reusable task Prompt packages and
least-privilege `prompt.use` sharing without changing the operational Prompt identity introduced here.

Organization defaults, scheduled activation, or percentage rollout can be layered above Scope-local immutable
revisions if their ownership and precedence rules are specified explicitly. None of these extensions requires changing
the v1 rule that an inference operation freezes one exact effective Prompt selection before its first model request.
