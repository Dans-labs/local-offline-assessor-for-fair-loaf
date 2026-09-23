from dataclasses import dataclass, replace

import pytest

from fair_offline_assessor import load_profile
from fair_offline_assessor.adapters import resolve_adapter
from fair_offline_assessor.models import ProfileError, ResourceRef


@dataclass
class ExampleAdapter:
    id: str
    version: str
    definitions: tuple

    def assess(self, request, profile):
        raise NotImplementedError


def test_adapter_selection_requires_exact_implementation_and_definitions():
    profile = load_profile("fusji-offline@3.5.1")
    definition = ResourceRef(
        id="fuji:metrics",
        version="3.5.1",
        kind="reference",
        format="yaml",
        digest="99c65ad9202a1f1dc8178c3457347f1a533b78329d3b53814687382874fad18a",
    )
    matching = ExampleAdapter("fuji", "1.0.0", (definition,))
    assert resolve_adapter(profile, adapters=(matching,)) is matching
    for candidates, code in (
        ((), "adapter_unavailable"),
        ((ExampleAdapter("fuji", "2.0.0", (definition,)),), "adapter_unavailable"),
        ((matching, matching), "adapter_conflict"),
        (
            (
                ExampleAdapter(
                    "fuji",
                    "1.0.0",
                    (definition.model_copy(update={"digest": "0" * 64}),),
                ),
            ),
            "unsupported_definitions",
        ),
    ):
        with pytest.raises(ProfileError) as exc:
            resolve_adapter(profile, adapters=candidates)
        assert exc.value.code == code


def test_adapter_versions_remain_independently_selectable():
    original = load_profile("fusji-offline@3.5.1")
    newer = replace(
        original,
        profile=original.profile.model_copy(update={"adapter_version": "2.0.0"}),
        info=original.info.model_copy(update={"adapter_version": "2.0.0"}),
    )
    first = ExampleAdapter("fuji", "1.0.0", ())
    second = ExampleAdapter("fuji", "2.0.0", ())
    unrelated = ExampleAdapter("example", "1.0.0", ())
    adapters = (unrelated, second, first)

    assert resolve_adapter(original, adapters=adapters) is first
    assert resolve_adapter(newer, adapters=adapters) is second
    assert resolve_adapter(original, adapters=adapters) is first
    with pytest.raises(ProfileError) as error:
        resolve_adapter(original, adapters=(unrelated, second))
    assert error.value.code == "adapter_unavailable"
