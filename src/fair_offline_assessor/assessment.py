from fair_offline_assessor._fuji_assessment import FujiAdapter
from fair_offline_assessor.adapters import resolve_adapter
from fair_offline_assessor.models import AssessmentInput, AssessmentResult
from fair_offline_assessor.profiles import ProfileProvider, load_profile


def assess(
    request: AssessmentInput, *, profile: str, provider: ProfileProvider | None = None
) -> AssessmentResult:
    """Assess supplied evidence offline using an exact profile ID@version."""
    loaded = load_profile(profile, provider=provider)
    adapter = resolve_adapter(loaded, adapters=(FujiAdapter(),))
    return adapter.assess(request, loaded)
