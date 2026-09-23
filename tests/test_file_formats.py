import pytest

from fair_offline_assessor import AssessmentInput, assess, load_profile
from fair_offline_assessor.assessors.fuji.checks import Runner


@pytest.mark.parametrize(
    ("formats", "outcome"),
    [
        ("text/csv", "pass"),
        (["application/x-custom", "application/x-netcdf"], "pass"),
        ("application/x-custom", "fail"),
        (None, "indeterminate"),
    ],
)
def test_file_formats_use_declarations_without_guessing(formats, outcome):
    request = AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@type": "Dataset",
            "distribution": {
                "contentUrl": "https://example.org/data.csv",
                "encodingFormat": formats,
                "contentSize": "123",
            },
        }
    )
    if isinstance(formats, list):
        request.metadata["distribution"] = [
            {"contentUrl": f"https://example.org/data/{i}", "encodingFormat": fmt}
            for i, fmt in enumerate(formats)
        ]
    original = request.model_copy(deep=True)
    result = assess(request, profile="fusji-offline@3.5.1")
    metric = next(item for item in result.metrics if item.id == "FsF-R1.3-02D")
    check = next(item for item in result.tests if item.metric == metric.id)
    assert metric.outcome == check.outcome == outcome
    assert metric.score.observed_earned == (outcome == "pass")
    assert metric.score.maximum == 1
    assert metric.score.complete == (outcome != "indeterminate")
    if outcome == "indeterminate":
        assert check.reason_code == "missing_evidence"
        assert check.score is None
        assert not check.evidence
    else:
        assert check.score == metric.score
        assert metric.level.value == (3 if outcome == "pass" else 0)
        assert all(ref.location == "/metadata" for ref in check.evidence)
        assert all("contentSize" not in ref.location for ref in check.evidence)
    assert result.coverage.errors == 0
    assert request == original


def test_file_format_catalogue_preserves_native_reasons_and_score():
    runner = Runner(load_profile("fusji-offline@3.5.1").resources)
    result = runner.evaluate(
        "FsF-R1.3-02D",
        {
            "file_formats": [
                {"url": "urn:science", "type": "image/x-3ds"},
                {"url": "urn:preservation", "type": "audio/aac"},
                {"url": "urn:open", "type": "image/avif"},
            ]
        },
    )
    assert result.native["score"] == {"earned": 1, "total": 1}
    assert {
        item["file_uri"]: item["preference_reason"] for item in result.native["output"]
    } == {
        "urn:science": ["science format"],
        "urn:preservation": ["long term format"],
        "urn:open": ["open format"],
    }
