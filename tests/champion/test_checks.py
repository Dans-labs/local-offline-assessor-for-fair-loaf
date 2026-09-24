import json
from pathlib import Path

import pytest

from fair_offline_assessor import ProfileError
from fair_offline_assessor.assessors.champion.v0_5_12.checks import (
    CheckContext,
    evaluate_check,
)
from fair_offline_assessor.assessors.champion.v0_5_12.graph import prepare_graph
from fair_offline_assessor.assessors.champion.v0_5_12.input import (
    prepare_champion_input,
)

FIXTURES = [
    json.loads(
        (
            Path(__file__).parents[1] / f"fixtures/champion/0.5.12/{name}.json"
        ).read_text()
    )
    for name in ("identifiers", "graph", "conditional")
]


@pytest.mark.parametrize(
    ("sources", "case"),
    [
        pytest.param(fixture["sources"], case, id=case["case_id"])
        for fixture in FIXTURES
        for case in fixture["cases"]
    ],
)
def test_scenario_matches_reviewed_decisions(
    sources, case, champion_profile, definitions
):
    prepared = prepare_champion_input(case["request"])
    graph = None
    if "metadata" not in prepared.invalid:
        graph = prepare_graph(prepared.request, champion_profile)
    context = CheckContext(prepared, graph, definitions)
    decisions = {
        test_id: evaluate_check(test_id, context) for test_id in case["expected"]
    }
    assert {
        test_id: [decision.outcome, decision.reason_code]
        for test_id, decision in decisions.items()
    } == case["expected"]
    for test_id, decision in decisions.items():
        definition = next(d for d in definitions.tests if d.id == test_id)
        assert sources[test_id] == {
            "path": definition.source_path,
            "sha256": definition.source_digest,
        }
        if decision.outcome != "indeterminate":
            assert decision.evidence
            for evidence in decision.evidence:
                if evidence.resource == "assessment_input":
                    assert evidence.digest == prepared.digest
                    assert evidence.location in (
                        "/metadata",
                        "/target_identifier",
                        "/metadata_url",
                    )
                else:
                    assert graph is not None
                    assert evidence in graph.evidence


def test_unknown_check_is_rejected(definitions):
    context = CheckContext(prepare_champion_input({"metadata": {}}), None, definitions)
    with pytest.raises(ProfileError) as error:
        evaluate_check("not-a-check", context)
    assert error.value.code == "unsupported_definitions"
