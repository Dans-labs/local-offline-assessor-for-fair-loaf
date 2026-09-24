from hashlib import sha256

from pydantic import Field, JsonValue, TypeAdapter, ValidationError

from fair_offline_assessor.assessors.champion.v0_5_12.bindings import DEFINITIONS
from fair_offline_assessor.models import ProfileError, ResourceRef
from fair_offline_assessor.models.v1 import Model
from fair_offline_assessor.profiles import LoadedProfile


class TestDefinition(Model):
    id: str
    name: str
    metric: str
    indicators: str
    test_version: str
    source_path: str
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    principles: tuple[str, ...]
    requires: tuple[str, ...]


class ChampionDefinitions(Model):
    tests: tuple[TestDefinition, ...]
    references: dict[str, JsonValue]
    policy: dict[str, JsonValue]


def load_definitions(profile: LoadedProfile) -> ChampionDefinitions:
    """Verify compiled-in bindings, then parse fresh independent definitions."""
    resources = {}
    for definition in DEFINITIONS:
        matching = [r for r in profile.references if r.id == definition.id]
        content = profile.resources.get(definition.id)
        if (
            len(matching) != 1
            or matching[0].model_dump(include=set(ResourceRef.model_fields))
            != definition.model_dump()
            or content is None
            or sha256(content).hexdigest() != definition.digest
        ):
            raise ProfileError(
                "unsupported_definitions", f"Unsupported definition: {definition.id}"
            )
        resources[definition.id] = content
    try:
        objects = TypeAdapter(dict[str, JsonValue])
        # Provenance is pinned and validated even though evaluators do not use it.
        objects.validate_json(resources["champion:upstream"])
        return ChampionDefinitions(
            tests=TypeAdapter(tuple[TestDefinition, ...]).validate_json(
                resources["champion:tests"]
            ),
            references=objects.validate_json(resources["champion:references"]),
            policy=objects.validate_json(resources["champion:offline-policy"]),
        )
    except ValidationError as exc:
        raise ProfileError(
            "invalid_definitions", "Invalid Champion definitions"
        ) from exc
