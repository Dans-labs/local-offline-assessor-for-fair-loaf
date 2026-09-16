import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from fair_offline_assessor import _fuji, load_profile
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
    assert result.metric.id == "FsF-F2-01M"
    assert result.metric.principles == ("F2",)
    assert result.metric.outcome == ("pass" if earned else "fail")
    assert result.metric.score.observed_earned == earned
    assert result.metric.score.maximum == 2
    assert result.metric.score.percent == earned * 50
    assert result.metric.level.value == maturity
    assert tuple(check.outcome for check in result.tests) == outcomes
    assert all(check.metric == result.metric.id for check in result.tests)
    assert result.native["metric_identifier"] == "FsF-F2-01M"
    assert result.native["score"] == {"earned": earned, "total": 2}
    assert result.native["maturity"] == maturity
    assert result.native["test_status"] == ("pass" if earned else "fail")
    assert {
        key: test["metric_test_status"]
        for key, test in result.native["metric_tests"].items()
    } == dict(zip(("FsF-F2-01M-2", "FsF-F2-01M-3"), outcomes, strict=True))
    assert json.loads(json.dumps(result.native)) == result.native


def test_empty_fields_do_not_earn_points(definitions):
    for empty in (None, "", "  ", [], {}):
        result = evaluate_core_metadata(
            {**metadata(), "creator": deepcopy(empty)}, definitions=definitions
        )
        assert result.metric.score.observed_earned == 0


def test_assessments_do_not_share_mutable_state(definitions):
    supplied = metadata()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda value: evaluate_core_metadata(value, definitions=definitions),
                [supplied, {}, supplied, {}],
            )
        )
    assert [result.metric.score.observed_earned for result in results] == [2, 0, 2, 0]
    results[0].native["output"]["core_metadata_found"]["creator"].clear()
    assert supplied["creator"] == ["Example author"]
    assert results[2].native["output"]["core_metadata_found"]["creator"] == [
        "Example author"
    ]


def test_other_metric_definitions_are_rejected(definitions):
    with pytest.raises(ProfileError) as error:
        evaluate_core_metadata(metadata(), definitions=definitions + b"\n")
    assert error.value.code == "unsupported_definitions"


@pytest.mark.parametrize(
    ("status", "outcome", "earned"),
    [(None, "indeterminate", 0), (200, "pass", 1), (404, "fail", 0)],
)
def test_retrieval_distinguishes_missing_evidence_from_failure(
    definitions, status, outcome, earned
):
    data = (
        None
        if status is None
        else {
            "https://example.org/data.csv": {
                "url": "https://example.org/data.csv",
                "scheme": "https",
                "status_code": status,
            }
        }
    )
    original = deepcopy(data)
    result = _fuji.evaluate_retrievability(definitions=definitions, data=data)
    assert data == original
    assert [check.outcome for check in result.tests] == ["indeterminate", outcome]
    assert result.tests[0].score is None
    assert result.tests[0].reason_code == "missing_evidence"
    assert "FsF-A1-02MD-1" not in result.native["metric_tests"]
    assert result.metric.score.observed_earned == earned
    assert result.metric.score.maximum == 2
    assert result.metric.score.percent is None
    assert result.metric.outcome == ("pass" if earned else "indeterminate")


@pytest.mark.parametrize(
    ("found", "status", "earned"), [(True, 200, 2), (True, 404, 1), (False, 404, 0)]
)
def test_retrieval_preserves_upstream_scoring_when_evidence_is_complete(
    definitions, found, status, earned
):
    result = _fuji.evaluate_retrievability(
        definitions=definitions,
        metadata=[
            {
                "url": "https://example.org/metadata.jsonld",
                "metadata": metadata(),
                "schema": "https://schema.org/",
                "offering_method": "content_negotiation",
            }
        ]
        if found
        else [],
        data={
            "https://example.org/data.csv": {
                "url": "https://example.org/data.csv",
                "scheme": "https",
                "status_code": status,
            }
        },
    )
    assert [check.outcome for check in result.tests] == [
        "pass" if found else "fail",
        "pass" if status == 200 else "fail",
    ]
    assert result.metric.outcome == ("pass" if earned else "fail")
    assert result.metric.score.percent == earned * 50
    assert result.metric.level.value == (3 if earned else 0)
    assert result.native["score"] == {"earned": earned, "total": 2}


def test_fresh_import_and_evaluation_do_not_access_the_network():
    script = """
import sys
attempts = []
def forbid_network(event, args):
    # urllib3 checks local IPv6 support during import.
    if event == 'socket.__new__' or (event == 'socket.bind' and args[1] == ('::1', 0)):
        return
    if event.startswith('socket.'):
        attempts.append(event)
        raise AssertionError(event)
sys.addaudithook(forbid_network)
from fair_offline_assessor import AssessmentInput, assess, load_profile
from fair_offline_assessor._fuji import evaluate_core_metadata, evaluate_retrievability
definitions = load_profile('fusji-offline@3.5.1').resources['fuji:metrics']
core = evaluate_core_metadata({}, definitions=definitions)
assert core.metric.score.observed_earned == 0
missing = evaluate_retrievability(definitions=definitions)
assert missing.tests[0].outcome == 'indeterminate'
for status in (200, 404):
    result = evaluate_retrievability(definitions=definitions, data={
        'https://example.org/data': {'url': 'https://example.org/data',
            'scheme': 'https', 'status_code': status}})
    assert result.tests[1].outcome == ('pass' if status == 200 else 'fail')
assert not any(name.startswith('fuji_server') for name in sys.modules)
result = assess(AssessmentInput(metadata={
    '@context': 'https://schema.org', '@type': 'Dataset', 'name': 'Example',
    'creator': {'@id': 'https://example.org/person'},
    'license': {'@id': 'https://example.org/custom-licence'}
}), profile='fusji-offline@3.5.1')
assert result.status == 'completed'
assert not attempts
"""
    subprocess.run([sys.executable, "-c", script], check=True, timeout=10)  # noqa: S603


@pytest.mark.parametrize(
    ("value", "details"),
    [
        ("MIT License", "http://spdx.org/licenses/MIT.html"),
        (
            "https://spdx.org/licenses/Apache-2.0.html",
            "http://spdx.org/licenses/Apache-2.0.html",
        ),
        ("Custom permission from the author", None),
    ],
)
def test_licence_catalogue_keeps_native_lookup_without_changing_presence_score(
    definitions, value, details
):
    result = _fuji.evaluate_license(
        {"license": [value]},
        definitions=definitions,
        licenses=load_profile("fusji-offline@3.5.1").resources["fuji:licenses"],
    )
    assert result.native["score"] == {"earned": 1, "total": 1}
    assert result.native["output"][0]["license"] == value
    assert result.native["output"][0]["details_url"] == details
