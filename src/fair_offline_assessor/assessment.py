"""Single-engine offline F-UJI API."""
from collections.abc import Mapping
from functools import lru_cache
from pydantic import JsonValue
from fair_offline_assessor.assessors.fuji.assessment import FujiAdapter
from fair_offline_assessor.models import AssessmentInput, AssessmentResult, ProfileError
from fair_offline_assessor.models.v1 import JsonObject
from fair_offline_assessor.profiles import ProfileProvider, load_profile

FUJI_VERSION = "3.5.1"
PROFILE_ID = f"fusji-offline@{FUJI_VERSION}"

@lru_cache(maxsize=1)
def _profile():
    """Read and verify the pinned profile and assets once per process."""
    return load_profile(PROFILE_ID)

class FairAssessor:
    """Reusable assessor; F-UJI is the sole supported engine."""
    def __init__(self) -> None:
        self._profile = _profile()
        self._adapter = FujiAdapter()

    def assess(
        self,
        *,
        metadata: JsonValue,
        metadata_format: str | None = None,
        subject: str | None = None,
        metadata_url: str | None = None,
        local_contexts: dict[str, JsonObject] | None = None,
        target_identifier: str | None = None,
    ) -> AssessmentResult:
        request = {
            "metadata": metadata,
            "metadata_format": metadata_format,
            "subject": subject,
            "metadata_url": metadata_url,
            "local_contexts": local_contexts if local_contexts is not None else {},
        }
        if target_identifier is not None:
            request["target_identifier"] = target_identifier
        return self._adapter.assess(request, self._profile)

    def assess_many(self, datasets):
        """Stream results without materialising the input collection."""
        for metadata in datasets:
            yield self.assess(metadata=metadata)

class Assessor(FairAssessor):
    """Compatibility alias for the former Assessor('FUJI') API."""
    def __init__(self, name: str = "FUJI", *, version: str | None = None):
        if name.upper() != "FUJI":
            raise ProfileError("assessor_not_found", f"Only FUJI is supported: {name}")
        if version is not None and version != FUJI_VERSION:
            raise ProfileError("assessor_version_not_found", f"Unsupported F-UJI version: {version}")
        super().__init__()

def assess(
    request: AssessmentInput | Mapping[str, object],
    *,
    profile: str = PROFILE_ID,
    provider: ProfileProvider | None = None,
) -> AssessmentResult:
    """One-shot compatibility entry point. Prefer reusing FairAssessor."""
    if profile != PROFILE_ID:
        raise ProfileError("profile_not_found", f"Only {PROFILE_ID} is supported")
    selected = (
        _profile() if provider is None else load_profile(profile, provider=provider)
    )
    return FujiAdapter().assess(request, selected)
