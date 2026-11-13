"""Single-engine offline F-UJI assessment.

Lazy public exports keep resource build tools independent from heavy evaluator imports.
"""
import logging

__all__ = ["Assessor", "FairAssessor", "assess", "AssessmentInput", "AssessmentResult", "InputError", "ProfileError", "load_profile", "list_profiles", "BundledProfileProvider"]


def __getattr__(name):
    if name in {"Assessor", "FairAssessor", "assess"}:
        from fair_offline_assessor import assessment
        return getattr(assessment, name)
    if name in {"AssessmentInput", "AssessmentResult", "InputError", "ProfileError"}:
        from fair_offline_assessor import models
        return getattr(models, name)
    if name in {"load_profile", "list_profiles", "BundledProfileProvider"}:
        from fair_offline_assessor import profiles
        return getattr(profiles, name)
    raise AttributeError(name)

logging.getLogger(__name__).addHandler(logging.NullHandler())
