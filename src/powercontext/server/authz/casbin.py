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

"""Embedded Casbin adapter over the canonical PowerContext Binding Store."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

import casbin

from powercontext.server.authz.errors import AccessInvalidRequestError
from powercontext.server.authz.models import (
    DEFAULT_DEPLOYMENT_ID,
    ROLE_ACTIONS,
    AccessAction,
    AccessBinding,
    AccessDecision,
    AccessResourceType,
    PrincipalRef,
    ResourceRef,
)
from powercontext.server.authz.service import (
    AccessRepository,
    AccessRequest,
    AuthorizedResourceFilter,
    ResourceSearchRequest,
)

_MODEL = """
[request_definition]
r = sub, act, obj, scope, deployment

[policy_definition]
p = sub, act, obj, scope, deployment

[policy_effect]
e = some(where (p.eft == allow))

[matchers]
m = r.sub == p.sub && (p.act == "*" || r.act == p.act) && (p.obj == "*" || r.obj == p.obj) && (p.scope == "*" || r.scope == p.scope) && r.deployment == p.deployment
"""


class CasbinAuthorizationProvider:
    """Evaluate canonical role bindings with an embedded Casbin policy model.

    The relational Binding Store is the persistent Casbin adapter: each decision materializes only
    the current Principal's active, opaque relationships into a short-lived enforcer. This avoids
    copying business content or maintaining a second policy shadow while preserving the same CAS,
    idempotency, expiry, audit, and safe-list semantics as the built-in reference provider.
    """

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
        decisions = await self.check_batch((request,))
        return decisions[0]

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
        bindings = await self._repository.active_bindings(principal, now=self._clock())
        enforcer = _enforcer(
            principal,
            bindings,
            bootstrap=principal in self._bootstrap_administrators,
            deployment_id=self._deployment_id,
        )
        decisions: list[AccessDecision] = []
        for request in requests:
            if request.action is AccessAction.ACCESS_SELF:
                decisions.append(AccessDecision(True, "authenticated", revision))
                continue
            allowed = bool(enforcer.enforce(*_casbin_request(request, self._deployment_id)))
            decisions.append(
                AccessDecision(
                    allowed=allowed,
                    reason_code="casbin-policy" if allowed else "no-matching-policy",
                    policy_revision=revision,
                )
            )
        return tuple(decisions)

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

    async def get_binding(self, binding_id: str) -> AccessBinding | None:
        return await self._repository.get_binding(binding_id)

    async def list_bindings(
        self,
        *,
        subject: PrincipalRef | None = None,
        resource: ResourceRef | None = None,
        include_revoked: bool = False,
    ) -> tuple[AccessBinding, ...]:
        return await self._repository.list_bindings(
            subject=subject,
            resource=resource,
            include_revoked=include_revoked,
        )

    async def create_binding(self, binding: AccessBinding) -> AccessBinding:
        return await self._repository.create_binding(binding)

    async def revoke_binding(
        self,
        binding_id: str,
        *,
        expected_version: int,
        revoked_at: datetime,
        revoked_by: PrincipalRef,
    ) -> AccessBinding:
        return await self._repository.revoke_binding(
            binding_id,
            expected_version=expected_version,
            revoked_at=revoked_at,
            revoked_by=revoked_by,
        )


def _enforcer(
    principal: PrincipalRef,
    bindings: Sequence[AccessBinding],
    *,
    bootstrap: bool,
    deployment_id: str,
) -> casbin.Enforcer:
    model = casbin.Model()
    model.load_model_from_text(_MODEL)
    enforcer = casbin.Enforcer(model)
    policies: list[list[str]] = []
    if bootstrap:
        policies.append([principal.key, "*", "*", "*", deployment_id])
    for binding in bindings:
        obj, scope, deployment = _casbin_policy_resource(binding.resource, deployment_id)
        policies.extend([principal.key, action.value, obj, scope, deployment] for action in ROLE_ACTIONS[binding.role])
    if policies:
        enforcer.add_policies(policies)
    return enforcer


def _casbin_request(request: AccessRequest, deployment_id: str) -> tuple[str, str, str, str, str]:
    resource = request.resource
    return (
        request.subject.key,
        request.action.value,
        resource.key,
        resource.scope_id or "",
        resource.deployment_id or deployment_id,
    )


def _casbin_policy_resource(resource: ResourceRef, deployment_id: str) -> tuple[str, str, str]:
    if resource.type is AccessResourceType.SERVER:
        return (
            "*" if resource.deployment_id == deployment_id else resource.key,
            "*",
            resource.deployment_id or deployment_id,
        )
    if resource.type is AccessResourceType.SCOPE:
        return "*", resource.scope_id or "", deployment_id
    return resource.key, resource.scope_id or "", deployment_id


def _resource_is_parent(resource: ResourceRef, requested_type: AccessResourceType) -> bool:
    return resource.type is AccessResourceType.SERVER or (
        resource.type is AccessResourceType.SCOPE and requested_type is AccessResourceType.ARTIFACT
    )


__all__ = ("CasbinAuthorizationProvider",)
