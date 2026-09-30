import pytest
from pydantic import ValidationError

from fair_offline_assessor import load_profile
from fair_offline_assessor.models import AssessmentResult, Score


def result_data():
    return {
        "profile": load_profile("fusji-offline@3.5.1").info.model_dump(),
        "provenance": {
            "engine_version": "0.1.0",
            "processor_version": "3.3",
            "input_digest": "0" * 64,
            "resources": [],
        },
        "metrics": [
            {
                "id": "I1",
                "principles": ["I1"],
                "outcome": "pass",
                "score": {"observed_earned": 2, "maximum": 2, "complete": True},
            }
        ],
        "tests": [
            {
                "id": "embedded",
                "metric": "I1",
                "outcome": "pass",
                "reason_code": "found",
                "message": "Embedded metadata found.",
            },
            {
                "id": "negotiated",
                "metric": "I1",
                "outcome": "indeterminate",
                "reason_code": "missing_evidence",
                "message": "No evidence supplied.",
            },
        ],
    }


def test_score_round_trip_rejects_incorrect_derived_percentage():
    score = Score(observed_earned=1, maximum=2, complete=True)
    assert Score.model_validate_json(score.model_dump_json()) == score
    with pytest.raises(ValidationError):
        Score.model_validate({**score.model_dump(), "percent": 100})


def test_alternative_checks_keep_adapter_score_and_separate_coverage():
    result = AssessmentResult.model_validate(result_data())
    assert result.metrics[0].score.percent == 100
    assert result.coverage.model_dump() == {
        "evaluated": 1,
        "indeterminate": 1,
        "errors": 0,
        "not_applicable": 0,
        "total": 2,
    }
    assert AssessmentResult.model_validate_json(result.model_dump_json()) == result


def test_unscored_maturity_and_not_applicable_are_preserved():
    data = result_data()
    data["metrics"] = [
        {
            "id": "I1",
            "principles": ["I1"],
            "outcome": "not_applicable",
            "level": {"scheme": "rda-progress", "value": 0},
        }
    ]
    data["tests"] = [{**data["tests"][0], "outcome": "not_applicable"}]
    result = AssessmentResult.model_validate(data)
    assert result.metrics[0].level.value == 0
    assert result.metrics[0].score is None
    assert result.coverage.not_applicable == 1
    assert result.coverage.evaluated == 0


@pytest.mark.parametrize(
    "problem",
    ["coverage", "orphan", "duplicate", "status", "unmeasured_score"],
)
def test_inconsistent_results_are_rejected(problem):
    data = result_data()
    match problem:
        case "coverage":
            data["coverage"] = {
                "evaluated": 99,
                "indeterminate": 0,
                "errors": 0,
                "not_applicable": 0,
                "total": 99,
            }
        case "orphan":
            data["tests"][0]["metric"] = "missing"
        case "duplicate":
            data["tests"].append(data["tests"][0])
        case "status":
            data["tests"][0]["outcome"] = "error"
            data["status"] = "completed"
        case "unmeasured_score":
            data["tests"][1]["score"] = data["metrics"][0]["score"]
    with pytest.raises(ValidationError):
        AssessmentResult.model_validate(data)
