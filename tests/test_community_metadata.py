import pytest

from fair_offline_assessor import AssessmentInput, assess, load_profile
from fair_offline_assessor._fuji import Runner


@pytest.mark.parametrize(
    ("term", "outcomes", "maturity"),
    [
        ("https://schema.org/name", ["fail", "pass"], 1),
        ("https://rs.tdwg.org/dwc/terms/scientificName", ["pass", "fail"], 3),
        ("https://example.org/custom/title", ["fail", "fail"], 0),
    ],
)
def test_community_standards_use_declared_namespaces(term, outcomes, maturity):
    request = AssessmentInput(metadata={"@id": "urn:data", term: "Sample"})
    original = request.model_copy(deep=True)
    result = assess(request, profile="fusji-offline@3.5.1")
    metric = next(item for item in result.metrics if item.id == "FsF-R1.3-01M")
    checks = [item for item in result.tests if item.metric == metric.id]
    assert [check.outcome for check in checks] == outcomes
    assert metric.outcome == ("pass" if maturity else "fail")
    assert metric.score.observed_earned == bool(maturity)
    assert metric.score.maximum == 1
    assert metric.score.complete
    assert metric.level.value == maturity
    assert all(check.evidence for check in checks)
    assert result.coverage.errors == 0
    assert request == original


def test_community_namespaces_follow_native_union_of_supplied_graphs():
    metadata = {
        "@context": {"dwc": "http://rs.tdwg.org/dwc/terms/"},
        "@graph": [
            {
                "@id": "urn:data",
                "urn:title": "http://rs.tdwg.org/dwc/terms/",
                "urn:external": {"@id": "urn:hidden"},
            },
            {"@id": "urn:other", "@type": "dwc:Taxon"},
            {
                "@id": "urn:named",
                "@graph": [{"@id": "urn:hidden", "@type": "dwc:Taxon"}],
            },
        ],
    }
    first = assess(
        AssessmentInput(metadata=metadata),
        profile="fusji-offline@3.5.1",
    )
    assert next(c for c in first.tests if c.id == "FsF-R1.3-01M-1").outcome == "pass"
    metadata["@graph"][0]["urn:related"] = {"@list": [{"@id": "urn:other"}]}
    second = assess(
        AssessmentInput(metadata=metadata),
        profile="fusji-offline@3.5.1",
    )
    check = next(item for item in second.tests if item.id == "FsF-R1.3-01M-1")
    assert check.outcome == "pass"
    assert all(ref.location == "/metadata" for ref in check.evidence)
    assert second.coverage.errors == 0


def test_community_matching_preserves_native_fuzzy_lookup_and_alternative_score():
    runner = Runner(load_profile("fusji-offline@3.5.1").resources)
    result = runner.evaluate(
        "FsF-R1.3-01M",
        {"namespaces": ["http://rs.tdwg.org/dwc/term/", "http://purl.org/dc/terms/"]},
    )
    assert [check.outcome for check in result.tests] == ["pass", "pass"]
    assert result.native["score"] == {"earned": 1, "total": 1}
    assert result.native["maturity"] == 3
    assert {item["metadata_standard"] for item in result.native["output"]} == {
        "Darwin Core",
        "Dublin Core",
    }
    rejected = runner.evaluate(
        "FsF-R1.3-01M", {"namespaces": ["http://rs.tdwg.invalid/dwc/terms/"]}
    )
    assert rejected.native["output"] == []
    assert rejected.metric.outcome == "fail"
