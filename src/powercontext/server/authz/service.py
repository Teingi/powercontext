# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Authorization Provider SPI and Server-owned Access use cases."""

from __future__ import annotations

from base64 import b64decode, urlsafe_b64encode
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol, TypeVar
from uuid import uuid4

from powercontext.server.authz.errors import (
    AccessControlError,
    AccessDeniedError,
    AccessIdentityRequiredError,
    AccessInvalidRequestError,
    AccessUnavailableError,
)
from powercontext.server.authz.models import (
    DEFAULT_DEPLOYMENT_ID,
    ROLE_ACTIONS,
    AccessAction,
    AccessAuditEvent,
    AccessBinding,
    AccessBindingState,
    AccessDecision,
    AccessResourceType,
    AccessRole,
    PrincipalRef,
    ResourceRef,
)
from powercontext.server.authz.profiles import (
    ARTIFACT_FAMILY_PROFILES,
    artifact_family_profile,
    validate_action_resource,
    validate_binding_role,
)

_T = TypeVar("_T")
_MAX_AUTHORIZED_FILTER_IDENTITIES = 10_000


@dataclass(frozen=True, slots=True)
class AuthorizedResourceFilter:
    """Bounded identities and parent constraints authorized before repository access."""

    exact_resources: tuple[ResourceRef, ...]
    parent_constraints: tuple[ResourceRef, ...]
    policy_revision: str | None


@dataclass(frozen=True, slots=True)
class AuthorizedResourcePage:
    """One stable, non-discovering page of resources visible to a Principal."""

    items: tuple[ResourceRef, ...]
    total: int
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class AccessProviderCapabilities:
    """Enforcement features that one configured Provider can safely supply."""

    safe_resource_filtering: bool
    multi_requirement_check: bool
    relationship_management: bool


@dataclass(frozen=True, slots=True)
class AccessAuditContext:
    """Low-sensitivity request facts attached to a decision audit event."""

    transport: str
    operation: str
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class AccessRequest:
    """Normalized AuthZEN-shaped point decision request."""

    subject: PrincipalRef
    action: AccessAction
    resource: ResourceRef
    context: AccessAuditContext


@dataclass(frozen=True, slots=True)
class ResourceSearchRequest:
    """Normalized request for a safe, provider-owned resource filter."""

    subject: PrincipalRef
    action: AccessAction
    resource_type: AccessResourceType
    family: str | None
    context: AccessAuditContext


@dataclass(frozen=True, slots=True)
class CreateBinding:
    """Validated intent to create one immutable Access Binding."""

    subject: PrincipalRef
    resource: ResourceRef
    role: AccessRole
    idempotency_key: str
    reason: str | None = None
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.idempotency_key or len(self.idempotency_key) > 255:
            raise AccessInvalidRequestError("idempotency-key")
        if self.reason is not None and len(self.reason) > 1_024:
            raise AccessInvalidRequestError("reason")


class AuthorizationProvider(Protocol):
    """Replaceable decision interface suitable for embedded or remote PDPs."""

    async def check(self, request: AccessRequest, /) -> AccessDecision: ...

    async def check_batch(
        self,
        requests: Sequence[AccessRequest],
        /,
    ) -> tuple[AccessDecision, ...]: ...

    async def resolve_resource_filter(
        self,
        request: ResourceSearchRequest,
        /,
    ) -> AuthorizedResourceFilter: ...


class RelationshipWriter(Protocol):
    """Replaceable relationship mutation interface paired with a Provider."""

    async def get_binding(self, binding_id: str) -> AccessBinding | None: ...

    async def list_bindings(
        self,
        *,
        subject: PrincipalRef | None = None,
        resource: ResourceRef | None = None,
        include_revoked: bool = False,
    ) -> tuple[AccessBinding, ...]: ...

    async def create_binding(self, binding: AccessBinding) -> AccessBinding: ...

    async def revoke_binding(
        self,
        binding_id: str,
        *,
        expected_version: int,
        revoked_at: datetime,
        revoked_by: PrincipalRef,
    ) -> AccessBinding: ...


class AccessAuditStore(Protocol):
    """Append-only audit boundary that can use a dedicated compliance backend."""

    async def append_audit(self, event: AccessAuditEvent) -> AccessAuditEvent: ...

    async def list_audit(
        self,
        *,
        resource: ResourceRef | None = None,
        after: int | None = None,
        limit: int = 100,
    ) -> tuple[AccessAuditEvent, ...]: ...


class AccessRepository(RelationshipWriter, AccessAuditStore, Protocol):
    """Built-in Provider read requirements."""

    async def policy_revision(self) -> str: ...

    async def active_bindings(self, subject: PrincipalRef, *, now: datetime) -> tuple[AccessBinding, ...]: ...


class BuiltinAuthorizationProvider:
    """Small hierarchical RBAC profile backed by immutable Access Bindings."""

    def __init__(
        self,
        repository: AccessRepository,
        *,
        bootstrap_administrators: Sequence[PrincipalRef] = (),
        deployment_id: str = DEFAULT_DEPLOYMENT_ID,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._bootstrap_administrators = frozenset(bootstrap_administrators)
        self._deployment_id = deployment_id
        self._clock = clock or (lambda: datetime.now(UTC))

    async def check(self, request: AccessRequest, /) -> AccessDecision:
        revision = await self._repository.policy_revision()
        if request.action is AccessAction.ACCESS_SELF:
            return AccessDecision(True, "authenticated", revision)
        if request.subject in self._bootstrap_administrators:
            return AccessDecision(True, "bootstrap-admin", revision)
        bindings = await self._repository.active_bindings(request.subject, now=self._clock())
        return _binding_decision(bindings, request.action, request.resource, policy_revision=revision)

    async def check_batch(
        self,
        requests: Sequence[AccessRequest],
        /,
    ) -> tuple[AccessDecision, ...]:
        revision = await self._repository.policy_revision()
        if not requests:
            return ()
        principal = requests[0].subject
        if any(request.subject != principal for request in requests):
            raise AccessInvalidRequestError("batch-subject")
        if principal in self._bootstrap_administrators:
            return tuple(AccessDecision(True, "bootstrap-admin", revision) for _ in requests)
        bindings = await self._repository.active_bindings(principal, now=self._clock())
        return tuple(
            AccessDecision(True, "authenticated", revision)
            if request.action is AccessAction.ACCESS_SELF
            else _binding_decision(bindings, request.action, request.resource, policy_revision=revision)
            for request in requests
        )

    async def resolve_resource_filter(
        self,
        request: ResourceSearchRequest,
        /,
    ) -> AuthorizedResourceFilter:
        revision = await self._repository.policy_revision()
        if request.subject in self._bootstrap_administrators:
            return AuthorizedResourceFilter(
                exact_resources=(ResourceRef.server(self._deployment_id),)
                if request.resource_type is AccessResourceType.SERVER
                else (),
                parent_constraints=(ResourceRef.server(self._deployment_id),),
                policy_revision=revision,
            )
        bindings = await self._repository.active_bindings(request.subject, now=self._clock())
        exact: dict[str, ResourceRef] = {}
        parents: dict[str, ResourceRef] = {}
        for binding in bindings:
            if request.action not in ROLE_ACTIONS[binding.role]:
                continue
            resource = binding.resource
            if resource.type is request.resource_type and (request.family is None or resource.family == request.family):
                exact[resource.key] = resource
            elif _resource_is_parent(resource, request.resource_type):
                parents[resource.key] = resource
        return AuthorizedResourceFilter(
            exact_resources=tuple(exact[key] for key in sorted(exact)),
            parent_constraints=tuple(parents[key] for key in sorted(parents)),
            policy_revision=revision,
        )


class AccessControlService:
    """Fail-closed Access orchestration shared by HTTP and MCP transports."""

    def __init__(
        self,
        provider: AuthorizationProvider,
        *,
        relationships: RelationshipWriter | None,
        audit: AccessAuditStore,
        deployment_id: str = DEFAULT_DEPLOYMENT_ID,
        mode: Literal["legacy-static-admin", "enforced"] = "enforced",
        provider_capabilities: AccessProviderCapabilities | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.provider = provider
        self.relationships = relationships
        self.audit = audit
        self.deployment_id = deployment_id
        self.mode = mode
        self.provider_capabilities = provider_capabilities or AccessProviderCapabilities(
            safe_resource_filtering=True,
            multi_requirement_check=True,
            relationship_management=relationships is not None,
        )
        self._clock = clock or (lambda: datetime.now(UTC))

    async def check(
        self,
        principal: PrincipalRef | None,
        action: AccessAction,
        resource: ResourceRef,
        *,
        context: AccessAuditContext,
    ) -> AccessDecision:
        actor = _required_principal(principal)
        validate_action_resource(action, resource, deployment_id=self.deployment_id)
        request = AccessRequest(subject=actor, action=action, resource=resource, context=context)
        decision = await _access_call(self.provider.check(request))
        _validate_provider_decision(decision)
        if action is not AccessAction.ACCESS_SELF:
            await _access_call(self._record_decision(actor, action, resource, decision, context=context))
        return decision

    async def require(
        self,
        principal: PrincipalRef | None,
        action: AccessAction,
        resource: ResourceRef,
        *,
        context: AccessAuditContext,
    ) -> AccessDecision:
        decision = await self.check(principal, action, resource, context=context)
        if not decision.allowed:
            raise AccessDeniedError
        return decision

    async def check_batch(
        self,
        principal: PrincipalRef | None,
        checks: Sequence[tuple[AccessAction, ResourceRef]],
        *,
        context: AccessAuditContext,
    ) -> tuple[AccessDecision, ...]:
        if not self.provider_capabilities.multi_requirement_check:
            raise AccessUnavailableError("multi_requirement_check_unavailable")
        actor = _required_principal(principal)
        for action, resource in checks:
            validate_action_resource(action, resource, deployment_id=self.deployment_id)
        requests = tuple(
            AccessRequest(subject=actor, action=action, resource=resource, context=context)
            for action, resource in checks
        )
        decisions = await _access_call(self.provider.check_batch(requests))
        if len(decisions) != len(checks):
            raise AccessUnavailableError
        for decision in decisions:
            _validate_provider_decision(decision)
        for (action, resource), decision in zip(checks, decisions, strict=True):
            if action is not AccessAction.ACCESS_SELF:
                await _access_call(self._record_decision(actor, action, resource, decision, context=context))
        return decisions

    async def require_all(
        self,
        principal: PrincipalRef | None,
        checks: Sequence[tuple[AccessAction, ResourceRef]],
        *,
        context: AccessAuditContext,
    ) -> tuple[AccessDecision, ...]:
        decisions = await self.check_batch(principal, checks, context=context)
        if not all(decision.allowed for decision in decisions):
            raise AccessDeniedError
        return decisions

    async def list_resources(
        self,
        principal: PrincipalRef | None,
        *,
        action: AccessAction,
        resource_type: AccessResourceType,
        family: str | None = None,
        cursor: str | None = None,
        limit: int = 100,
        context: AccessAuditContext,
    ) -> AuthorizedResourcePage:
        if not self.provider_capabilities.safe_resource_filtering:
            raise AccessUnavailableError("safe_resource_filtering_unavailable")
        if limit < 1 or limit > 500:
            raise AccessInvalidRequestError("limit")
        _validate_resource_list_query(action=action, resource_type=resource_type, family=family)
        actor = _required_principal(principal)
        authorized_filter = await _access_call(
            self.provider.resolve_resource_filter(
                ResourceSearchRequest(
                    subject=actor,
                    action=action,
                    resource_type=resource_type,
                    family=family,
                    context=context,
                )
            )
        )
        _validate_resource_filter(
            authorized_filter,
            action=action,
            resource_type=resource_type,
            family=family,
            deployment_id=self.deployment_id,
        )
        ordered = tuple(sorted(authorized_filter.exact_resources, key=lambda resource: resource.key))
        after_key = _decode_cursor(cursor)
        visible = ordered if after_key is None else tuple(resource for resource in ordered if resource.key > after_key)
        items = visible[:limit]
        next_cursor = _encode_cursor(items[-1].key) if len(visible) > len(items) else None
        return AuthorizedResourcePage(items=items, total=len(ordered), next_cursor=next_cursor)

    async def list_bindings(
        self,
        *,
        subject: PrincipalRef | None = None,
        resource: ResourceRef | None = None,
        include_revoked: bool = False,
    ) -> tuple[AccessBinding, ...]:
        relationships = self._relationships()
        return await _access_call(
            relationships.list_bindings(
                subject=subject,
                resource=resource,
                include_revoked=include_revoked,
            )
        )

    async def list_audit(
        self,
        *,
        resource: ResourceRef | None = None,
        after: int | None = None,
        limit: int = 100,
    ) -> tuple[AccessAuditEvent, ...]:
        return await _access_call(self.audit.list_audit(resource=resource, after=after, limit=limit))

    async def create_binding(
        self,
        principal: PrincipalRef | None,
        request: CreateBinding,
        *,
        context: AccessAuditContext,
        validate_resource: Callable[[ResourceRef], Awaitable[None]] | None = None,
    ) -> AccessBinding:
        validate_binding_role(request.resource, request.role, deployment_id=self.deployment_id)
        now = self._clock()
        if request.expires_at is not None and request.expires_at <= now:
            raise AccessInvalidRequestError("binding-expired")
        action, administrative_resource = _administrative_check(request.resource)
        actor = _required_principal(principal)
        await self.require(actor, action, administrative_resource, context=context)
        if validate_resource is not None:
            await validate_resource(request.resource)
        candidate = AccessBinding(
            binding_id=str(uuid4()),
            subject=request.subject,
            resource=request.resource,
            role=request.role,
            granted_by=actor,
            reason=request.reason,
            created_at=now,
            expires_at=request.expires_at,
            state=AccessBindingState.ACTIVE,
            version=1,
            policy_revision="pending",
            idempotency_key=request.idempotency_key,
        )
        created = await _access_call(self._relationships().create_binding(candidate))
        await _access_call(self._record_relationship(created, principal=actor, action=action, context=context))
        return created

    async def revoke_binding(
        self,
        principal: PrincipalRef | None,
        binding_id: str,
        *,
        expected_version: int,
        context: AccessAuditContext,
    ) -> AccessBinding:
        actor = _required_principal(principal)
        relationships = self._relationships()
        binding = await _access_call(relationships.get_binding(binding_id))
        if binding is None:
            raise AccessDeniedError
        action, administrative_resource = _administrative_check(binding.resource)
        await self.require(actor, action, administrative_resource, context=context)
        revoked = await _access_call(
            relationships.revoke_binding(
                binding_id,
                expected_version=expected_version,
                revoked_at=self._clock(),
                revoked_by=actor,
            )
        )
        await _access_call(self._record_relationship(revoked, principal=actor, action=action, context=context))
        return revoked

    def _relationships(self) -> RelationshipWriter:
        if self.relationships is None or not self.provider_capabilities.relationship_management:
            raise AccessUnavailableError("relationship_management_unavailable")
        return self.relationships

    async def _record_decision(
        self,
        principal: PrincipalRef,
        action: AccessAction,
        resource: ResourceRef,
        decision: AccessDecision,
        *,
        context: AccessAuditContext,
    ) -> None:
        await self.audit.append_audit(
            AccessAuditEvent(
                cursor=None,
                event_id=str(uuid4()),
                occurred_at=self._clock(),
                request_id=context.request_id,
                transport=context.transport,
                operation=context.operation,
                principal=principal,
                action=action,
                resource=resource,
                allowed=decision.allowed,
                reason_code=decision.reason_code,
                policy_revision=decision.policy_revision,
            )
        )

    async def _record_relationship(
        self,
        binding: AccessBinding,
        *,
        principal: PrincipalRef,
        action: AccessAction,
        context: AccessAuditContext,
    ) -> None:
        await self.audit.append_audit(
            AccessAuditEvent(
                cursor=None,
                event_id=str(uuid4()),
                occurred_at=self._clock(),
                request_id=context.request_id,
                transport=context.transport,
                operation=context.operation,
                principal=principal,
                action=action,
                resource=binding.resource,
                allowed=True,
                reason_code="binding-created" if binding.state is AccessBindingState.ACTIVE else "binding-revoked",
                policy_revision=binding.policy_revision,
                binding_id=binding.binding_id,
                target=binding.subject,
                role=binding.role,
            )
        )


def _validate_resource_list_query(
    *,
    action: AccessAction,
    resource_type: AccessResourceType,
    family: str | None,
) -> None:
    if action is AccessAction.ACCESS_SELF or (family is not None and resource_type is not AccessResourceType.ARTIFACT):
        raise AccessInvalidRequestError("action-resource")
    allowed_actions = {
        AccessResourceType.SERVER: {AccessAction.SERVER_OBSERVE, AccessAction.SERVER_ADMIN},
        AccessResourceType.SCOPE: {
            AccessAction.SCOPE_READ,
            AccessAction.SCOPE_CONTRIBUTE,
            AccessAction.SCOPE_REVIEW,
            AccessAction.SCOPE_DELEGATE,
            AccessAction.SCOPE_ADMIN,
        },
    }
    if resource_type is not AccessResourceType.ARTIFACT:
        if action not in allowed_actions[resource_type]:
            raise AccessInvalidRequestError("action-resource")
        return
    if family is None:
        if not any(profile.enabled and action in profile.actions for profile in ARTIFACT_FAMILY_PROFILES.values()):
            raise AccessInvalidRequestError("action-resource")
        return
    profile = ARTIFACT_FAMILY_PROFILES.get(family)
    if profile is None:
        raise AccessInvalidRequestError("artifact-family")
    if not profile.enabled:
        raise AccessInvalidRequestError("artifact-family-disabled")
    if action not in profile.actions:
        raise AccessInvalidRequestError("action-resource")


def _binding_covers(binding: ResourceRef, requested: ResourceRef) -> bool:
    if binding == requested:
        return True
    if binding.type is AccessResourceType.SERVER:
        return True
    return (
        binding.type is AccessResourceType.SCOPE
        and requested.type is AccessResourceType.ARTIFACT
        and binding.scope_id == requested.scope_id
    )


def _binding_decision(
    bindings: Sequence[AccessBinding],
    action: AccessAction,
    resource: ResourceRef,
    *,
    policy_revision: str,
) -> AccessDecision:
    for binding in bindings:
        if action in ROLE_ACTIONS[binding.role] and _binding_covers(binding.resource, resource):
            return AccessDecision(True, "role-binding", policy_revision)
    return AccessDecision(False, "no-matching-binding", policy_revision)


def _administrative_check(resource: ResourceRef) -> tuple[AccessAction, ResourceRef]:
    if resource.type is AccessResourceType.SERVER:
        return AccessAction.SERVER_ADMIN, resource
    if resource.type is AccessResourceType.SCOPE:
        return AccessAction.SCOPE_ADMIN, resource
    parent = resource.parent_scope
    if parent is None:
        raise AccessInvalidRequestError("artifact-reference")
    profile = artifact_family_profile(resource)
    action = AccessAction.SCOPE_DELEGATE if profile.family == "handoff" else AccessAction.SCOPE_ADMIN
    return action, parent


def _resource_is_parent(resource: ResourceRef, child_type: AccessResourceType) -> bool:
    if resource.type is AccessResourceType.SERVER:
        return child_type is not AccessResourceType.SERVER
    return resource.type is AccessResourceType.SCOPE and child_type is AccessResourceType.ARTIFACT


def _validate_resource_filter(
    value: AuthorizedResourceFilter,
    *,
    action: AccessAction,
    resource_type: AccessResourceType,
    family: str | None,
    deployment_id: str,
) -> None:
    if len(value.exact_resources) + len(value.parent_constraints) > _MAX_AUTHORIZED_FILTER_IDENTITIES:
        raise AccessUnavailableError("safe_resource_filtering_unavailable")
    if len({resource.key for resource in value.exact_resources}) != len(value.exact_resources):
        raise AccessUnavailableError("safe_resource_filtering_unavailable")
    for resource in value.exact_resources:
        if resource.type is not resource_type or (family is not None and resource.family != family):
            raise AccessUnavailableError("safe_resource_filtering_unavailable")
        validate_action_resource(action, resource, deployment_id=deployment_id)
    for resource in value.parent_constraints:
        if not _resource_is_parent(resource, resource_type):
            raise AccessUnavailableError("safe_resource_filtering_unavailable")


def _validate_provider_decision(value: object) -> None:
    if not isinstance(value, AccessDecision) or not isinstance(value.allowed, bool):
        raise AccessUnavailableError
    reason = value.reason_code
    if (
        not reason
        or len(reason) > 64
        or not reason[0].isalnum()
        or any(not character.isascii() or not (character.isalnum() or character in "._-") for character in reason)
    ):
        raise AccessUnavailableError
    if value.policy_revision is not None and (not value.policy_revision or len(value.policy_revision) > 128):
        raise AccessUnavailableError


def _required_principal(principal: PrincipalRef | None) -> PrincipalRef:
    if principal is None:
        raise AccessIdentityRequiredError
    return principal


def _encode_cursor(resource_key: str) -> str:
    return urlsafe_b64encode(resource_key.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> str | None:
    if cursor is None or cursor == "":
        return None
    try:
        padded = f"{cursor}{'=' * (-len(cursor) % 4)}"
        return b64decode(padded.encode("ascii"), altchars=b"-_", validate=True).decode("utf-8")
    except (UnicodeDecodeError, ValueError) as error:
        raise AccessInvalidRequestError("cursor") from error


async def _access_call(awaitable: Awaitable[_T]) -> _T:
    try:
        return await awaitable
    except AccessControlError:
        raise
    except Exception as error:
        raise AccessUnavailableError from error


__all__ = (
    "AccessAuditContext",
    "AccessAuditStore",
    "AccessControlService",
    "AccessProviderCapabilities",
    "AccessRequest",
    "AuthorizationProvider",
    "AuthorizedResourceFilter",
    "AuthorizedResourcePage",
    "BuiltinAuthorizationProvider",
    "CreateBinding",
    "RelationshipWriter",
    "ResourceSearchRequest",
)
