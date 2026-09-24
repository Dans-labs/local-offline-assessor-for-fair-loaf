import logging

from fair_offline_assessor.assessment import Assessor, assess
from fair_offline_assessor.models import (
    AssessmentInput,
    AssessmentResult,
    ChampionInput,
    InputError,
    ProfileError,
)
from fair_offline_assessor.profiles import (
    BundledProfileProvider,
    ProfileBundle,
    ProfileProvider,
    list_profiles,
    load_profile,
)

__all__ = [
    "AssessmentInput",
    "AssessmentResult",
    "Assessor",
    "BundledProfileProvider",
    "ChampionInput",
    "InputError",
    "ProfileBundle",
    "ProfileError",
    "ProfileProvider",
    "assess",
    "list_profiles",
    "load_profile",
]

logging.getLogger(__name__).addHandler(logging.NullHandler())
