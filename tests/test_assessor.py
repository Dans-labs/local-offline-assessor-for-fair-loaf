import pytest

import fair_offline_assessor as library


@pytest.mark.parametrize(("name", "version"), [("FUJI", None), ("fuji", "3.5.1")])
def test_assessor_matches_profile_entry_point_with_all_evidence(name, version):
    request = library.AssessmentInput(
        metadata=[
            {
                "@context": "urn:context",
                "@id": identifier,
                "@type": "Dataset",
                "name": identifier,
            }
            for identifier in ("first", "second")
        ],
        subject="https://example.org/second",
        metadata_url="https://example.org/metadata",
        local_contexts={"urn:context": {"@context": {"@vocab": "https://schema.org/"}}},
    )
    evidence = request.model_dump()
    assessor = library.Assessor(name, version=version)
    result = assessor.assess(**evidence)
    assert result == library.assess(request, profile="fusji-offline@3.5.1")
    assert (result.profile.id, result.profile.version) == ("fusji-offline", "3.5.1")
    assert evidence == request.model_dump()


@pytest.mark.parametrize(
    ("name", "version", "code"),
    [
        ("unknown", None, "assessor_not_found"),
        ("FUJI", "2.0.0", "assessor_version_not_found"),
        ("FUJI", "", "assessor_version_not_found"),
    ],
)
def test_assessor_rejects_unknown_selection_without_falling_back(name, version, code):
    with pytest.raises(library.ProfileError) as error:
        library.Assessor(name, version=version)
    assert error.value.code == code


def test_assessor_keeps_assessments_and_instances_independent():
    assessor = library.Assessor("FUJI")
    metadata = {"@context": "https://schema.org", "@type": "Dataset", "name": "Example"}
    licensed = {**metadata, "license": "MIT"}
    first = assessor.assess(metadata=licensed)
    second = assessor.assess(metadata=metadata)
    assert next(c for c in first.tests if c.id == "FsF-R1.1-01M-1").outcome == "pass"
    assert next(c for c in second.tests if c.id == "FsF-R1.1-01M-1").outcome == "fail"
    assert assessor.assess(metadata=licensed) == first
    assert library.Assessor("FUJI").assess(metadata=metadata) == second
