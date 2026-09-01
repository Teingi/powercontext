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

"""Server-owned authentication and authorization building blocks."""

from powercontext.server.authz.authzen import AuthZenAuthorizationProvider
from powercontext.server.authz.casbin import CasbinAuthorizationProvider
from powercontext.server.authz.errors import (
    AccessConflictError,
    AccessControlError,
    AccessDeniedError,
    AccessIdentityRequiredError,
    AccessInvalidRequestError,
    AccessUnavailableError,
)
from powercontext.server.authz.models import (
    DEFAULT_DEPLOYMENT_ID,
    PUBLIC_ACCESS_ACTIONS,
    AccessAction,
    AccessArtifactReference,
    AccessAuditEvent,
    AccessBinding,
    AccessBindingState,
    AccessDecision,
    AccessResourceType,
    AccessRole,
    MemoryEntrySelector,
    PrincipalRef,
    ResourceRef,
)
from powercontext.server.authz.service import (
    AccessAuditContext,
    AccessAuditStore,
    AccessControlService,
    AccessProviderCapabilities,
    AccessRequest,
    AuthorizationProvider,
    AuthorizedResourceFilter,
    AuthorizedResourcePage,
    BuiltinAuthorizationProvider,
    CreateBinding,
    RelationshipWriter,
    ResourceSearchRequest,
)

__all__ = (
    "DEFAULT_DEPLOYMENT_ID",
    "PUBLIC_ACCESS_ACTIONS",
    "AccessAction",
    "AccessArtifactReference",
    "AccessAuditContext",
    "AccessAuditEvent",
    "AccessAuditStore",
    "AccessBinding",
    "AccessBindingState",
    "AccessConflictError",
    "AccessControlError",
    "AccessControlService",
    "AccessDecision",
    "AccessDeniedError",
    "AccessIdentityRequiredError",
    "AccessInvalidRequestError",
    "AccessProviderCapabilities",
    "AccessRequest",
    "AccessResourceType",
    "AccessRole",
    "AccessUnavailableError",
    "AuthZenAuthorizationProvider",
    "AuthorizationProvider",
    "AuthorizedResourceFilter",
    "AuthorizedResourcePage",
    "BuiltinAuthorizationProvider",
    "CasbinAuthorizationProvider",
    "CreateBinding",
    "MemoryEntrySelector",
    "PrincipalRef",
    "RelationshipWriter",
    "ResourceRef",
    "ResourceSearchRequest",
)
