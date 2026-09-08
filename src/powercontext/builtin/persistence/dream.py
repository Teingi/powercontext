# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Durable Dream idempotency, keyset paging, leases, and fencing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, insert, or_, select, true, update
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.builtin.dream.models import (
    CreateDreamRunRequest,
    DreamError,
    DreamRecord,
    DreamRun,
    DreamRunPage,
    ListDreamRunsRequest,
)
from powercontext.builtin.evidence.models import content_digest
from powercontext.builtin.persistence.codec import dump_model, load_model, stored_bytes
from powercontext.builtin.persistence.tables import DREAM_RUNS_TABLE as RUNS


def ticks(value: datetime) -> int:
    return int(value.timestamp() * 1_000_000)


async def database_now(connection: AsyncConnection) -> datetime:
    if connection.dialect.name == "mysql":
        value = await connection.scalar(select(func.utc_timestamp(6)))
    else:
        value = await connection.scalar(select(func.strftime("%Y-%m-%dT%H:%M:%f", "now")))
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=UTC)


def _payload(record: DreamRecord) -> bytes:
    return dump_model(record, kind="dream", name="record")


def _decode(value: object) -> DreamRecord:
    return load_model(DreamRecord, stored_bytes(value, column="dream"), kind="dream", name="record")


class DreamRepository:
    async def find_request(
        self,
        connection: AsyncConnection,
        scope_id: str,
        principal_id: str,
        request: CreateDreamRunRequest,
        *,
        current: bool = False,
    ) -> DreamRecord | None:
        statement = select(RUNS.c.payload).where(
            RUNS.c.scope_id == scope_id,
            RUNS.c.principal_key == content_digest(principal_id.encode())[7:],
            RUNS.c.idempotency_key == request.idempotency_key,
        )
        if current:
            statement = statement.with_for_update()
        row = await connection.scalar(statement)
        if row is None:
            return None
        record = _decode(row)
        if record.request.digest() != request.digest():
            raise DreamError("idempotency_conflict")
        return record

    async def create(self, connection: AsyncConnection, record: DreamRecord) -> DreamRecord:
        run = record.run
        # Admission already holds the Scope write lock and rechecks the durable key.
        # A plain insert avoids driver-dependent nested transaction semantics.
        await connection.execute(
            insert(RUNS).values(
                scope_id=run.scope_id,
                run_id=run.run_id,
                principal_key=content_digest(record.principal_id.encode())[7:],
                idempotency_key=record.request.idempotency_key,
                request_digest=record.request.digest(),
                operation=run.operation,
                status=run.status,
                accepted_at=ticks(run.accepted_at),
                generation=0,
                lease_expires_at=None,
                payload=_payload(record),
            )
        )
        return record

    async def get(
        self,
        connection: AsyncConnection,
        scope_id: str,
        run_id: str,
        *,
        current: bool = False,
    ) -> DreamRecord:
        statement = select(RUNS.c.payload).where(
            RUNS.c.scope_id == scope_id,
            RUNS.c.run_id == run_id,
        )
        if current:
            statement = statement.with_for_update()
        value = await connection.scalar(statement)
        if value is None:
            raise DreamError("dream_not_found")
        return _decode(value)

    async def list(
        self,
        connection: AsyncConnection,
        scope_id: str,
        request: ListDreamRunsRequest,
    ) -> DreamRunPage:
        statement = select(RUNS.c.payload).where(RUNS.c.scope_id == scope_id)
        if request.status is not None:
            statement = statement.where(RUNS.c.status == request.status)
        if request.operation is not None:
            statement = statement.where(RUNS.c.operation == request.operation)
        if request.cursor is not None:
            stamp, run_id = _parse_cursor(request.cursor)
            statement = statement.where(
                or_(
                    RUNS.c.accepted_at < stamp,
                    and_(RUNS.c.accepted_at == stamp, RUNS.c.run_id < run_id),
                )
            )
        rows = (
            await connection.scalars(
                statement.order_by(
                    RUNS.c.accepted_at.desc(),
                    RUNS.c.run_id.desc(),
                ).limit(request.limit + 1)
            )
        ).all()
        runs = tuple(_decode(row).run for row in rows[: request.limit])
        cursor = None
        if len(rows) > request.limit and runs:
            cursor = f"{ticks(runs[-1].accepted_at)}:{runs[-1].run_id}"
        return DreamRunPage(runs=runs, next_cursor=cursor)

    async def pending_count(self, connection: AsyncConnection, scope_id: str) -> int:
        value = await connection.scalar(
            select(func.count())
            .select_from(RUNS)
            .where(
                RUNS.c.scope_id == scope_id,
                RUNS.c.status.in_(("queued", "running")),
            )
        )
        return int(value or 0)

    async def ready(
        self,
        connection: AsyncConnection,
        *,
        limit: int,
        trusted_runtime_only: bool = False,
    ) -> tuple[tuple[str, str], ...]:
        now = await database_now(connection)
        rows = (
            await connection.execute(
                select(RUNS.c.scope_id, RUNS.c.run_id)
                .where(
                    RUNS.c.principal_key == content_digest(b"runtime")[7:] if trusted_runtime_only else true(),
                    or_(
                        RUNS.c.status == "queued",
                        and_(RUNS.c.status == "running", RUNS.c.lease_expires_at <= ticks(now)),
                    ),
                )
                .order_by(RUNS.c.accepted_at, RUNS.c.run_id)
                .limit(limit)
            )
        ).all()
        return tuple((str(row.scope_id), str(row.run_id)) for row in rows)

    async def claim(
        self,
        connection: AsyncConnection,
        scope_id: str,
        run_id: str,
        *,
        owner: str,
        lease_seconds: float,
    ) -> DreamRecord | None:
        now = await database_now(connection)
        eligible = and_(
            RUNS.c.scope_id == scope_id,
            RUNS.c.run_id == run_id,
            or_(
                RUNS.c.status == "queued",
                and_(RUNS.c.status == "running", RUNS.c.lease_expires_at <= ticks(now)),
            ),
        )
        # This conditional write serializes claimants on both SQLite and OceanBase.
        result = await connection.execute(update(RUNS).where(eligible).values(generation=RUNS.c.generation + 1))
        if result.rowcount != 1:
            return None
        record = await self.get(connection, scope_id, run_id, current=True)
        deadline = record.deadline_at or now + timedelta(seconds=record.run.budget.timeout_seconds)
        if now >= deadline or record.run.attempt_count >= record.run.budget.max_model_calls:
            exhausted = record.model_copy(
                update={
                    "generation": record.generation + 1,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "run": record.run.model_copy(
                        update={
                            "status": "failed",
                            "error": "budget_exceeded",
                            "completed_at": now,
                        }
                    ),
                }
            )
            await self._store(connection, exhausted)
            return exhausted
        run = record.run.model_copy(
            update={
                "status": "running",
                "started_at": record.run.started_at or now,
                "attempt_count": record.run.attempt_count + 1,
            }
        )
        claimed = record.model_copy(
            update={
                "run": run,
                "generation": record.generation + 1,
                "lease_owner": owner,
                "deadline_at": deadline,
                "lease_expires_at": min(deadline, now + timedelta(seconds=lease_seconds)),
            }
        )
        await self._store(connection, claimed)
        return claimed

    async def lock_owned(self, connection: AsyncConnection, record: DreamRecord) -> None:
        now = await database_now(connection)
        result = await connection.execute(
            update(RUNS)
            .where(
                RUNS.c.scope_id == record.run.scope_id,
                RUNS.c.run_id == record.run.run_id,
                RUNS.c.status == "running",
                RUNS.c.generation == record.generation,
                RUNS.c.lease_expires_at > ticks(now),
            )
            .values(generation=RUNS.c.generation)
        )
        if result.rowcount != 1:
            raise DreamError("lease_lost")

    async def checkpoint(self, connection: AsyncConnection, record: DreamRecord) -> None:
        await self.lock_owned(connection, record)
        if record.run.status == "running":
            current = await self.get(connection, record.run.scope_id, record.run.run_id, current=True)
            record = record.model_copy(update={"lease_expires_at": current.lease_expires_at})
        await self._store(connection, record)

    async def renew(
        self,
        connection: AsyncConnection,
        record: DreamRecord,
        *,
        lease_seconds: float,
    ) -> DreamRecord:
        await self.lock_owned(connection, record)
        now = await database_now(connection)
        if record.deadline_at is None or now >= record.deadline_at:
            raise DreamError("budget_exceeded")
        current = await self.get(connection, record.run.scope_id, record.run.run_id, current=True)
        renewed = current.model_copy(
            update={
                "lease_expires_at": min(record.deadline_at, now + timedelta(seconds=lease_seconds)),
            }
        )
        await self._store(connection, renewed)
        return renewed

    async def finish(self, connection: AsyncConnection, record: DreamRecord, run: DreamRun) -> None:
        await self.lock_owned(connection, record)
        terminal = record.model_copy(update={"run": run, "lease_owner": None, "lease_expires_at": None})
        await self._store(connection, terminal)

    async def _store(self, connection: AsyncConnection, record: DreamRecord) -> None:
        await connection.execute(
            update(RUNS)
            .where(
                RUNS.c.scope_id == record.run.scope_id,
                RUNS.c.run_id == record.run.run_id,
            )
            .values(
                status=record.run.status,
                generation=record.generation,
                lease_expires_at=None if record.lease_expires_at is None else ticks(record.lease_expires_at),
                payload=_payload(record),
            )
        )


def _parse_cursor(cursor: str) -> tuple[int, str]:
    try:
        stamp, run_id = cursor.split(":", 1)
        value = int(stamp)
    except ValueError as error:
        raise DreamError("invalid_cursor") from error
    if value < 0 or not run_id or len(run_id) > 64:
        raise DreamError("invalid_cursor")
    return value, run_id
