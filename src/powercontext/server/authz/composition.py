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

"""Lifecycle assembly for the built-in relational Authorization Provider."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from powercontext.builtin.persistence.oceanbase import OceanBaseConfig, OceanBaseProfile
from powercontext.builtin.persistence.seekdb import SeekDBConfig, SeekDBProfile
from powercontext.builtin.persistence.sqlite import SQLiteConfig, SQLiteProfile
from powercontext.builtin.runtime.composition import BuiltinConfigurationError
from powercontext.builtin.runtime.config import DatabaseConfig
from powercontext.server.authz.models import PrincipalRef
from powercontext.server.authz.repository import ACCESS_TABLES, RelationalAccessRepository
from powercontext.server.authz.service import AccessControlService, BuiltinAuthorizationProvider


@asynccontextmanager
async def open_builtin_access_control(
    database: DatabaseConfig,
    *,
    bootstrap_administrators: Sequence[PrincipalRef] = (),
) -> AsyncIterator[AccessControlService]:
    """Open a Server-owned Access schema without coupling it to Runtime domains."""

    if isinstance(database, SQLiteConfig):
        profile_context = SQLiteProfile.open(database, tables=ACCESS_TABLES)
    elif isinstance(database, OceanBaseConfig):
        profile_context = OceanBaseProfile.open(database, tables=ACCESS_TABLES)
    elif isinstance(database, SeekDBConfig):
        profile_context = SeekDBProfile.open(database, tables=ACCESS_TABLES)
    else:
        raise BuiltinConfigurationError("database")
    async with profile_context as profile:
        repository = RelationalAccessRepository(profile.database)
        provider = BuiltinAuthorizationProvider(
            repository,
            bootstrap_administrators=bootstrap_administrators,
        )
        yield AccessControlService(provider, relationships=repository, audit=repository)


__all__ = ("open_builtin_access_control",)
