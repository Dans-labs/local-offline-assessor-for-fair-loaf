import pytest

from fair_offline_assessor import AssessmentInput, assess


@pytest.mark.parametrize(
    ("properties", "outcomes", "maturity"),
    [
        ({}, ("fail", "fail"), 0),
        ({"creator": "Alice"}, ("pass", "fail"), 2),
        ({"contributor": {"name": "Alice"}}, ("pass", "fail"), 2),
        ({"dc:modified": "2026-01-01"}, ("pass", "fail"), 2),
        ({"prov:wasGeneratedBy": {"@id": "urn:run"}}, ("fail", "pass"), 3),
        ({"pav:createdBy": {"@id": "urn:person"}}, ("fail", "pass"), 3),
        (
            {"creator": "Alice", "prov:wasAttributedTo": {"@id": "urn:person"}},
            ("pass", "pass"),
            3,
        ),
        ({"creator": " ", "prov:wasGeneratedBy": None}, ("fail", "fail"), 0),
        ({"dc:source": {"@id": "urn:source"}}, ("fail", "fail"), 0),
        (
            {
                "description": "http://purl.org/pav/createdBy",
                "http://www.w3.org/ns/provenance#activity": "unrecognised",
            },
            ("fail", "fail"),
            0,
        ),
    ],
)
def test_provenance_keeps_native_scoring_and_scopes_evidence(
    properties, outcomes, maturity
):
    request = AssessmentInput(
        metadata={
            "@context": [
                "https://schema.org",
                {
                    "prov": "http://www.w3.org/ns/prov#",
                    "pav": "http://purl.org/pav/",
                    "dc": "http://purl.org/dc/terms/",
                },
            ],
            "@type": "Dataset",
            **properties,
        }
    )
    original = request.model_copy(deep=True)
    result = assess(request, profile="fusji-offline@3.5.1")
    metric = next(item for item in result.metrics if item.id == "FsF-R1.2-01M")
    checks = [check for check in result.tests if check.metric == metric.id]
    assert tuple(check.outcome for check in checks) == outcomes
    assert metric.outcome == ("pass" if maturity else "fail")
    assert metric.score.observed_earned == bool(maturity)
    assert metric.score.maximum == 1
    assert metric.score.complete
    assert metric.level.value == maturity
    for check in checks:
        assert check.score.observed_earned == (check.outcome == "pass")
        assert check.score.maximum == 1
    assert bool(checks[1].evidence) == (outcomes[1] == "pass")
    assert all(
        "prov#" in ref.location or "pav~1" in ref.location for ref in checks[1].evidence
    )
    assert all("prov#" not in ref.location for ref in checks[0].evidence)
    assert result.coverage.errors == 0
    assert request == original
