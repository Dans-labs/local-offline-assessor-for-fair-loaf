import pytest

from fair_offline_assessor import AssessmentInput, assess, load_profile
from fair_offline_assessor.assessors.fuji.checks import Runner


@pytest.mark.parametrize(
    ("metadata_id", "data_ids", "outcomes", "earned"),
    [
        (
            "https://doi.org/10.5072/example",
            ["https://example.org/data", "taxonomy:9606"],
            ("pass", "pass"),
            0.5,
        ),
        (
            "https://example.org/metadata",
            ["https://example.org/data"],
            ("fail", "fail"),
            0,
        ),
        (None, ["hdl:12345/example"], ("indeterminate", "pass"), 0),
        ("https://doi.org/10.5072/example", [], ("pass", "indeterminate"), 0.5),
    ],
)
def test_pid_syntax_keeps_registration_unassessed(
    metadata_id, data_ids, outcomes, earned
):
    request = AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@id": "https://doi.org/10.5072/dataset",
            "@type": "Dataset",
            "distribution": [{"contentUrl": {"@value": value}} for value in data_ids],
        },
        metadata_url=metadata_id,
    )
    original = request.model_copy(deep=True)
    result = assess(request, profile="fusji-offline@3.5.1")
    metric = next(item for item in result.metrics if item.id == "FsF-F1-02MD")
    checks = {
        check.id.rsplit("-", 1)[1]: check
        for check in result.tests
        if check.metric == metric.id
    }
    assert (checks["1"].outcome, checks["4"].outcome) == outcomes
    for suffix, present, maximum in (("1", metadata_id, 0.5), ("4", data_ids, 0)):
        check = checks[suffix]
        if present:
            assert check.score.maximum == maximum
            assert check.score.observed_earned == (
                maximum if check.outcome == "pass" else 0
            )
            assert check.evidence
        else:
            assert check.score is None
            assert check.reason_code == "missing_evidence"
            assert not check.evidence
    assert all(ref.location == "/metadata_url" for ref in checks["1"].evidence)
    assert all(ref.location == "/metadata" for ref in checks["4"].evidence)
    for suffix in ("2", "5"):
        assert checks[suffix].outcome == "indeterminate"
        assert checks[suffix].reason_code == "unsupported_check"
        assert checks[suffix].score is None
        assert not checks[suffix].evidence
    assert metric.score.observed_earned == earned
    assert metric.score.maximum == 1
    assert not metric.score.complete
    assert metric.score.percent is metric.level is None
    assert result.coverage.errors == 0
    assert request == original


def test_pid_syntax_does_not_claim_resolution_or_reuse_previous_identifiers():
    runner = Runner(load_profile("fusji-offline@3.5.1").resources)
    identifier = "https://doi.org/10.5072/example"
    result = runner.evaluate("FsF-F1-02MD", {}, metadata_url=identifier)
    assert result.native["output"]["persistent_identifiers"] == [
        {
            "pid": identifier,
            "pid_scheme": "doi",
            "resolvable_status": False,
            "resolved_url": None,
            "target": "metadata",
        }
    ]
    assert result.native["score"] == {"earned": 0.5, "total": 1}
    assert (
        runner.evaluate("FsF-F1-02MD", {}).native["output"]["persistent_identifiers"]
        == []
    )
    assert runner.evaluate("FsF-F1-02MD", {}, metadata_url=identifier) == result
