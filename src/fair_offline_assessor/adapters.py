from collections.abc import Mapping
from typing import Protocol

from fair_offline_assessor.models import (
    AssessmentInput,
    AssessmentResult,
    ProfileError,
    ResourceRef,
)
from fair_offline_assessor.profiles import LoadedProfile


class AssessorAdapter(Protocol):
    id: str
    version: str
    definitions: tuple[ResourceRef, ...]

    def assess(
        self, request: AssessmentInput | Mapping[str, object], profile: LoadedProfile
    ) -> AssessmentResult:
        """Assess supplied evidence using this implementation's checks and scoring."""
        ...


def resolve_adapter(
    profile: LoadedProfile, *, adapters: tuple[AssessorAdapter, ...] = ()
) -> AssessorAdapter:
    """Select an available implementation with matching pinned definitions."""
    selection = (profile.profile.adapter, profile.profile.adapter_version)
    matches = [
        adapter for adapter in adapters if (adapter.id, adapter.version) == selection
    ]
    if not matches:
        raise ProfileError("adapter_unavailable", f"Adapter not available: {selection}")
    if len(matches) != 1:
        raise ProfileError("adapter_conflict", f"Multiple implementations: {selection}")
    adapter = matches[0]
    resources = {reference.id: reference for reference in profile.references}
    for definition in adapter.definitions:
        actual = resources.get(definition.id)
        if (
            actual is None
            or actual.model_dump(include=set(ResourceRef.model_fields))
            != definition.model_dump()
        ):
            raise ProfileError(
                "unsupported_definitions", f"Unsupported definition: {definition.id}"
            )
    return adapter
