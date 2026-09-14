from dataclasses import dataclass

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
    with pytest.raises(ProfileError, match="not available"):
        resolve_adapter(profile)
