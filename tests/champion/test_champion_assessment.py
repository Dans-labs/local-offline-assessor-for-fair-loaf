import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest
from pyld import jsonld

import fair_offline_assessor as library
from fair_offline_assessor.assessors.champion.v0_5_12 import adapter, checks

PROFILE = "fair-champion-offline@0.5.12"
REQUEST = {
    "target_identifier": "10.1234/abc",
    "metadata_url": "https://example.org/metadata",
    "metadata": {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": "Example",
        "identifier": "10.1234/abc",
        "license": "CC0",
        "contentUrl": {"@id": "https://example.org/data"},
    },
}


def findings(result):
    return {test.id.removeprefix("test_FM_"): test for test in result.tests}


def stable_result(result):
    # Raw execution UUIDs/timestamps belong to each run; checked separately below.
    return result.model_dump(exclude={"raw"})


def test_public_champion_result_preserves_pins_outcomes_and_raw():
    request = deepcopy(REQUEST)
    result = library.Assessor("fair_champion", version="0.5.12").assess(**request)
    for other in (
        library.Assessor("FAIR_CHAMPION").assess(**request),
        library.assess(library.ChampionInput(**request), profile=PROFILE),
        library.assess(request, profile=PROFILE),
    ):
        assert stable_result(other) == stable_result(result)
    assert request == REQUEST
    assert (len(result.tests), len(result.metrics)) == (16, 13)
    assert result.coverage.model_dump() == {
        "evaluated": 14,
        "indeterminate": 2,
        "errors": 0,
        "not_applicable": 0,
        "total": 16,
    }
    assert result.status == "completed"
    assert all(
        item.score is None and item.level is None
        for item in (*result.tests, *result.metrics)
    )
    profile = library.load_profile(PROFILE)
    catalog = json.loads(profile.resources["champion:tests"])
    assert {t.id: t.metric for t in result.tests} == {
        d["id"]: d["metric"] for d in catalog
    }
    assert {(r.id, r.digest) for r in result.provenance.resources} == {
        (key, sha256(content).hexdigest()) for key, content in profile.resources.items()
    }
    assert {m.id: m.outcome for m in result.metrics}[
        "https://w3id.org/fair-metrics/general/FM_A1-1_M_OpenProt"
    ] == "pass"
    assert len(result.raw) == 16
    by_id = {test.id: test for test in result.tests}
    run_ids = set()
    for document in result.raw:
        nodes = {
            node["@type"]: node
            for node in document["@graph"]
            if isinstance(node["@type"], str)
        }
        native = nodes["ftr:TestResult"]
        execution = nodes["ftr:TestExecutionActivity"]
        target = nodes["prov:Entity"]
        for node in (native, execution, target):
            UUID(node["@id"].rsplit(":", 1)[1])
            assert node["@id"] not in run_ids
            run_ids.add(node["@id"])
        test_id = native["ftr:outputFromTest"]["@id"].rsplit(":", 1)[1]
        assert native["prov:value"] == {
            "@value": by_id[test_id].outcome,
            "@language": "en",
        }
        assert native["prov:wasGeneratedBy"] == {"@id": execution["@id"]}
        assert (
            execution["prov:used"]
            == native["ftr:assessmentTarget"]
            == {"@id": target["@id"]}
        )
        assert target["dct:identifier"] == "10.1234/abc"
        datetime.fromisoformat(native["prov:generatedAtTime"]["@value"])
        # Contexts are inline; expanding the actual output must work offline.
        assert len(jsonld.expand(document)) == 4
        if test_id == "test_FM_F1_M_IdentUnique":
            expected = json.loads(
                (
                    Path(__file__).parents[1] / "fixtures/champion/0.5.12/raw.json"
                ).read_text()
            )["expected"]
            normalized = json.dumps(document)
            for node, token in (
                (native, "RESULT"),
                (execution, "EXECUTION"),
                (target, "TARGET"),
            ):
                normalized = normalized.replace(node["@id"], token)
            normalized = normalized.replace(
                native["prov:generatedAtTime"]["@value"], "TIMESTAMP"
            )
            assert json.loads(normalized) == expected


def test_invalid_metadata_preserves_target_only_checks():
    result = library.Assessor("FAIR_CHAMPION").assess(
        metadata=None, target_identifier="10.1234/abc"
    )
    tests = findings(result)
    assert {key for key, test in tests.items() if test.outcome == "pass"} == {
        "A1_1_M_OpenProt",
        "A1_2_M_Auth",
        "A2_M_MetaLong",
        "F1_M_IdentPersistent",
        "F1_M_IdentUnique",
    }
    assert tests["I1_M_FormalLangSyntax"].reason_code == "unsupported_input"
    assert result.coverage.evaluated == 5
    assert result.coverage.errors == 0
    assert result.diagnostics[0].code == "unsupported_input"


@pytest.mark.parametrize(
    ("metadata", "code"),
    [
        (
            {"@context": "https://unknown.example/context", "name": "x"},
            "unknown_context",
        ),
        (
            [
                {"@id": name, "@graph": [{"urn:title": "x"}]}
                for name in ("urn:first", "urn:second")
            ],
            "ambiguous_graph",
        ),
    ],
)
def test_graph_preparation_diagnostics_block_only_dependent_checks(metadata, code):
    result = library.Assessor("FAIR_CHAMPION").assess(
        metadata=metadata, target_identifier="10.1234/abc"
    )
    tests = findings(result)
    assert tests["I1_M_FormalLangSyntax"].reason_code == code
    assert tests["A2_M_MetaLong"].outcome == "pass"
    assert result.diagnostics[0].code == code
    assert result.coverage.errors == 0


def test_empty_and_graph_only_requests_keep_missing_evidence_distinct():
    assessor = library.Assessor("FAIR_CHAMPION")
    empty = assessor.assess(metadata={})
    assert empty.coverage.evaluated == 7
    assert empty.coverage.indeterminate == 9
    assert (
        next(m for m in empty.metrics if m.id.endswith("FM_R1-1_M_StdLic")).outcome
        == "fail"
    )
    result = assessor.assess(
        metadata={"@type": "urn:Record", "http://purl.org/dc/terms/title": "Graph only"}
    )
    tests = findings(result)
    assert tests["I1_M_FormalLangSyntax"].outcome == "pass"
    assert tests["I2_M_FAIRVocabSyntax"].outcome == "pass"
    assert tests["I3_M_QualRef"].reason_code == "missing_evidence"
    assert tests["F1_M_IdentUnique"].reason_code == "missing_evidence"
    assert all(
        "dct:identifier" not in node
        for document in result.raw
        for node in document["@graph"]
        if node["@type"] == "prov:Entity"
    )


def test_evaluator_error_is_isolated_and_metric_summaries_are_conservative(monkeypatch):
    original = checks.evaluate_check
    overrides = {
        "test_FM_A1_1_M_OpenProt_Data": "fail",
        "test_FM_A1_2_M_Auth": "fail",
        "test_FM_A1_2_M_DataAuth": "indeterminate",
        "test_FM_R1_1_M_StdLic_strong": "indeterminate",
    }

    def evaluate(test_id, context):
        if test_id == "test_FM_R1_1_M_StdLic":
            raise RuntimeError("internal failure detail")
        if test_id in overrides:
            return checks.CheckDecision(
                overrides[test_id], "test_case", "Reviewed test case"
            )
        return original(test_id, context)

    monkeypatch.setattr(checks, "evaluate_check", evaluate)
    result = library.Assessor("FAIR_CHAMPION").assess(**REQUEST)
    metrics = {m.id.rsplit("/", 1)[1]: m.outcome for m in result.metrics}
    assert metrics["FM_A1-1_M_OpenProt"] == "partial"
    assert metrics["FM_A1-2_M_Auth"] == "indeterminate"
    assert metrics["FM_R1-1_M_StdLic"] == "error"
    assert result.status == "completed_with_errors"
    assert result.coverage.errors == 1
    assert findings(result)["F1_M_IdentUnique"].outcome == "pass"
    assert len(result.raw) == 15  # The failed evaluator emitted no assessor result.
    assert "internal failure detail" not in result.model_dump_json()

    def broken_graph(*_args):
        raise RuntimeError("internal graph failure")

    monkeypatch.setattr(checks, "evaluate_check", original)
    monkeypatch.setattr(adapter, "prepare_graph", broken_graph)
    result = library.Assessor("FAIR_CHAMPION").assess(**REQUEST)
    tests = findings(result)
    assert tests["I1_M_FormalLangSyntax"].outcome == "error"
    assert tests["A2_M_MetaLong"].outcome == "pass"
    assert result.diagnostics[0].code == "evaluator_error"
    assert len(result.raw) == result.coverage.total - result.coverage.errors
    assert "internal graph failure" not in result.model_dump_json()


def test_mixed_assessors_keep_contexts_and_requests_independent():
    context = "https://example.org/context"
    requests = [
        {
            "metadata": {"@context": context, "@type": "Dataset", "license": "MIT"},
            "local_contexts": {context: {"@context": {"@vocab": "http://schema.org/"}}},
        },
        {
            "metadata": {"@context": context, "@type": "Record", "license": "MIT"},
            "local_contexts": {
                context: {"@context": {"@vocab": "https://unknown.example/"}}
            },
        },
    ]
    before = deepcopy(requests)
    assessors = [library.Assessor("FUJI"), library.Assessor("FAIR_CHAMPION")]

    def run(index):
        return stable_result(assessors[index].assess(**requests[index]))

    expected = [run(0), run(1)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(run, [1, 0, 1, 0])) == [expected[i] for i in (1, 0, 1, 0)]
    assert [run(1), run(0)] == expected[::-1]
    assert requests == before
