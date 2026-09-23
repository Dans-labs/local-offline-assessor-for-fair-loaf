import pytest

from fair_offline_assessor import AssessmentInput, assess


@pytest.mark.parametrize(
    ("properties", "outcomes", "earned", "maturity"),
    [
        ({}, ("fail", "fail", "fail"), 0, 0),
        ({"@type": "Dataset"}, ("pass", "fail", "fail"), 1, 1),
        ({"@type": "urn:custom:type"}, ("pass", "fail", "fail"), 1, 1),
        ({"variableMeasured": "temperature"}, ("fail", "fail", "fail"), 0, 0),
        (
            {"size": {"value": 123}, "encodingFormat": "text/csv"},
            ("fail", "fail", "fail"),
            0,
            0,
        ),
        (
            {
                "http://purl.org/dc/terms/extent": "123",
                "http://purl.org/dc/terms/format": "text/csv",
            },
            ("fail", "fail", "fail"),
            0,
            0,
        ),
        (
            {
                "@type": "Dataset",
                "distribution": {
                    "contentUrl": "https://example.org/data",
                    "encodingFormat": "text/csv",
                    "contentSize": "123",
                },
                "variableMeasured": {"name": "temperature"},
            },
            ("pass", "pass", "pass"),
            2,
            3,
        ),
        (
            {
                "distribution": [
                    {
                        "contentUrl": "https://example.org/a",
                        "encodingFormat": "text/csv",
                    },
                    {"contentUrl": "https://example.org/b", "contentSize": "123"},
                ],
            },
            ("fail", "fail", "fail"),
            0,
            0,
        ),
        (
            {
                "distribution": {
                    "contentUrl": "https://example.org/data",
                    "encodingFormat": "text/csv",
                    "contentSize": 0,
                },
            },
            ("fail", "fail", "fail"),
            0,
            0,
        ),
        (
            {
                "distribution": "https://example.org/data",
                "variableMeasured": "temperature",
            },
            ("fail", "fail", "fail"),
            0,
            0,
        ),
        (
            {"size": " ", "encodingFormat": [], "variableMeasured": {"name": ""}},
            ("fail", "fail", "fail"),
            0,
            0,
        ),
    ],
)
def test_data_content_preserves_native_presence_checks(
    properties, outcomes, earned, maturity
):
    request = AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@id": "urn:data",
            "name": "Example",
            **properties,
        },
    )
    original = request.model_copy(deep=True)
    result = assess(request, profile="fusji-offline@3.5.1")
    metric = next(item for item in result.metrics if item.id == "FsF-R1-01M")
    checks = [check for check in result.tests if check.metric == metric.id]
    assert tuple(check.outcome for check in checks) == outcomes
    assert metric.outcome == ("pass" if "pass" in outcomes else "fail")
    assert metric.score.observed_earned == earned
    assert metric.score.maximum == 2
    assert metric.score.complete
    assert metric.level.value == maturity
    assert [check.score.maximum for check in checks] == [1, 1, 0]
    assert checks[2].score.observed_earned == 0
    assert all(ref.location == "/metadata" for c in checks for ref in c.evidence)
    assert result.coverage.errors == 0
    assert request == original
