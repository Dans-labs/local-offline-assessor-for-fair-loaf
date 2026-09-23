import json
from copy import deepcopy
from importlib.metadata import version
from pathlib import Path

import pytest

import fair_offline_assessor as library

# Captured from the baseline commit recorded in the fixture, before refactoring.
# Freeze the current unreleased contract before adding another assessor.
BASELINE = json.loads(
    Path(__file__)
    .with_name("fixtures")
    .joinpath("fuji", "3.5.1", "compatibility.json")
    .read_text(encoding="utf-8")
)


def canonical_result(result, case_id):
    # Native F-UJI serializes these sets in process-dependent order.
    # Compare their members without changing the raw response itself.
    result = deepcopy(result)
    for metric in result["raw"]:
        output = metric.get("output")
        if metric["metric_identifier"] == "FsF-F2-01M" and output:
            keywords = output.get("core_metadata_found", {}).get("keywords")
            if isinstance(keywords, list):
                keywords.sort()
        if (
            case_id == "ambiguous_selection"
            and metric["metric_identifier"] == "FsF-F2-01M"
        ):
            # Native graph iteration can choose either supplied Dataset. The
            # harmonized result still marks this ambiguous input indeterminate.
            assert output["core_metadata_found"]["title"] in {"first", "second"}
            output["core_metadata_found"]["title"] = "<either supplied title>"
        if metric["metric_identifier"] == "FsF-R1.3-01M" and output:
            output.sort(key=lambda item: json.dumps(item, sort_keys=True))
        if metric["metric_identifier"] == "FsF-R1.3-02D" and output:
            for item in output:
                if item.get("preference_reason"):
                    item["preference_reason"].sort()
    return result


@pytest.mark.parametrize("entry_point", ["named", "profile"])
@pytest.mark.parametrize("case", BASELINE["cases"], ids=lambda case: case["id"])
def test_fuji_matches_frozen_3_5_1_results(case, entry_point):
    request = deepcopy(case["request"])
    if entry_point == "named":
        result = library.Assessor("FUJI", version="3.5.1").assess(**request)
    else:
        result = library.assess(request, profile="fusji-offline@3.5.1")

    actual = result.model_dump(mode="json")
    assert actual.pop("profile") == BASELINE["profile"]
    provenance = actual["provenance"]
    assert provenance.pop("engine_version") == version("fair-offline-assessor")
    assert provenance.pop("processor_version") == version("PyLD")
    assert provenance.pop("resources") == BASELINE["resources"]
    assert canonical_result(actual, case["id"]) == canonical_result(
        case["expected"], case["id"]
    )
    assert request == case["request"]
