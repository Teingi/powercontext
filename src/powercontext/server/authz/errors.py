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

"""Stable failures owned by the Server Access Control boundary."""

from powercontext.errors import PowerContextError


class AccessControlError(PowerContextError):
    """Base failure for authentication and authorization operations."""


class AccessIdentityRequiredError(AccessControlError):
    """The request has no authenticated Principal."""

    def __init__(self) -> None:
        super().__init__("an authenticated Principal is required")


class AccessDeniedError(AccessControlError, PermissionError):
    """The current Principal cannot perform the requested action."""

    def __init__(self) -> None:
        super().__init__("the Principal is not authorized for this operation")


class AccessUnavailableError(AccessControlError, RuntimeError):
    """A required authorization dependency is unavailable."""

    def __init__(self, code: str = "access_unavailable") -> None:
        self.code = code
        messages = {
            "access_unavailable": "the authorization service is unavailable",
            "multi_requirement_check_unavailable": "multi-requirement Access checks are unavailable",
            "relationship_management_unavailable": "Access relationship management is unavailable",
            "safe_resource_filtering_unavailable": "safe Access resource filtering is unavailable",
        }
        super().__init__(messages.get(code, messages["access_unavailable"]))


class AccessConflictError(AccessControlError, RuntimeError):
    """A relationship mutation conflicts with current immutable state."""

    def __init__(self, code: str) -> None:
        self.code = code
        messages = {
            "binding-version": "the Access Binding version is stale",
            "idempotency-key": "the Access Binding idempotency key was reused with different input",
        }
        super().__init__(messages.get(code, "the Access Binding conflicts with current state"))


class AccessInvalidRequestError(AccessControlError, ValueError):
    """An Access API request violates the authorization contract."""

    def __init__(self, code: str) -> None:
        self.code = code
        messages = {
            "action-resource": "the action is not valid for this Access resource",
            "artifact-family": "the Artifact Family is not registered for Access sharing",
            "artifact-family-disabled": "the Artifact Family Access Profile is disabled",
            "artifact-reference": "an Artifact resource requires one exact ArtifactReference",
            "artifact-selector": "the Artifact Family does not accept this selector",
            "artifact-state": "the Artifact resource is not in a shareable lifecycle state",
            "binding-role": "the role cannot be bound to this resource type",
            "binding-expired": "expires_at must be later than the current Server time",
            "cursor": "the Access cursor is invalid",
            "deployment": "the Server resource does not identify this deployment",
            "handoff-reference": "a Handoff resource requires one exact Handoff ArtifactReference",
            "idempotency-key": "the Access Binding idempotency key is invalid",
            "memory-entry-selector": "a Memory Access resource requires one exact Memory Entry Version selector",
            "principal": "the Access Principal is invalid",
            "resource": "the Access resource is invalid",
            "receiver-principal": "an accepted Handoff receiver must match the authenticated Principal",
            "reason": "the Access Binding reason exceeds its limit",
        }
        super().__init__(messages.get(code, f"invalid Access request: {code}"))


__all__ = (
    "AccessConflictError",
    "AccessControlError",
    "AccessDeniedError",
    "AccessIdentityRequiredError",
    "AccessInvalidRequestError",
    "AccessUnavailableError",
)
