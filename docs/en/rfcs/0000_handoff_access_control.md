- Proposal Name: `handoff_access_control`
- Start Date: 2026-08-30
- Status: Draft
- RFC PR: [oceanbase/powercontext#0000](https://github.com/oceanbase/powercontext/pull/0000)
- Tracking Issue: [oceanbase/powercontext#1395](https://github.com/oceanbase/powercontext/issues/1395)
- Related RFCs: [RFC 0011](0011_remote_access_architecture.md), [RFC 0048](0048_handoff_artifact.md),
  [RFC 0082](0082_handoff_report.md), and [RFC 1223](1223_human_agent_work_continuity.md)

# Summary

This RFC defines an independent Access Control boundary for the PowerContext Server and uses Handoff as the first
resource-level authorization profile. It answers one concrete question: when user A transfers a Handoff to user B,
what may B see and do, and how can that access be revoked and audited?

Handoff content does not store users, roles, or ACLs. `scope_id` remains the stable business partition for a
Workstream; it is not a user identity, tenant, role, or security boundary. Authentication and authorization happen at
the Server. Authentication establishes a trusted Principal. A Policy Enforcement Point (PEP) sends that Principal,
the action, and the resource to a replaceable `AuthorizationProvider` before it calls the existing Runtime application
service.

```text
Identity Provider or static credential
                |
                v
        Authenticated Principal
                |
                v
       PowerContext Server PEP
                |
                v
       AuthorizationProvider  <---->  Policy or relationship store
                |
          allow or deny
                |
                v
       Existing application service
```

User A can transfer work in two ways:

- grant a Workstream role to a long-term collaborator; or
- grant B access to one exact committed Handoff Revision.

The second option is the least-privilege path in the first version. B can read that Handoff, inspect only the evidence
explicitly cited by it through the Handoff resolver, and leave a Receipt for the same exact Revision. B does not gain
access to other Handoffs, Memory, or Sources in the scope. B also does not gain permission to commit a new Handoff,
record a Task Outcome, use tools, access the network, or read credentials. An `accepted` Receipt records the result of
the transfer; it does not grant authority.

PowerContext defines a stable authorization request and decision, built-in roles, an Access API, and an OpenAPI
extension without requiring one policy engine. The first version provides a built-in Role Binding Store. Casbin,
OpenFGA, and Policy Decision Points (PDPs) compatible with the OpenID AuthZEN Authorization API can be integrated
through adapters.

# Motivation

PowerContext already has temporary Prepared Handoffs, immutable Handoff Revisions, Continue, Receipts, and Task
Outcomes. The current Server authentication model, however, is an optional global static Bearer token. A valid token
can call every protected operation. The Server cannot express that:

- A administers a Workstream while B can see only one transfer;
- B may acknowledge a transfer but may not publish another milestone;
- a team member may view a Handoff Report but may not approve an Experience or Skill;
- a revoked receiver may not read later Revisions;
- HTTP, MCP, and the Dashboard make the same decision for the same Principal.

RFC 0048 requires a receiver to be able to read the Handoff's scope and evidence. Adding B to the complete scope meets
that requirement but exposes unrelated Memory, Sources, and history. Copying only the Handoff body to B loses exact
evidence, Receipts, and revocation.

The authorization check in RFC 1223's `acknowledge_handoff` is the receiver's observation about the live environment.
It answers whether the receiver currently appears able to continue. It does not authenticate B and is not an ACL. The
natural-language `receiver`, `authorization_notes`, or an instruction such as “continue this work” cannot be an access
credential either.

Handoff therefore needs an authorization layer independent of its content and the Runtime domain API. That layer must
support least-privilege sharing, team roles, external PDPs, safe listing, audit, and fail-closed behavior without
allowing an Agent, a request body, or `scope_id` to establish authority.

# Guide-level explanation

## Mental model: transfer content and transfer access are different

A Handoff answers “where is the work?” An Access Binding answers “who may do what with this transfer now?” They have
different lifecycles:

```text
Prepared Handoff -> Commit -> immutable Handoff Revision
                                  |
                                  +-> Access Binding for user B
                                           |
                                  read / inspect / acknowledge
                                           |
                                    expire or revoke
```

Committing a new Handoff does not share it automatically. Sharing does not change the Handoff content or Revision.
Revoking a Binding does not delete the Handoff, Receipt, or audit events.

## A transfers one exact Handoff to B

Assume A administers the `project:payments` Workstream and has prepared a transfer. The normal flow is:

1. A inspects and commits the Prepared Handoff, producing an immutable `ArtifactReference`:

   ```json
   {
     "family": "handoff",
     "artifact_id": "project:payments",
     "revision": 12
   }
   ```

2. A explicitly selects B. The Dashboard or integration resolves B through the deployment's identity directory to a
   trusted canonical Principal. Model output, a display name, or email text cannot replace this resolution.
3. The Server checks whether A has `scope.delegate` on `project:payments`.
4. The Server creates an Access Binding with the `handoff.receiver` role for that exact Revision and optionally sets an
   expiration time.
5. B signs in using B's own credential. `resources/list` returns exact Handoffs B may read. B never receives A's token
   or a new bearer share link.
6. B calls Continue with an exact selection. The Server reads the same Revision and resolves only the evidence it
   explicitly cites.
7. After checking the live workspace, capability, and authorization state, B may leave an `accepted`,
   `needs_clarification`, or `declined` Receipt for the same Revision.

An example Binding creation request is:

```json
{
  "subject": {
    "type": "user",
    "issuer": "https://id.example.com/",
    "id": "00u-bob"
  },
  "resource": {
    "type": "handoff",
    "scope_id": "project:payments",
    "reference": {
      "family": "handoff",
      "artifact_id": "project:payments",
      "revision": 12
    }
  },
  "role": "handoff.receiver",
  "expires_at": "2026-09-06T12:00:00Z",
  "reason": "Continue the payment retry investigation",
  "idempotency_key": "transfer-payments-12-to-bob"
}
```

The Server supplies `granted_by`, creation time, and policy revision. The caller cannot assert them.

## What B can see

`handoff.receiver` is an exact-resource role, not a scope role:

| Operation | Result | Reason |
| --- | --- | --- |
| Read Handoff Revision 12 | Allowed | The Binding identifies this exact Revision |
| Inspect the citations of Revision 12 through Continue | Allowed | `handoff.evidence.read` covers only this Revision's citation manifest |
| Acknowledge Revision 12 | Allowed | A receiver may leave a Receipt for the exact Handoff it inspected |
| Request `latest` | Denied | Latest may be a later Revision that was never granted to B |
| Read Revision 11 or 13 | Denied | An exact Binding does not inherit to adjacent Revisions |
| Open the aggregate Handoff Report | Denied | The Report contains scope-level history and statistics |
| Search scope Memory or list Sources | Denied | A Handoff Binding does not grant general scope read |
| Commit a Handoff or record a Task Outcome | Denied | Those operations require `scope.contribute` |
| Approve a Candidate | Denied | Approval requires independent `scope.review` authority |

Least-privilege evidence access does not copy each Source or Memory item, and it does not require an external PDP to
store every citation. The Server reads the citation manifest from the immutable Handoff Revision, checks whether B has
`handoff.evidence.read` on that Handoff, and dereferences only exact citations in that manifest through the Handoff
resolver. B cannot reuse that permission by placing an arbitrary Source ID in a general read API.

If a citation has been deleted, retired, corrupted, or denied by a higher-order policy, Continue marks the
corresponding evidence unavailable. A Handoff Binding does not override retention, legal hold, data classification, or
an explicit deny policy.

## B takes over the Workstream

Seeing a transfer does not grant execution authority. If B will work on the Workstream over time, A or an administrator
must separately grant `scope.contributor`:

```text
handoff.receiver
  = read one exact Handoff + inspect its citations + acknowledge it

scope.contributor
  = read the Workstream + contribute Sources + prepare/commit Handoffs
    + acknowledge Handoffs + record Task Outcomes
```

PowerContext authorization governs only PowerContext resources and operations. The host, operating system, and
external services still govern Git changes, cloud APIs, production access, and credentials. A Handoff, Role Binding,
or Receipt cannot enlarge those permissions.

## Long-term team collaboration

A stable team can receive scope roles instead of a new Binding for each Revision:

- `scope.viewer` reads Handoffs, Memory, Sources, and read-only projections in the current scope;
- `scope.contributor` writes work evidence, Handoffs, and Outcomes in addition to viewer access;
- `scope.reviewer` reviews Artifact Candidates in addition to viewer access;
- `scope.delegator` shares exact Handoffs with receivers in addition to viewer access;
- `scope.admin` administers all roles and policies for the scope.

These fixed roles are wire-contract vocabulary. An external PDP does not have to persist the same role names. It may
map organization roles, teams, or relationships to these actions.

## Revocation and expiration

A or a scope administrator can revoke an exact Handoff Binding created by A. After revocation:

- B's later read, Continue, and acknowledge requests return 403;
- B no longer sees the Handoff in `resources/list`;
- the saved Handoff, Receipt, and Access Audit remain intact;
- content already displayed, exported, or copied by B cannot be recalled remotely.

The PDP evaluates expiration against trusted Server time. If an adapter cannot enforce conditions or expiration, it
must reject creation of an expiring Binding instead of silently creating permanent access.

A role change uses revoke + create rather than updating `handoff.viewer` in place to `handoff.receiver`. Revocation
uses `expected_version`; a concurrent change returns 409.

## The authorization service is unavailable

Authorization is a security dependency. In enforced mode:

- a missing or unverifiable identity returns 401;
- a valid identity with insufficient authority returns 403;
- an unavailable PDP, Binding Store, or safe resource filter returns 503;
- the Server does not fall back to a global token, an empty Principal, or allow-all when a PDP fails;
- `/health/live` still reports process liveness while `/health/ready` reports the required authorization dependency as
  not ready.

A 403 response does not distinguish “the resource does not exist” from “the resource exists but is not visible.” The
Repository may return 404 only after authorization succeeds, preventing resource enumeration.

# Reference-level explanation

## Goals and non-goals

This RFC aims to:

- establish one Server PEP in front of HTTP, MCP, and the Dashboard;
- establish a Principal from a credential without allowing the request to override it;
- support scope-level RBAC and exact Handoff receiver Bindings;
- resolve evidence cited by an exact Handoff safely without opening the complete scope;
- provide a replaceable decision interface and an optional relationship mutation interface;
- provide APIs for self-checks, resource discovery, Binding administration, and audit;
- fail closed for direct reads, lists, pagination, the internal MCP bridge, and background operations;
- preserve the domain purity of the current Runtime, Source, Memory, Handoff, and Work application APIs.

This RFC does not define:

- user registration, passwords, MFA, an OIDC Provider, or token issuance;
- a custom role DSL, wildcard scopes, organization hierarchy, or a group directory;
- anonymous bearer share links or authority embedded in Handoff content;
- authorization for Git, filesystems, tools, networks, model Providers, or credentials;
- redaction, cross-organization export, legal hold, or retention policy;
- approval workflows, temporary elevation, or an Agent requesting more authority automatically;
- PowerContext as a general-purpose IAM product.

## Trust model and invariants

An implementation must preserve these invariants:

1. `scope_id` is a business partition value, not proof of authority.
2. A Principal comes only from authentication middleware or trusted internal bridge context.
3. A `receiver`, `subject`, `actor`, role string, or Handoff prose in a request body cannot replace the current
   Principal.
4. Handoff and Memory are `untrusted_history` and cannot grant an action.
5. `is_internal_bridge()` may skip repeated transport authentication but never authorization.
6. Every protected operation receives a decision before it accesses a Repository or application service.
7. An exact Handoff grant does not allow `latest` and does not cover other Revisions of the same Artifact.
8. An `accepted` Receipt does not create, update, or inherit an Access Binding.
9. A model may suggest a receiver or explain a denial, but it cannot choose a canonical Principal or invoke an
   allow-all fallback.
10. Public errors, logs, metrics, and traces do not contain credentials, Handoff content, Memory, Source bodies, or raw
    PDP responses.

## Principal model

`PrincipalRef` uses the stable opaque identity established by an authentication Provider:

```json
{
  "type": "user",
  "issuer": "https://id.example.com/",
  "id": "00u-bob"
}
```

The fields mean:

| Field | Semantics |
| --- | --- |
| `type` | `user`, `service`, or a later registered Principal type |
| `issuer` | The trusted issuer that established the identity; local credentials use a deployment-specific issuer |
| `id` | A stable opaque subject within that issuer, not a display name or email address |

Agent names, hosts, session IDs, and model names are provenance, not Principals by default. When an enterprise token
proves an on-behalf-of actor, an authentication adapter may add that actor to trusted request context; a PDP may then
constrain both subject and actor. A client cannot assert that actor in a JSON body.

The existing Handoff Receipt `receiver` remains record content. The Server separately records the authenticated
Principal that produced the Receipt. If they differ, the Server rejects `accepted` or explicitly records the mismatch
for a non-accepted Receipt. It never treats the free-form `receiver` as a Principal.

## Resource model

Internal authorization requests use structured `ResourceRef` values. This avoids concatenating identifiers that may
contain `:`, `/`, or user data into policy strings:

| Resource type | Identity | Parent |
| --- | --- | --- |
| `server` | Deployment identifier | None |
| `scope` | Exact `scope_id` | Server |
| `handoff` | Exact Handoff `ArtifactReference` plus `scope_id` | Scope |

A Handoff resource includes `family`, `artifact_id`, and `revision`. A Prepared Handoff has no persistent identity and
cannot receive an exact Access Binding. A least-privilege cross-user transfer must be committed first. A caller in an
already shared trust domain may still transmit a Prepared Handoff explicitly, but the receiver needs separate scope
authority to read its evidence.

An adapter maps a structured ResourceRef to an external PDP object ID. The mapping must be canonical and stable, and
must not write email addresses, tokens, Handoff prose, or other PII into Casbin policy, OpenFGA tuples, or audit keys.

## Action vocabulary

First-version actions are stable lowercase dotted strings:

| Action | Resource | Meaning |
| --- | --- | --- |
| `server.observe` | server | Read service-level operations and observability data |
| `server.admin` | server | Administer deployment access configuration |
| `scope.read` | scope | Read general resources and projections in a Workstream |
| `scope.contribute` | scope | Write Sources, Memory contributions, Handoffs, and Outcomes |
| `scope.review` | scope | Review Artifact Candidates in the scope |
| `scope.delegate` | scope | Create viewer or receiver Bindings for exact Handoffs |
| `scope.admin` | scope | Administer roles, Bindings, and policy for the scope |
| `handoff.read` | exact handoff | Read one exact Handoff Revision |
| `handoff.evidence.read` | exact handoff | Resolve that Revision's citation manifest through the Handoff resolver |
| `handoff.acknowledge` | exact handoff | Create a Handoff Receipt for that Revision |

Business operations check actions rather than role names. External role and relationship models can therefore evolve
without changing application code.

Policy may make `scope.read` imply `handoff.read` and `handoff.evidence.read` for Handoffs under the scope.
`scope.contribute` may imply acknowledge, prepare, commit, and Outcome writes. The reverse implication never holds: an
exact `handoff.receiver` does not gain `scope.read` or `scope.contribute`.

## Built-in roles

| Role | Granted actions |
| --- | --- |
| `handoff.viewer` | `handoff.read`, `handoff.evidence.read` on one exact Handoff |
| `handoff.receiver` | Viewer actions plus `handoff.acknowledge` on one exact Handoff |
| `scope.viewer` | `scope.read` |
| `scope.contributor` | `scope.read`, `scope.contribute` |
| `scope.reviewer` | `scope.read`, `scope.review` |
| `scope.delegator` | `scope.read`, `scope.delegate` |
| `scope.admin` | Every scope action, including delegation and Binding administration |
| `server.observer` | `server.observe` |
| `server.admin` | Every server and scope action |

The first version does not allow the public API to create roles or change role-to-action mappings. Fixed roles give
OpenAPI, the Dashboard, and adapter conformance tests stable semantics. An enterprise PDP may map custom organization
roles to the actions externally.

A Principal with `scope.delegate` may create only `handoff.viewer` or `handoff.receiver`, and only for an existing
exact Handoff in that scope. Creating a scope role requires `scope.admin`. Creating `server.admin` requires an existing
`server.admin` and permission from deployment policy. A Principal cannot grant itself authority beyond the caller's
administration boundary.

## Authorization request and decision

The PowerContext decision model aligns with the subject, action, resource, and context shape of the OpenID AuthZEN
Authorization API, but the Python protocol does not require an HTTP PDP:

```python
class AuthorizationProvider(Protocol):
    async def check(self, request: AccessRequest, /) -> AccessDecision: ...

    async def check_batch(
        self,
        requests: Sequence[AccessRequest],
        /,
    ) -> Sequence[AccessDecision]: ...

    async def list_resources(
        self,
        request: ResourceSearchRequest,
        /,
    ) -> AuthorizedResourcePage: ...
```

A normalized request is:

```json
{
  "subject": {
    "type": "user",
    "issuer": "https://id.example.com/",
    "id": "00u-bob"
  },
  "action": {"name": "handoff.read"},
  "resource": {
    "type": "handoff",
    "scope_id": "project:payments",
    "reference": {
      "family": "handoff",
      "artifact_id": "project:payments",
      "revision": 12
    }
  },
  "context": {
    "request_id": "pc-01K...",
    "transport": "mcp"
  }
}
```

`AccessDecision` contains at least:

```json
{
  "allowed": true,
  "reason_code": "role_binding",
  "policy_revision": "42"
}
```

`reason_code` is a stable, low-sensitivity enum for audit and diagnostics. A business 403 response does not expose a
provider rule, tuple, URL, stack, or raw body. `policy_revision` correlates audit and cache behavior to a defined
policy; it is not an authorization token.

`check_batch` preserves input order and returns one decision for each item. An adapter cannot use one allowed item to
permit a complete batch.

`list_resources` is required for safe list operations. It obtains allowed resource identities from the authorization
system before passing a bounded identity set to a Repository. A Provider that offers only point checks and cannot
produce a safe resource filter must not query all Handoffs, Projects, or Scopes and filter them afterward. The
affected list operation returns 503, or configuration rejects the Provider as missing a required capability.

## Relationship administration

AuthZEN defines decision interoperability, not the relationship mutation interface for every PDP. Administration is
therefore separate from decisions:

```python
class RelationshipWriter(Protocol):
    async def create_binding(
        self,
        request: CreateAccessBinding,
        /,
    ) -> AccessBinding: ...

    async def revoke_binding(
        self,
        binding_id: str,
        /,
        *,
        expected_version: int,
    ) -> AccessBinding: ...
```

The built-in Provider and Casbin or OpenFGA adapters may implement both `AuthorizationProvider` and
`RelationshipWriter`. An OPA, Cerbos, or generic AuthZEN adapter may provide decisions only. Its PowerContext Binding
mutation endpoint then returns `relationship_management_unavailable`, and administrators configure relationships in
the external system. The Server must not report a successful grant and then write only a local shadow record.

## Access Binding model

The built-in Binding Store records at least:

| Field | Requirement |
| --- | --- |
| `binding_id` | Server-generated opaque ID |
| `subject` | Canonical `PrincipalRef` |
| `resource` | Canonical exact `ResourceRef` |
| `role` | One fixed role name |
| `granted_by` | Authenticated Principal recorded by the Server |
| `reason` | Optional bounded human explanation |
| `created_at` | Trusted Server time |
| `expires_at` | Optional trusted expiration |
| `state` | `active` or `revoked` |
| `version` | Monotonically increasing CAS version |
| `policy_revision` | Policy version after mutation when available |
| `idempotency_key` | Bounded caller key scoped to grantor and resource |

A role, subject, or resource change revokes the old Binding and creates a new one. A retry with the same grantor,
idempotency key, and payload returns the original Binding. The same key with a different payload returns 409.
Expiration does not delete a record; the decision treats it as denied.

The built-in Binding Repository belongs to a Server access-control component. It is not added to the Runtime
`context`, `source`, `memory`, `handoff`, or `work` application object. It may share a deployment database with the
Server, but it owns an independent schema, migrations, and API.

## Public Access API

The OpenAPI source of truth adds these operations:

| Operation | Purpose | Authorization |
| --- | --- | --- |
| `GET /v1/access/me` | Return the current Principal and access-control capabilities | Authenticated Principal |
| `POST /v1/access/check` | Check one action/resource for the current Principal | Current Principal only |
| `POST /v1/access/check-batch` | Batch checks for the current Principal | Current Principal only |
| `POST /v1/access/resources/list` | List resource identities available to the current Principal | Current Principal only |
| `POST /v1/access/roles/list` | Return fixed roles and action vocabulary | Authenticated Principal |
| `POST /v1/access/bindings/list` | List Bindings the caller may administer | `scope.delegate`, `scope.admin`, or `server.admin` |
| `POST /v1/access/bindings/create` | Create an exact-Handoff or administrative Binding | Resource-specific administration action |
| `POST /v1/access/bindings/revoke` | Revoke a Binding using CAS | Same administration boundary |
| `POST /v1/access/audit/list` | Query security audit events | `scope.admin` or `server.admin` |

`check`, `check-batch`, and `resources/list` do not accept a client-selected subject. They evaluate only the current
authenticated Principal, preventing ordinary users from using the API as a personnel permission oracle.
Administrator checks for another Principal, subject search, and directory integration are deferred.

`bindings/create` necessarily accepts a target subject so A can name B, but the caller can create only fixed roles on
resources it may administer. Before writing, the Server reads the exact Handoff identity after authorization and
confirms that it exists in the target scope.

The public `check` operation may return HTTP 200 with `allowed=false`. The same denial on a business operation returns
403 and does not call the application service. The Access API supports explanation and UI preflight; it never replaces
enforcement when the business request runs.

## Handoff operation requirements

The first-version Handoff mappings are:

| Operation | Required authorization |
| --- | --- |
| `prepare_handoff`, `finalize_handoff`, `handoff_current_work` | `scope.contribute` on request `scope_id` |
| `commit_handoff` | `scope.contribute` on request `scope_id` |
| `continue_handoff(selection=latest)` | `scope.read` on request `scope_id` |
| `continue_handoff(selection=exact)` | `scope.read` or `handoff.read` on the exact Revision |
| `continue_handoff(selection=prepared)` | `scope.read` on request `scope_id` |
| `acknowledge_handoff` with an exact Receipt | `scope.contribute` or `handoff.acknowledge` on the exact Revision |
| `record_task_outcome` | `scope.contribute` on request `scope_id` |
| Aggregate Handoff Report queries | Scope-level read; an exact Handoff grant is insufficient |
| Handoff Report administration | `scope.admin` or an appropriate server administration action |

When an exact receiver calls Continue, the request provides `selection=exact` and an exact `ArtifactReference`. The
Server builds the Handoff ResourceRef and evaluates it before reading the Revision. It cannot resolve latest before
the check or fall back to latest when the exact Revision is absent.

A Prepared Handoff may contain complete caller-supplied content, so the narrow grant path does not accept
`selection=prepared`. Only a Principal with `scope.read` may use a prepared selection to resolve scope evidence.

## OpenAPI access metadata

Every protected operation declares `x-powercontext-access` in `openapi/powercontext.yaml`. The generator includes the
extension as `Operation.access`; Server `_add_route()` uses it to assemble the PEP wrapper. For example:

```yaml
/v1/handoff/commit:
  post:
    operationId: commit_handoff
    x-powercontext-access:
      action: scope.contribute
      resource:
        type: scope
        scope-id-from: body.scope_id
```

An operation whose policy depends on selection names a registered resolver rather than embedding executable
expressions in YAML:

```yaml
x-powercontext-access:
  resolver: continue_handoff_access
```

A resolver is deterministic, Server-owned, and unit-tested. It builds an AccessRequest only from the validated request
model and route metadata. It cannot read a business Repository before deciding what to authorize.

Health endpoints, static page shells, and authentication callbacks may be explicitly public. A new business operation
without access metadata fails contract generation or contract tests; it never defaults to public.

## Server PEP

Request order is fixed:

```text
transport authentication
  -> bind Principal and trusted request context
  -> validate request schema
  -> resolve action and resource
  -> AuthorizationProvider decision
  -> application service
  -> response
```

Schema validation may run before the decision to establish a resource identity safely, but validation errors do not
expose resource content. Every Repository lookup, Handoff resolution, Memory search, Report aggregate, and mutation
runs after allow.

The PEP lives in the Server adapter. It does not add `principal`, role, or permission parameters to
`application.context.for_scope(...)` or to Source, Memory, Handoff, Work, or Review domain methods. Local in-process
Runtime calls do not gain Server authentication automatically. A local integration that needs a security boundary
uses the same Access Control service or calls through the Server.

## HTTP, MCP, and Dashboard parity

HTTP is the complete remote contract. MCP and the Dashboard reuse the same operations and PEP:

- HTTP authentication establishes a Principal before the authorization wrapper runs for each operation;
- the MCP internal ASGI bridge propagates the original Principal, actor, and request ID in request-local context;
- `is_internal_bridge()` can avoid parsing the same external credential twice, but the authorization wrapper still
  runs;
- MCP tool discovery may filter unavailable tools for the current Principal, but hiding a tool is only UX and each
  invocation still receives a decision;
- the Dashboard uses `access/me` and batch checks to disable or hide actions but cannot bypass API enforcement;
- a background job carries the service Principal bound when it was created or an explicit system Principal, never an
  empty identity.

HTTP and MCP return the same allow or deny for the same Principal, action, resource, and policy revision. Adapter
conformance tests protect that guarantee.

## Listing and pagination

Lists can leak Project names, scope IDs, Handoff objectives, or Candidate metadata. The safe order is:

```text
AuthorizationProvider.list_resources
  -> bounded authorized identity filter
  -> Repository query restricted by that filter
  -> stable pagination
  -> response
```

This implementation is prohibited:

```text
Repository.list_all -> page -> check each item -> remove denied rows
```

It leaks totals, cursors, holes, and timing, and can prevent an authorized user from ever reaching later rows. `total`,
cursors, and page boundaries describe only the authorized collection.

An exact Handoff receiver discovers granted Revisions through `/v1/access/resources/list`; this does not place the
receiver in aggregate Project or Workstream lists. Only scope-level read permits Handoff Report aggregate queries.

## Audit and diagnostics

Access Audit is an append-only Server security record. It contains at least:

- request ID, time, transport, and operation ID;
- the Principal's opaque identifier and trusted actor identifier, if present;
- action, resource type, and opaque resource identity;
- allow or deny, stable reason code, and policy revision;
- for Binding creation or revocation, binding ID, grantor, target, role, and expected/result version.

Audit does not contain:

- Bearer tokens, cookies, client secrets, or PDP credentials;
- Handoff objectives, state, or next action;
- Source, Memory, PreparedContext, or citation bodies;
- arbitrary exception fields, configured PDP URLs, or raw provider responses;
- email addresses, display names, or unnecessary directory attributes.

Ordinary logs, metrics, and traces use the same data-minimization boundary. Public readiness returns only stable
component states and safe reasons. Detailed provider diagnostics stay in a protected operator channel.

## Consistency and failure recovery

Committing a Handoff and creating an external authorization relationship are not a disguised cross-system
transaction. A “send to B” UI performs recoverable steps:

1. commit or reuse the same exact Handoff Revision;
2. create the Binding using a stable idempotency key;
3. display “shared” only after both steps succeed;
4. if the second step fails, display “Handoff saved, but not yet visible to B” and retry only Binding creation;
5. do not prepare, commit, or create another Revision.

When the Binding succeeded but the client lost the response, the same idempotency key returns the original Binding.
If an external RelationshipWriter cannot provide equivalent idempotency, its adapter performs a safe exact
relationship lookup first or declares self-service mutation unsupported.

Receipt creation retains the existing exact-selection and evidence rules. The decision occurs before the Receipt
transaction. If authority is revoked concurrently immediately after the check, a colocated Provider and Binding Store
use a policy revision or transaction fence to avoid an obvious stale write. A remote PDP has a bounded residual TOCTOU
window and records the decision revision. The first version does not cache allowed decisions.

## Provider profiles

### Built-in provider

The built-in profile uses fixed roles and a Server-owned Binding Store. It supports point checks, batch checks,
authorized resource listing, creation, revocation, and audit. It is the reference semantics for local deployments and
conformance tests. It does not provide passwords, a directory, or a custom policy language.

### Casbin adapter

A Casbin adapter can use RBAC with domains:

- subject maps to an issuer-scoped opaque ID;
- domain maps to the canonical scope resource namespace;
- object maps to a scope or exact Handoff resource key;
- action uses this RFC's action vocabulary;
- role assignment and policy mutation use the Casbin management API and a persistence adapter.

The Casbin domain is an adapter policy namespace. It does not turn `scope_id` into authentication or tenant proof. The
adapter derives the domain from a trusted ResourceRef supplied by the Server.

### OpenFGA adapter

OpenFGA naturally represents relationships among users, groups, scopes, and exact Handoffs. A conceptual model is:

```text
type user

type scope
  relations
    define viewer: [user]
    define contributor: [user]
    define reviewer: [user]
    define delegator: [user]
    define admin: [user]
    define can_read: viewer or contributor or reviewer or delegator or admin
    define can_contribute: contributor or admin
    define can_review: reviewer or admin
    define can_delegate: delegator or admin

type handoff
  relations
    define parent: [scope]
    define viewer: [user]
    define receiver: [user]
    define can_read: viewer or receiver or can_read from parent
    define can_acknowledge: receiver or can_contribute from parent
```

The adapter uses an explicit authorization model ID for Check, ListObjects, and tuple writes. Tuples contain only
opaque IDs, never email addresses or Handoff content. Model migration switches the configured model ID explicitly; it
does not use an implicit latest model.

### AuthZEN, OPA, and Cerbos adapters

An AuthZEN adapter maps `AccessRequest` to the Authorization API subject, action, resource, and context and maps the
decision back to `AccessDecision`. An OPA adapter can submit the same structure as its input document. A Cerbos adapter
can map it to principal, resource, and actions.

Decision interoperability does not imply policy administration interoperability. If an organization manages policy
through GitOps, IAM, or a separate administration plane, PowerContext consumes decisions and safe resource search but
does not write policy. The deployment declares `relationship_management=false`, and the Dashboard does not present a
self-service share control that could report false success.

## Configuration and compatibility

The Server provides three explicit modes:

| Mode | Behavior |
| --- | --- |
| `disabled` | Preserve existing single-user, single-trust-domain behavior; Access API unavailable; no multi-user isolation claim |
| `legacy-static-admin` | Map the current static Bearer to a deployment-local `server.admin` Principal |
| `enforced` | Require both an authentication Provider and AuthorizationProvider; run the PEP for every business operation |

An upgrade cannot fall back to `disabled` because external identity is configured but a PDP is missing. Mode is
explicit. Capabilities and readiness report the current mode and whether relationship management, batch checks, and
safe resource listing are available.

`disabled` is suitable only for a local environment whose caller already trusts the whole process and catalog.
Documentation cannot describe it as a secure multi-user configuration. Remote, multi-user, or shared-Dashboard
deployments use `enforced`.

Adding authorization metadata to an existing OpenAPI operation does not change its domain request or response schema,
but it adds a 403 response and changes unauthorized behavior. The generated Client maps 401, 403, and 503 to stable,
distinct exceptions; it does not treat 403 as an empty result.

## Implementation slices

Implementation proceeds in independently verifiable slices:

1. **Contract and Principal**: OpenAPI Access models, operation metadata, generated `Operation.access`, trusted request
   Principal, and stable errors.
2. **Built-in PEP/PDP**: fixed roles, Binding Store, `_add_route()` authorization wrapper, point/batch checks, and
   audit.
3. **Exact Handoff receiver**: post-commit Binding creation, exact Continue, citation-manifest resolver, exact
   acknowledge, revocation, and expiration.
4. **Safe listing and UI**: authorized resource listing, Handoff inbox, Dashboard permission projection, and
   authorization-aware pagination.
5. **MCP parity**: Principal propagation through the internal bridge, tool-discovery UX, and invocation-time
   enforcement.
6. **External adapters**: implement Casbin or OpenFGA first, then validate an AuthZEN-compatible PDP with the same
   conformance suite.
7. **Migration**: legacy static admin, configuration validation, readiness, and operator documentation.

Every slice leaves the Server in a coherent state. An intermediate release cannot protect only HTTP while MCP bypasses
the PEP, or hide only Dashboard controls without API enforcement.

## Test and acceptance plan

The implementation of this RFC is complete only when these observable scenarios pass:

- an unauthenticated request to a protected operation returns 401;
- A with `scope.delegate` can grant an existing exact Revision to B; without that action the request returns 403 and
  writes no Binding;
- B can read, Continue, and acknowledge the granted exact Revision;
- B is denied latest, adjacent Revisions, the aggregate Handoff Report, Memory lists, Source lists, and Task Outcome
  writes;
- B reads manifest citations only through the authorized Handoff resolver and cannot submit an arbitrary citation to
  a general read endpoint;
- `handoff.viewer` cannot acknowledge while `handoff.receiver` can;
- an `accepted` Receipt creates no Binding or scope role;
- after revocation or expiration, B's later access is denied and authorized resource listing omits the Revision;
- Binding creation and revocation have stable CAS, idempotency, and audit behavior;
- 403 does not leak resource existence, and list cursors and totals describe only the authorized collection;
- an unavailable PDP returns 503 without calling an application service, Repository, or mutation;
- the MCP internal bridge uses the original Principal and returns the same denial as HTTP;
- the API denies a request even when Dashboard controls are bypassed or fail to hide it;
- a legacy static token becomes local admin only in the explicit compatibility mode;
- built-in, Casbin/OpenFGA, and AuthZEN adapters return equivalent decisions for the same conformance vectors;
- Access Audit contains no token, Handoff content, Memory, Source body, or raw PDP error.

Cross-component acceptance scenarios belong in `tests/e2e/` and assert through the public HTTP and MCP contracts.
Focused tests cover resource resolvers, role mapping, Binding CAS, provider failure, and citation membership without
freezing private call order.

# Drawbacks

Every business request adds an authorization decision. A remote PDP adds a network dependency and latency. Safe lists
require resource search or a filter that can be pushed down, so a point-check-only adapter cannot support every
Dashboard list.

An exact Handoff transfer must be committed first. A temporary Prepared Handoff cannot become a revocable cross-user
resource. That adds a persistence step but avoids inventing a second identity and ACL model for temporary payloads.

Separating decisions from relationship management makes the adapter surface more complex than a single `check()`.
Assuming every external PDP lets PowerContext write policy would, however, make a false portability promise.

Revocation blocks future access but cannot erase information a receiver has already read, captured, or exported.
Handoffs containing highly sensitive material still need content minimization, external data classification, and
export controls.

Fixed first-version roles limit organization-specific UX. An enterprise can map custom roles in its external PDP, but
the PowerContext public API does not immediately provide a custom role editor.

# Rationale and alternatives

## Chosen: independent Server PEP plus replaceable PDP

This design keeps Handoff and Runtime models independent of the identity system while giving HTTP, MCP, and the
Dashboard one enforcement path. Stable action vocabulary maps across Casbin, OpenFGA, OPA, Cerbos, and enterprise IAM
more reliably than stable external role names.

An AuthZEN-compatible request shape gives remote PDPs a standard integration point. A separate RelationshipWriter
accurately reflects that AuthZEN does not standardize all grant mutations.

## Alternative: put ACL fields on Handoff or scope

Adding `allowed_users` to Handoff or encoding owner and tenant into `scope_id` looks direct but mixes identity
lifecycle, group expansion, revocation, external policy revision, and audit into domain data. An immutable Handoff
should not receive a new Revision whenever team membership changes. This alternative is rejected.

## Alternative: scope-level roles only

Granting only `scope.viewer` is easy, but B then sees the complete Workstream's Memory, Sources, history, and Report.
That violates least privilege for a temporary relay. Scope roles remain available for long-term collaboration; exact
Handoff Bindings serve one-off transfers.

## Alternative: send an anonymous capability URL

A bearer share link treats knowledge of a URL as identity. Links can enter chat, logs, browser history, or model
context. They make it hard to identify the actual receiver or apply enterprise group policy and individual audit. The
first version requires B's own authenticated identity and does not provide anonymous capability URLs.

## Alternative: copy a redacted Handoff document

Copying Markdown avoids Server authorization work but loses exact Revision, evidence availability, Receipt,
concurrency, and revocation semantics. Export may become an explicit external publication feature, but it cannot
replace a PowerContext-internal transfer.

## Alternative: hide unauthorized Dashboard controls

UI hiding improves experience but an HTTP or MCP caller can bypass it. Enforcement always occurs at the Server PEP;
the Dashboard only consumes the same decisions.

## Alternative: require one policy engine

Casbin fits embedded RBAC, OpenFGA fits relationships and groups, and OPA or Cerbos fits an existing policy platform.
Requiring one implementation either increases deployment cost or restricts enterprise integration. PowerContext
defines semantics and a conformance contract rather than one engine.

## Alternative: store roles in access tokens

Token roles are simple but poorly suited to exact Handoff grants, revocation, large resource sets, and policy updates.
A token may carry trusted identity and group claims, but the PDP still makes the final resource decision.

## Alternative: authorize inside every Runtime method

Passing a Principal into Context, Source, Memory, Handoff, and Work spreads transport policy through the domain,
encourages divergent HTTP and MCP implementations, and changes local domain APIs. The Server PEP is the single remote
trust-boundary enforcement point.

# Prior art

PowerContext [RFC 0011](0011_remote_access_architecture.md) defines HTTP as the complete contract with the generated
Client and MCP projection sharing Server application semantics. This RFC adds authentication and authorization at the
same Server boundary rather than creating a parallel MCP policy service.

[RFC 0048](0048_handoff_artifact.md) defines Prepared Handoffs, immutable Handoff Revisions, Continue, and exact
evidence. [RFC 1223](1223_human_agent_work_continuity.md) defines Receipts and Task Outcomes and states that a transfer
does not grant tools, network access, or credentials. [RFC 0082](0082_handoff_report.md) provides scope- and
Project-level aggregate views. This RFC adds Principal-aware visibility to those reads and writes.

The [OpenID AuthZEN Authorization API 1.0](https://openid.net/specs/authorization-api-1_0.html) defines the subject,
action, resource, context, and decision contract between PEPs and PDPs. This RFC aligns with that information model
while retaining an embedded Provider option.

[Casbin RBAC with Domains](https://casbin.apache.org/docs/rbac-with-domains/) demonstrates domain-scoped role
assignment. [OpenFGA concepts](https://openfga.dev/docs/concepts) use user, relation, and object tuples for object-level
authorization. [OPA](https://www.openpolicyagent.org/docs/integration) provides a general policy decision integration.
[Cerbos CheckResources](https://docs.cerbos.dev/cerbos/latest/api/index.html) provides batch decisions over principals,
resources, and actions. These systems are adapter targets; they do not change the PowerContext Handoff lifecycle.

# Unresolved questions

The RFC must resolve these choices before merge, but they do not change the core security boundary:

- whether the first external conformance adapter is Casbin or OpenFGA;
- whether the built-in Provider ships with the default Server extra or a separate optional extra;
- how the Dashboard selects a canonical recipient from the deployment identity directory; the Access API in this RFC
  does not provide directory search;
- whether an enforced deployment requires safe resource listing or may disable the corresponding Dashboard lists;
- whether deployment policy sets a default expiration for `handoff.receiver` or the UI requires an explicit choice;
- whether the UI suggests a separate `scope.contributor` grant after an exact receiver creates a Receipt, without ever
  performing that upgrade automatically.

Custom roles, organization hierarchy, cross-tenant export, anonymous share links, temporary elevation, approval
workflows, and general Source or Memory object-level ACLs are explicitly deferred. They require separate threat models
and RFCs.

# Future possibilities

The subject/action/resource contract can later support:

- group, team, and organization relationships;
- Project-to-Workstream inheritance and explicit deny;
- administrator checks, subject/resource search, and access-review campaigns;
- approval-backed temporary scope elevation;
- AuthZEN Search APIs, obligations, and richer decision metadata;
- policy bundles, signed decision metadata, and cross-service audit correlation;
- separate redaction, watermarking, and data-loss-prevention policy for Handoff export;
- exact-resource grants for more Artifact Families;
- a bounded decision cache after a clear revocation-staleness guarantee exists.

These extensions cannot change the first-version invariants: `scope_id` is not an ACL, Handoff content does not grant
authority, a Receipt does not elevate authority, and every transport fails closed at the Server PEP.
