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

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, TypeVar
from uuid import uuid4

from powercontext.server.authz.errors import (
    AccessControlError,
    AccessDeniedError,
    AccessIdentityRequiredError,
    AccessInvalidRequestError,
    AccessUnavailableError,
)
from powercontext.server.authz.models import (
    ROLE_ACTIONS,
    ROLE_RESOURCE_TYPES,
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

_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class AuthorizedResourcePage:
    """One stable, non-discovering page of resources visible to a Principal."""

    items: tuple[ResourceRef, ...]
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class CreateBinding:
    """Validated intent to create one immutable Access Binding."""

    subject: PrincipalRef
    resource: ResourceRef
    role: AccessRole
    idempotency_key: str
    reason: str | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AccessAuditContext:
    """Low-sensitivity request facts attached to a decision audit event."""

    transport: str
    operation: str
    request_id: str | None = None


class AuthorizationProvider(Protocol):
    """Replaceable decision interface suitable for OpenFGA, Casbin, or Oso adapters."""

    async def check(
        self,
        principal: PrincipalRef,
        action: AccessAction,
        resource: ResourceRef,
    ) -> AccessDecision: ...

    async def check_batch(
        self,
        principal: PrincipalRef,
        checks: Sequence[tuple[AccessAction, ResourceRef]],
    ) -> tuple[AccessDecision, ...]: ...

    async def list_resources(
        self,
        principal: PrincipalRef,
        *,
        action: AccessAction,
        resource_type: AccessResourceType,
        cursor: str | None = None,
        limit: int = 100,
    ) -> AuthorizedResourcePage: ...


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

    async def list_audit(self, *, after: int | None = None, limit: int = 100) -> tuple[AccessAuditEvent, ...]: ...


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
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._bootstrap_administrators = frozenset(bootstrap_administrators)
        self._clock = clock or (lambda: datetime.now(UTC))

    async def check(
        self,
        principal: PrincipalRef,
        action: AccessAction,
        resource: ResourceRef,
    ) -> AccessDecision:
        revision = await self._repository.policy_revision()
        if action is AccessAction.ACCESS_SELF:
            return AccessDecision(True, "authenticated", revision)
        if principal in self._bootstrap_administrators:
            return AccessDecision(True, "bootstrap-admin", revision)
        bindings = await self._repository.active_bindings(principal, now=self._clock())
        return _binding_decision(bindings, action, resource, policy_revision=revision)

    async def check_batch(
        self,
        principal: PrincipalRef,
        checks: Sequence[tuple[AccessAction, ResourceRef]],
    ) -> tuple[AccessDecision, ...]:
        revision = await self._repository.policy_revision()
        if principal in self._bootstrap_administrators:
            return tuple(AccessDecision(True, "bootstrap-admin", revision) for _ in checks)
        bindings = await self._repository.active_bindings(principal, now=self._clock())
        return tuple(
            AccessDecision(True, "authenticated", revision)
            if action is AccessAction.ACCESS_SELF
            else _binding_decision(bindings, action, resource, policy_revision=revision)
            for action, resource in checks
        )

    async def list_resources(
        self,
        principal: PrincipalRef,
        *,
        action: AccessAction,
        resource_type: AccessResourceType,
        cursor: str | None = None,
        limit: int = 100,
    ) -> AuthorizedResourcePage:
        if limit < 1 or limit > 500:
            raise AccessInvalidRequestError("limit")
        if cursor not in {None, ""}:
            raise AccessInvalidRequestError("cursor")
        bindings = await self._repository.active_bindings(principal, now=self._clock())
        resources = {
            binding.resource.key: binding.resource
            for binding in bindings
            if binding.resource.type is resource_type and action in ROLE_ACTIONS[binding.role]
        }
        ordered = tuple(resources[key] for key in sorted(resources))
        return AuthorizedResourcePage(items=ordered[:limit])


class AccessControlService:
    """Fail-closed Access orchestration shared by HTTP and MCP transports."""

    def __init__(
        self,
        provider: AuthorizationProvider,
        *,
        relationships: RelationshipWriter,
        audit: AccessAuditStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.provider = provider
        self.relationships = relationships
        self.audit = audit
        self._clock = clock or (lambda: datetime.now(UTC))

    async def check(
        self,
        principal: PrincipalRef | None,
        action: AccessAction,
        resource: ResourceRef,
        *,
        context: AccessAuditContext,
    ) -> AccessDecision:
        if principal is None:
            raise AccessIdentityRequiredError
        decision = await _access_call(self.provider.check(principal, action, resource))
        await _access_call(self._record_decision(principal, action, resource, decision, context=context))
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
        if principal is None:
            raise AccessIdentityRequiredError
        decisions = await _access_call(self.provider.check_batch(principal, checks))
        if len(decisions) != len(checks):
            raise AccessUnavailableError
        for (action, resource), decision in zip(checks, decisions, strict=True):
            await _access_call(self._record_decision(principal, action, resource, decision, context=context))
        return decisions

    async def list_resources(
        self,
        principal: PrincipalRef | None,
        *,
        action: AccessAction,
        resource_type: AccessResourceType,
        cursor: str | None = None,
        limit: int = 100,
    ) -> AuthorizedResourcePage:
        actor = _required_principal(principal)
        return await _access_call(
            self.provider.list_resources(
                actor,
                action=action,
                resource_type=resource_type,
                cursor=cursor,
                limit=limit,
            )
        )

    async def list_bindings(
        self,
        *,
        subject: PrincipalRef | None = None,
        resource: ResourceRef | None = None,
        include_revoked: bool = False,
    ) -> tuple[AccessBinding, ...]:
        return await _access_call(
            self.relationships.list_bindings(
                subject=subject,
                resource=resource,
                include_revoked=include_revoked,
            )
        )

    async def list_audit(self, *, after: int | None = None, limit: int = 100) -> tuple[AccessAuditEvent, ...]:
        return await _access_call(self.audit.list_audit(after=after, limit=limit))

    async def create_binding(
        self,
        principal: PrincipalRef | None,
        request: CreateBinding,
        *,
        context: AccessAuditContext,
    ) -> AccessBinding:
        if ROLE_RESOURCE_TYPES[request.role] is not request.resource.type:
            raise AccessInvalidRequestError("binding-role")
        now = self._clock()
        if request.expires_at is not None and request.expires_at <= now:
            raise AccessInvalidRequestError("binding-expired")
        action, administrative_resource = _administrative_check(request.resource)
        actor = _required_principal(principal)
        await self.require(actor, action, administrative_resource, context=context)
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
        created = await _access_call(self.relationships.create_binding(candidate))
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
        binding = await _access_call(self.relationships.get_binding(binding_id))
        if binding is None:
            raise AccessDeniedError
        action, administrative_resource = _administrative_check(binding.resource)
        await self.require(actor, action, administrative_resource, context=context)
        revoked = await _access_call(
            self.relationships.revoke_binding(
                binding_id,
                expected_version=expected_version,
                revoked_at=self._clock(),
                revoked_by=actor,
            )
        )
        await _access_call(self._record_relationship(revoked, principal=actor, action=action, context=context))
        return revoked

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


def _binding_covers(binding: ResourceRef, requested: ResourceRef) -> bool:
    if binding == requested:
        return True
    if binding.type is AccessResourceType.SERVER:
        return True
    return (
        binding.type is AccessResourceType.SCOPE
        and requested.type is AccessResourceType.HANDOFF
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
        raise AccessInvalidRequestError("handoff-reference")
    return AccessAction.SCOPE_DELEGATE, parent


def _required_principal(principal: PrincipalRef | None) -> PrincipalRef:
    if principal is None:
        raise AccessIdentityRequiredError
    return principal


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
    "AuthorizationProvider",
    "AuthorizedResourcePage",
    "BuiltinAuthorizationProvider",
    "CreateBinding",
    "RelationshipWriter",
)
