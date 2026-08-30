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

    def __init__(self) -> None:
        super().__init__("the authorization service is unavailable")


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
            "binding-role": "the role cannot be bound to this resource type",
            "binding-expired": "expires_at must be later than the current Server time",
            "handoff-reference": "a Handoff resource requires one exact Handoff ArtifactReference",
            "principal": "the Access Principal is invalid",
            "resource": "the Access resource is invalid",
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
