import json
from copy import deepcopy

import pytest

from fair_offline_assessor import Assessor, load_profile
from fair_offline_assessor.assessors.fuji import checks as fuji_checks
from fair_offline_assessor.models import AssessmentResult, Provenance

METADATA = {
    "@context": "https://schema.org",
    "@id": "urn:data",
    "@type": "Dataset",
    "name": "Example",
    "creator": "Alice",
    "publisher": "Archive",
    "datePublished": "2026-01-01",
    "description": "Soil measurements",
    "keywords": ["soil"],
    "license": "MIT",
}
IDENTIFIER = "https://doi.org/10.5072/example"


@pytest.fixture
def native_outputs(monkeypatch):
    produced = []
    get_result = fuji_checks.FAIREvaluator.getResult

    def record_result(evaluator):
        native = get_result(evaluator)
        produced.append(deepcopy(native))
        return native

    monkeypatch.setattr(fuji_checks.FAIREvaluator, "getResult", record_result)
    return produced


def test_raw_contains_exact_native_outputs_without_synthetic_checks(native_outputs):
    result = Assessor("FUJI").assess(metadata=METADATA, metadata_url=IDENTIFIER)

    assert result.raw == native_outputs
    assert json.loads(result.model_dump_json())["raw"] == native_outputs
    native = {item["metric_identifier"]: item for item in result.raw}
    assert "FsF-F4-01M" not in native
    persistence = native["FsF-F1-02MD"]["metric_tests"]
    assert "FsF-F1-02MD-1" in persistence
    assert "FsF-F1-02MD-2" not in persistence
    assert "FsF-F1-02MD-5" not in persistence
    check = next(item for item in result.tests if item.id == "FsF-F1-02MD-2")
    assert check.outcome == "indeterminate"


def test_blocked_metrics_do_not_receive_invented_native_results(native_outputs):
    result = Assessor("FUJI").assess(metadata=None, metadata_url=IDENTIFIER)

    assert result.raw == native_outputs
    native_ids = {item["metric_identifier"] for item in result.raw}
    assert "FsF-F2-01M" not in native_ids
    assert "FsF-F1-01MD" in native_ids
    core = next(item for item in result.metrics if item.id == "FsF-F2-01M")
    assert core.outcome == "indeterminate"


def test_failure_before_native_result_does_not_invent_a_payload(
    monkeypatch, native_outputs
):
    def fail_evaluation(_evaluator):
        raise RuntimeError("Evaluation failed before producing a result")

    monkeypatch.setattr(
        fuji_checks.core_metadata.FAIREvaluatorCoreMetadata, "evaluate", fail_evaluation
    )
    result = Assessor("FUJI").assess(metadata=METADATA, metadata_url=IDENTIFIER)

    assert result.raw == native_outputs
    native_ids = {item["metric_identifier"] for item in result.raw}
    assert "FsF-F2-01M" not in native_ids
    assert "FsF-R1.1-01M" in native_ids
    core = next(item for item in result.metrics if item.id == "FsF-F2-01M")
    assert core.outcome == "error"


def test_native_results_survive_harmonized_conversion_failure(
    monkeypatch, native_outputs
):
    def fail_conversion(**_values):
        raise RuntimeError("Harmonized score conversion failed")

    monkeypatch.setattr(fuji_checks, "Score", fail_conversion)
    result = Assessor("FUJI").assess(metadata=METADATA, metadata_url=IDENTIFIER)

    assert result.raw == native_outputs
    assert any(item["metric_identifier"] == "FsF-F2-01M" for item in result.raw)
    core = next(item for item in result.metrics if item.id == "FsF-F2-01M")
    assert core.outcome == "error"
    assert result.status == "completed_with_errors"


def test_runner_keeps_only_the_final_native_result_of_a_rerun():
    runner = fuji_checks.Runner(load_profile("fusji-offline@3.5.1").resources)
    first = runner.evaluate("FsF-R1.1-01M", {"license": ["MIT"]})
    last = runner.evaluate("FsF-R1.1-01M", {})

    assert first.native["test_status"] == "pass"
    assert last.native["test_status"] == "fail"
    assert runner.native_results == [last.native]


def test_captured_native_results_are_detached_from_mutable_results():
    runner = fuji_checks.Runner(load_profile("fusji-offline@3.5.1").resources)
    result = runner.evaluate("FsF-R1.1-01M", {"license": ["MIT"]})
    original = deepcopy(result.native)

    result.native["output"][0]["license"] = "Changed after evaluation"
    assert runner.native_results == [original]
    snapshot = runner.native_results
    snapshot[0]["metric_tests"].clear()
    assert runner.native_results == [original]


@pytest.mark.parametrize(
    "payload",
    [
        None,
        False,
        42,
        2.5,
        "another assessor's output",
        ["native", {"details": [1, None, True]}],
        {"assessment": {"score": 0.75}, "observations": []},
    ],
)
def test_raw_accepts_other_assessor_json_shapes(payload):
    profile = load_profile("fusji-offline@3.5.1").info.model_copy(
        update={"id": "example-profile", "adapter": "example"}
    )
    result = AssessmentResult(
        profile=profile,
        provenance=Provenance(
            engine_version="0.1.0",
            processor_version="1.0.0",
            input_digest="0" * 64,
            resources=(),
        ),
        tests=(),
        metrics=(),
        raw=payload,
    )

    assert result.raw == payload
    assert AssessmentResult.model_validate_json(result.model_dump_json()).raw == payload


def test_raw_defaults_to_none_when_an_adapter_has_no_native_payload():
    result = AssessmentResult(
        profile=load_profile("fusji-offline@3.5.1").info,
        provenance=Provenance(
            engine_version="0.1.0",
            processor_version="1.0.0",
            input_digest="0" * 64,
            resources=(),
        ),
        tests=(),
        metrics=(),
    )

    assert result.raw is None
