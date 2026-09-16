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
        "evaluated": 2,
        "indeterminate": 29,
        "errors": 0,
        "not_applicable": 0,
        "total": 31,
    }
    evaluated = {
        "FsF-F2-01M-2",
        "FsF-F2-01M-3",
    }
    assert {
        check.id for check in result.tests if check.outcome in {"pass", "fail"}
    } == evaluated
    assert all(
        check.score is None and check.reason_code == "not_implemented"
        for check in result.tests
        if check.outcome == "indeterminate"
    )
    assert result.overall_score is None
    assert result.principle_scores == {}
    assert result.status == "completed"
    assert result.provenance.engine_version == version("fair-offline-assessor")
    assert result.provenance.processor_version == version("PyLD")
    assert result.profile == library.load_profile(PROFILE).info
    assert {ref.id for ref in result.provenance.resources} == {
        "fuji:metrics",
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
    assert first.tests == relocated.tests
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


@pytest.mark.parametrize("problem", ["adapter", "definitions"])
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
        content = bundle.resources["fuji:metrics"] + b"\n"
        bundle = replace(
            bundle,
            resources={**bundle.resources, "fuji:metrics": content},
            references=tuple(
                ref.model_copy(update={"digest": sha256(content).hexdigest()})
                if ref.id == "fuji:metrics"
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
    monkeypatch.setattr(_fuji, "evaluate_core_metadata", fail)
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
