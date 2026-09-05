# Copyright (c) 2026 OceanBase.
# SPDX-License-Identifier: Apache-2.0

import pytest

from powercontext.builtin.records import InvalidBaseAccessRequestError
from powercontext.builtin.tags import ArtifactTagTarget, TagFilter, normalize_tags, tag_set


def test_unicode_normalization_preserves_display_and_canonical_order() -> None:
    assert normalize_tags(("STRASSE", "Cafe\u0301", "中文")) == {
        "café": "Cafe\u0301",
        "strasse": "STRASSE",
        "中文": "中文",
    }
    assert TagFilter(tags=("Straße",)).keys == ("strasse",)
    target = ArtifactTagTarget(family="skill", artifact_id="skill-a")
    assert tag_set("scope", target, ("B", "A")) == tag_set("scope", target, ("A", "B"))
    assert tag_set("scope", target, ()).etag != tag_set("other", target, ()).etag


@pytest.mark.parametrize(
    "tags",
    [
        ("",),
        (" label",),
        ("label\n",),
        ("a\x00b",),
        ("\ud800",),
        ("\u0378",),
        ("x" * 65,),
        ("Café", "Cafe\u0301"),
        ("Straße", "STRASSE"),
    ],
)
def test_invalid_or_duplicate_tags_fail_without_echoing_input(tags: tuple[str, ...]) -> None:
    with pytest.raises(InvalidBaseAccessRequestError) as error:
        normalize_tags(tags)
    assert error.value.field == "tags"
    assert str(error.value) in {
        "tags contains an invalid label",
        "tags contains an invalid or duplicate normalized label",
    }
