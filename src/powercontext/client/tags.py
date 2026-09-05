# Copyright (c) 2026 OceanBase.
# SPDX-License-Identifier: Apache-2.0

"""Tag responses retain their server-issued optimistic concurrency validator."""

from dataclasses import dataclass

from powercontext.http._generated.models import ArtifactTagSet


@dataclass(frozen=True)
class ArtifactTagSetResponse:
    """A complete tag set and its opaque ETag, safe for a subsequent replacement."""

    tag_set: ArtifactTagSet
    etag: str
