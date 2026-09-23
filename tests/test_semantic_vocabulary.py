import pytest

from fair_offline_assessor import AssessmentInput, assess, load_profile
from fair_offline_assessor.assessors.fuji.checks import Runner


@pytest.mark.parametrize(
    ("term", "value", "outcome"),
    [
        ("http://www.w3.org/ns/prov#wasDerivedFrom", "Sample", "pass"),
        ("https://schema.org/name", "Sample", "fail"),
        ("urn:subject", "http://purl.obolibrary.org/obo/ENVO_00000446", "pass"),
        (
            "urn:subject",
            {"@list": [{"@id": "http://purl.obolibrary.org/obo/ENVO_00000446"}]},
            "pass",
        ),
    ],
)
def test_semantic_vocabularies_use_registered_nondefault_namespaces(
    term, value, outcome
):
    request = AssessmentInput(metadata={"@id": "urn:data", term: value})
    original = request.model_copy(deep=True)
    result = assess(request, profile="fusji-offline@3.5.1")
    metric = next(item for item in result.metrics if item.id == "FsF-I2-01M")
    check = next(item for item in result.tests if item.metric == metric.id)
    assert check.outcome == outcome
    assert check.score.observed_earned == (2 if outcome == "pass" else 0)
    assert check.score.maximum == 2
    assert metric.score == check.score
    assert metric.score.complete
    assert metric.level.value == (3 if outcome == "pass" else 0)
    assert check.evidence
    assert all(ref.location == "/metadata" for ref in check.evidence)
    assert result.coverage.errors == 0
    assert request == original


def test_semantic_vocabulary_keeps_native_status_and_exclusions():
    runner = Runner(load_profile("fusji-offline@3.5.1").resources)
    fields = {
        "namespaces": [
            "http://www.w3.org/ns/prov#",
            "http://www.w3.org/2004/02/skos/core#",
            "https://doi.org/",
            "https://orcid.org/",
        ]
    }
    result = runner.evaluate("FsF-I2-01M", fields)
    assert result.tests[0].outcome == "pass"
    assert result.native["score"] == {"earned": 2, "total": 2}
    assert result.native["test_status"] == result.metric.outcome == "fail"
    assert result.native["output"] == [
        {"namespace": "http://www.w3.org/ns/prov", "is_namespace_active": True}
    ]
    assert runner.evaluate("FsF-I2-01M", fields) == result
    empty = runner.evaluate("FsF-I2-01M", {})
    assert empty.tests[0].outcome == "fail"
    assert empty.metric.score.observed_earned == 0
