from collections.abc import Mapping

from pydantic import JsonValue

from fair_offline_assessor._fuji_assessment import FujiAdapter
from fair_offline_assessor.adapters import resolve_adapter
from fair_offline_assessor.models import (
    AssessmentInput,
    AssessmentResult,
    Capture,
    ProfileError,
)
from fair_offline_assessor.models.v1 import JsonObject
from fair_offline_assessor.profiles import ProfileProvider, load_profile

_DEFAULT_PROFILES = {"FUJI": "fusji-offline@3.5.1"}


class Assessor:
    def __init__(self, name: str, *, version: str | None = None) -> None:
        """Select an assessor by name and optional configuration version."""
        name = name.upper()
        try:
            selection = _DEFAULT_PROFILES[name]
        except KeyError as exc:
            raise ProfileError(
                "assessor_not_found", f"Assessor not found: {name}"
            ) from exc
        if version is not None:
            selection = f"{selection.rsplit('@', 1)[0]}@{version}"
        try:
            self._profile = load_profile(selection)
        except ProfileError as exc:
            if exc.code in {"invalid_selection", "profile_not_found"}:
                raise ProfileError(
                    "assessor_version_not_found",
                    f"Assessor version not found: {name}@{version}",
                ) from exc
            raise
        self._adapter = resolve_adapter(self._profile, adapters=(FujiAdapter(),))

    def assess(
        self,
        *,
        metadata: JsonValue,
        subject: str | None = None,
        metadata_url: str | None = None,
        captures: tuple[Capture, ...] = (),
        local_contexts: dict[str, JsonObject] | None = None,
    ) -> AssessmentResult:
        """Assess supplied JSON-LD and optional evidence without fetching URLs."""
        request = {
            "metadata": metadata,
            "subject": subject,
            "metadata_url": metadata_url,
            "captures": captures,
            "local_contexts": local_contexts if local_contexts is not None else {},
        }
        return self._adapter.assess(request, self._profile)


def assess(
    request: AssessmentInput | Mapping[str, object],
    *,
    profile: str,
    provider: ProfileProvider | None = None,
) -> AssessmentResult:
    """Assess supplied evidence offline using an exact profile ID@version."""
    loaded = load_profile(profile, provider=provider)
    adapter = resolve_adapter(loaded, adapters=(FujiAdapter(),))
    return adapter.assess(request, loaded)
