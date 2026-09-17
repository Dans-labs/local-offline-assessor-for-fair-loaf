import json
from dataclasses import replace
from hashlib import sha256
from importlib.metadata import version

import pytest

import fair_offline_assessor as library
from fair_offline_assessor import AssessmentInput, InputError, ProfileError, _fuji

PROFILE = "fusji-offline@3.5.1"


@pytest.fixture
def request_data():
    return AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@id": "urn:data",
            "@type": "Dataset",
            "name": "Example",
            "creator": "Alice",
            "publisher": "Archive",
            "datePublished": "2026-01-01",
            "description": "Soil measurements",
            "keywords": ["soil"],
        },
        metadata_url="https://example.org/metadata.jsonld",
    )


@pytest.mark.parametrize("identified", [True, False])
def test_public_assessment_reports_core_results_and_full_coverage(
    request_data, identified
):
    if not identified:
        del request_data.metadata["@id"]
    original = request_data.model_copy(deep=True)
    result = library.assess(request_data, profile=PROFILE)
    core = next(metric for metric in result.metrics if metric.id == "FsF-F2-01M")
    assert core.score.observed_earned == (2 if identified else 0)
    assert core.score.complete
    assert len(result.metrics) == 17
    expected = {
        "FsF-F1-01MD": (1, 2),
        "FsF-F1-02MD": (1, 2, 4, 5),
        "FsF-F2-01M": (2, 3),
        "FsF-F3-01M": (2,),
        "FsF-F4-01M": (1,),
        "FsF-A1-01M": (1,),
        "FsF-A1-02MD": (1, 2),
        "FsF-A1.1-01MD": (1, 2),
        "FsF-A1.2-01MD": (1, 2),
        "FsF-I1-01M": (1, 2),
        "FsF-I2-01M": (2,),
        "FsF-I3-01M": (1, 2),
        "FsF-R1-01M": (1, 2, 3),
        "FsF-R1.1-01M": (1,),
        "FsF-R1.2-01M": (1, 2),
        "FsF-R1.3-01M": (1, 3),
        "FsF-R1.3-02D": (1,),
    }
    assert {metric.id for metric in result.metrics} == expected.keys()
    assert {check.id: check.metric for check in result.tests} == {
        f"{metric}-{suffix}": metric
        for metric, suffixes in expected.items()
        for suffix in suffixes
    }
    assert next(
        metric for metric in result.metrics if metric.id == "FsF-F4-01M"
    ).principles == ("F4",)
    assert result.coverage.model_dump() == {
        "evaluated": 7,
        "indeterminate": 24,
        "errors": 0,
        "not_applicable": 0,
        "total": 31,
    }
    evaluated = {
        "FsF-F2-01M-2",
        "FsF-F2-01M-3",
        "FsF-F3-01M-2",
        "FsF-A1-01M-1",
        "FsF-R1.1-01M-1",
        "FsF-A1.1-01MD-1",
        "FsF-A1.2-01MD-1",
    }
    assert {
        check.id for check in result.tests if check.outcome in {"pass", "fail"}
    } == evaluated
    for check in result.tests:
        if check.outcome == "indeterminate":
            assert check.score is None
            assert check.reason_code == (
                "missing_evidence"
                if check.id in {"FsF-A1.1-01MD-2", "FsF-A1.2-01MD-2"}
                else "not_implemented"
            )
    assert result.overall_score is None
    assert result.principle_scores == {}
    assert result.status == "completed"
    assert result.provenance.engine_version == version("fair-offline-assessor")
    assert result.provenance.processor_version == version("PyLD")
    assert result.profile == library.load_profile(PROFILE).info
    assert {ref.id for ref in result.provenance.resources} == {
        "fuji:metrics",
        "fuji:licenses",
        "fuji:access-rights",
        "fuji:protocols",
        "schemaorg:context",
    }
    assert (
        library.AssessmentResult.model_validate_json(result.model_dump_json()) == result
    )
    assert request_data == original


def test_evidence_and_digests_are_reproducible(request_data):
    first = library.assess(request_data, profile=PROFILE)
    reordered = request_data.model_copy(
        update={"metadata": dict(reversed(request_data.metadata.items()))}
    )
    second = library.assess(reordered, profile=PROFILE)
    assert first == second
    relocated = library.assess(
        request_data.model_copy(update={"metadata_url": "https://example.org/other"}),
        profile=PROFILE,
    )
    assert first.metrics == relocated.metrics
    for before, after in zip(first.tests, relocated.tests, strict=True):
        evidence = tuple(
            ref.model_copy(update={"digest": relocated.provenance.input_digest})
            if ref.resource == "assessment_input"
            else ref
            for ref in before.evidence
        )
        assert before.model_copy(update={"evidence": evidence}) == after
    assert first.provenance.input_digest != relocated.provenance.input_digest
    citation = next(check for check in first.tests if check.id == "FsF-F2-01M-2")
    title = next(
        ref
        for ref in citation.evidence
        if ref.location.endswith("/http:~1~1schema.org~1name/0")
    )
    assert title.resource == "prepared_metadata"
    assert title.subject == "urn:data"
    assert len(title.digest) == 64
    request_data.metadata["name"] = "Changed"
    changed = library.assess(request_data, profile=PROFILE)
    assert first.provenance.input_digest != changed.provenance.input_digest
    changed_citation = next(check for check in changed.tests if check.id == citation.id)
    assert title.digest != changed_citation.evidence[0].digest


@pytest.mark.parametrize(
    "problem", ["adapter", "definitions", "licenses", "access-rights", "protocols"]
)
def test_configuration_is_checked_before_input(problem):
    base = library.BundledProfileProvider()
    bundle = base.load("fusji-offline", "3.5.1")
    info = library.load_profile(PROFILE).info
    if problem == "adapter":
        document = json.loads(bundle.content)
        document["adapter_version"] = "2.0.0"
        content = json.dumps(document).encode()
        bundle = replace(bundle, content=content)
        info = info.model_copy(
            update={"adapter_version": "2.0.0", "digest": sha256(content).hexdigest()}
        )
    else:
        resource = "fuji:metrics" if problem == "definitions" else f"fuji:{problem}"
        content = bundle.resources[resource] + b"\n"
        bundle = replace(
            bundle,
            resources={**bundle.resources, resource: content},
            references=tuple(
                ref.model_copy(update={"digest": sha256(content).hexdigest()})
                if ref.id == resource
                else ref
                for ref in bundle.references
            ),
        )

    class Provider:
        def list_profiles(self):
            return (info,)

        def load(self, _profile_id, _version):
            return bundle

    with pytest.raises(ProfileError) as error:
        library.assess(
            AssessmentInput(metadata={"@context": "https://missing.invalid/context"}),
            profile=PROFILE,
            provider=Provider(),
        )
    assert error.value.code == (
        "adapter_unavailable" if problem == "adapter" else "unsupported_definitions"
    )


@pytest.mark.parametrize(
    ("metadata", "code"),
    [
        ({"@context": "https://missing.invalid/context"}, "unknown_context"),
        ({"@context": "https://schema.org", "@type": "Person"}, "dataset_not_found"),
        (
            {
                "@context": "https://schema.org",
                "@type": "Dataset",
                "name": float("nan"),
            },
            "invalid_json",
        ),
    ],
)
def test_input_errors_do_not_become_failed_checks(metadata, code):
    with pytest.raises(InputError) as error:
        library.assess(AssessmentInput(metadata=metadata), profile=PROFILE)
    assert error.value.code == code


def test_evaluator_errors_are_findings_without_internal_details(
    request_data, monkeypatch
):
    def fail(*_args, **_kwargs):
        raise RuntimeError("private implementation details")

    original = library.assess(request_data, profile=PROFILE)
    monkeypatch.setattr(_fuji.EVALUATORS["FsF-F2-01M"].implementation, "evaluate", fail)
    result = library.assess(request_data, profile=PROFILE)
    assert result.status == "completed_with_errors"
    assert result.coverage.errors == 2
    for before, after in zip(original.tests, result.tests, strict=True):
        if before.metric == "FsF-F2-01M":
            assert after.outcome == "error"
            assert after.score is None
        else:
            assert after == before
    assert (
        next(metric for metric in result.metrics if metric.id == "FsF-F2-01M").outcome
        == "error"
    )
    assert "private implementation details" not in result.model_dump_json()


def test_unused_metadata_and_captures_are_reported(request_data):
    request_data.metadata["urn:custom"] = "Extra"
    request = AssessmentInput(
        **{
            **request_data.model_dump(),
            "captures": [
                {
                    "id": "capture",
                    "resource_url": "https://example.org/data",
                    "captured_at": "2026-01-01T00:00:00Z",
                    "exchanges": [
                        {
                            "method": "GET",
                            "url": "https://example.org/data",
                            "status": 200,
                        }
                    ],
                }
            ],
        }
    )
    result = library.assess(
        request, profile=PROFILE, provider=library.BundledProfileProvider()
    )
    assert {note.code for note in result.diagnostics} == {
        "unmapped_term",
        "captures_not_supported",
    }
    assert result.status == "completed"


@pytest.mark.parametrize(
    ("term", "value", "outcome"),
    [
        ("license", "https://creativecommons.org/licenses/by/4.0/", "pass"),
        ("license", {"@value": "Use with written permission from the author."}, "pass"),
        ("license", {"@id": "https://example.org/licence"}, "pass"),
        ("license", {"url": "https://example.org/licence"}, "pass"),
        ("http://purl.org/dc/terms/license", "MIT License", "pass"),
        ("license", None, "fail"),
        ("license", [{"@value": ""}, {"@value": "  "}, 0, False], "fail"),
        ("license", {"@id": "_:unknown"}, "fail"),
    ],
)
def test_licence_presence_uses_supplied_values_without_requiring_spdx(
    request_data, term, value, outcome
):
    request_data.metadata[term] = value
    original = request_data.model_copy(deep=True)
    result = library.assess(request_data, profile=PROFILE)
    metric = next(item for item in result.metrics if item.id == "FsF-R1.1-01M")
    check = next(item for item in result.tests if item.metric == metric.id)
    assert metric.outcome == check.outcome == outcome
    assert metric.score == check.score
    assert metric.score.observed_earned == (1 if outcome == "pass" else 0)
    assert metric.score.maximum == 1
    assert metric.score.complete
    assert metric.level.value == (3 if outcome == "pass" else 0)
    assert check.evidence or outcome == "fail"
    assert all(
        "license" in ref.location or "url" in ref.location for ref in check.evidence
    )
    core = next(item for item in result.tests if item.metric == "FsF-F2-01M")
    assert all("license" not in ref.location for ref in core.evidence)
    assert not result.diagnostics
    assert request_data == original
    empty = library.assess(
        AssessmentInput(
            metadata={"@context": "https://schema.org", "@type": "Dataset"}
        ),
        profile=PROFILE,
    )
    assert (
        next(item for item in empty.metrics if item.id == metric.id).outcome == "fail"
    )


@pytest.mark.parametrize(
    ("metadata", "outcome", "earned"),
    [
        ({"conditionsOfAccess": "Available on request."}, "pass", 1),
        (
            {
                "http://purl.org/dc/terms/accessRights": {
                    "@id": "http://purl.org/coar/access_right/c_16ec"
                }
            },
            "pass",
            1,
        ),
        ({"conditionsOfAccess": "MIT License"}, "fail", 0),
        ({"license": "https://creativecommons.org/licenses/by/4.0/"}, "fail", 0),
        ({"conditionsOfAccess": [None, "  "]}, "fail", 0),
        ({"isAccessibleForFree": True}, "pass", 0),
        ({"isAccessibleForFree": False}, "pass", 0),
    ],
)
def test_access_information_preserves_fuji_scoring(
    request_data, metadata, outcome, earned
):
    request_data.metadata.update(metadata)
    original = request_data.model_copy(deep=True)
    result = library.assess(request_data, profile=PROFILE)
    metric = next(item for item in result.metrics if item.id == "FsF-A1-01M")
    check = next(item for item in result.tests if item.metric == metric.id)
    assert metric.outcome == outcome
    assert metric.score.observed_earned == earned
    assert metric.score.maximum == 1
    assert metric.score.complete
    assert check.outcome == ("pass" if earned else "fail")
    assert check.score == metric.score
    assert metric.level.value == (3 if earned else 0)
    assert check.evidence or not earned
    assert all("license" not in ref.location for ref in check.evidence)
    assert not result.diagnostics
    assert request_data == original


@pytest.mark.parametrize("value", ["false", [True, False]])
def test_access_free_rejects_invalid_or_conflicting_booleans(request_data, value):
    request_data.metadata["isAccessibleForFree"] = value
    with pytest.raises(InputError) as error:
        library.assess(request_data, profile=PROFILE)
    assert error.value.code == "invalid_access_free"


def test_reference_files_are_parsed_once_per_assessment(request_data, monkeypatch):
    original = _fuji.yaml.safe_load
    parsed = []

    def read(content):
        parsed.append(content)
        return original(content)

    monkeypatch.setattr(_fuji.yaml, "safe_load", read)
    first = library.assess(request_data, profile=PROFILE)
    second = library.assess(request_data, profile=PROFILE)
    assert first == second
    resources = library.load_profile(PROFILE).resources
    assert all(
        parsed.count(resources[reference.id]) == 2 for reference in _fuji.REFERENCES
    )


@pytest.mark.parametrize(
    ("distribution", "outcome"),
    [
        ({"contentUrl": "https://example.org/data.csv"}, "pass"),
        ({"url": "https://example.org/data.csv"}, "pass"),
        ({"@id": "https://example.org/data.csv"}, "pass"),
        (None, "fail"),
        ({"name": "Data file"}, "fail"),
        ({"@id": "_:missing"}, "fail"),
        ({"contentUrl": [{"@value": "  "}, False, 0]}, "fail"),
    ],
)
def test_data_links_use_distributions_without_counting_the_dataset_url(
    request_data, distribution, outcome
):
    request_data.metadata.update(
        url="https://example.org/dataset", distribution=distribution
    )
    original = request_data.model_copy(deep=True)
    result = library.assess(request_data, profile=PROFILE)
    metric = next(item for item in result.metrics if item.id == "FsF-F3-01M")
    check = next(item for item in result.tests if item.id == "FsF-F3-01M-2")
    assert metric.outcome == check.outcome == outcome
    assert metric.score == check.score
    assert metric.score.observed_earned == (1 if outcome == "pass" else 0)
    assert metric.score.maximum == 1
    assert metric.score.complete
    assert metric.level.value == (3 if outcome == "pass" else 0)
    assert check.evidence or outcome == "fail"
    assert all(
        ref.subject != "urn:data" or "distribution" in ref.location
        for ref in check.evidence
    )
    assert not result.diagnostics
    assert request_data == original


@pytest.mark.parametrize(
    ("metadata_url", "data_urls", "standard", "authentication"),
    [
        (
            "https://example.org/meta",
            ["https://example.org/data"],
            ("pass", "pass"),
            ("pass", "pass"),
        ),
        (
            "ws://example.org/meta",
            ["ws://example.org/data"],
            ("pass", "pass"),
            ("fail", "fail"),
        ),
        (
            "unknown://example.org/meta",
            ["unknown://example.org/data"],
            ("fail", "fail"),
            ("fail", "fail"),
        ),
        (
            "https://example.org/meta",
            ["unknown://example.org/data"],
            ("pass", "fail"),
            ("pass", "fail"),
        ),
        (
            None,
            ["unknown://example.org/data", "https://example.org/data"],
            ("indeterminate", "pass"),
            ("indeterminate", "pass"),
        ),
        (
            "https://example.org/meta",
            [],
            ("pass", "indeterminate"),
            ("pass", "indeterminate"),
        ),
        (
            None,
            [],
            ("indeterminate", "indeterminate"),
            ("indeterminate", "indeterminate"),
        ),
    ],
)
def test_protocols_use_supplied_urls_and_catalogue_capabilities(
    metadata_url, data_urls, standard, authentication
):
    request = AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@type": "Dataset",
            "@id": "https://example.org/dataset",
            "distribution": [{"contentUrl": url} for url in data_urls],
        },
        metadata_url=metadata_url,
    )
    original = request.model_copy(deep=True)
    result = library.assess(request, profile=PROFILE)
    for identifier, outcomes in (
        ("FsF-A1.1-01MD", standard),
        ("FsF-A1.2-01MD", authentication),
    ):
        checks = [check for check in result.tests if check.metric == identifier]
        metric = next(item for item in result.metrics if item.id == identifier)
        assert tuple(check.outcome for check in checks) == outcomes
        earned = outcomes.count("pass")
        complete = "indeterminate" not in outcomes
        assert metric.score.observed_earned == earned
        assert metric.score.maximum == 2
        assert metric.score.complete == complete
        assert metric.score.percent == (earned * 50 if complete else None)
        assert metric.outcome == (
            "pass" if earned else "fail" if complete else "indeterminate"
        )
        for check in checks:
            if check.outcome == "indeterminate":
                assert check.reason_code == "missing_evidence"
                assert check.score is None
                assert not check.evidence
            else:
                assert check.score.observed_earned == (check.outcome == "pass")
                assert check.level.value == (3 if check.outcome == "pass" else 0)
                assert check.evidence
        if metadata_url:
            assert len(checks[0].evidence) == 1
            ref = checks[0].evidence[0]
            assert (ref.resource, ref.location) == ("assessment_input", "/metadata_url")
            assert ref.digest == result.provenance.input_digest
        assert all(ref.resource == "prepared_metadata" for ref in checks[1].evidence)
        assert all("@id" not in ref.location for ref in checks[1].evidence)
    assert result.coverage.errors == 0
    assert request == original
