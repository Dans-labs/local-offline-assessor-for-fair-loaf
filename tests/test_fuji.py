import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from fair_offline_assessor import load_profile
from fair_offline_assessor._fuji import evaluate_core_metadata
from fair_offline_assessor.models import ProfileError


def metadata():
    return {
        "creator": ["Example author"],
        "title": "Example dataset",
        "object_identifier": "https://example.org/dataset",
        "publication_date": "2026-01-01",
        "publisher": "Example publisher",
        "object_type": "Dataset",
        "summary": "Example description",
        "keywords": ["soil"],
    }


@pytest.fixture
def definitions():
    return load_profile("fusji-offline@3.5.1").resources["fuji:metrics"]


@pytest.mark.parametrize(
    ("kind", "earned", "maturity", "outcomes"),
    [
        ("rich", 2, 3, ("pass", "pass")),
        ("citation", 1, 2, ("pass", "fail")),
        ("sparse", 0, 0, ("fail", "fail")),
        ("empty", 0, 0, ("fail", "fail")),
    ],
)
def test_core_metadata_preserves_upstream_results(
    definitions, kind, earned, maturity, outcomes
):
    supplied = metadata()
    if kind == "citation":
        del supplied["summary"], supplied["keywords"]
    elif kind == "sparse":
        supplied = {"title": "Example dataset"}
    elif kind == "empty":
        supplied = {}
    original = deepcopy(supplied)
    result = evaluate_core_metadata(supplied, definitions=definitions)
    assert supplied == original
    assert result["metric_identifier"] == "FsF-F2-01M"
    assert result["score"] == {"earned": earned, "total": 2}
    assert result["maturity"] == maturity
    assert result["test_status"] == ("pass" if earned else "fail")
    assert {
        key: test["metric_test_status"] for key, test in result["metric_tests"].items()
    } == dict(zip(("FsF-F2-01M-2", "FsF-F2-01M-3"), outcomes, strict=True))
    assert json.loads(json.dumps(result)) == result


def test_empty_fields_do_not_earn_points(definitions):
    for empty in (None, "", "  ", [], {}):
        result = evaluate_core_metadata(
            {**metadata(), "creator": deepcopy(empty)}, definitions=definitions
        )
        assert result["score"]["earned"] == 0


def test_assessments_do_not_share_mutable_state(definitions):
    supplied = metadata()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda value: evaluate_core_metadata(value, definitions=definitions),
                [supplied, {}, supplied, {}],
            )
        )
    assert [result["score"]["earned"] for result in results] == [2, 0, 2, 0]
    results[0]["output"]["core_metadata_found"]["creator"].clear()
    assert supplied["creator"] == ["Example author"]
    assert results[2]["output"]["core_metadata_found"]["creator"] == ["Example author"]


def test_other_metric_definitions_are_rejected(definitions):
    with pytest.raises(ProfileError) as error:
        evaluate_core_metadata(metadata(), definitions=definitions + b"\n")
    assert error.value.code == "unsupported_definitions"


def test_fresh_import_and_evaluation_do_not_access_the_network():
    script = """
import sys
attempts = []
def forbid_network(event, args):
    if event.startswith('socket.'):
        attempts.append(event)
        raise AssertionError(event)
sys.addaudithook(forbid_network)
from fair_offline_assessor import load_profile
from fair_offline_assessor._fuji import evaluate_core_metadata
definitions = load_profile('fusji-offline@3.5.1').resources['fuji:metrics']
assert evaluate_core_metadata({}, definitions=definitions)['score']['earned'] == 0
assert not any(name.startswith('fuji_server') for name in sys.modules)
assert not attempts
"""
    subprocess.run([sys.executable, "-c", script], check=True, timeout=10)  # noqa: S603
