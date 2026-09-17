import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from fair_offline_assessor import AssessmentInput, _fuji, load_profile
from fair_offline_assessor._fuji_metadata import prepare_metadata
from fair_offline_assessor._metadata import select_dataset
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
def runner():
    return _fuji.Runner(load_profile("fusji-offline@3.5.1").resources)


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
    runner, kind, earned, maturity, outcomes
):
    supplied = metadata()
    if kind == "citation":
        del supplied["summary"], supplied["keywords"]
    elif kind == "sparse":
        supplied = {"title": "Example dataset"}
    elif kind == "empty":
        supplied = {}
    original = deepcopy(supplied)
    result = runner.evaluate("FsF-F2-01M", supplied)
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


def test_empty_fields_do_not_earn_points(runner):
    for empty in (None, "", "  ", [], {}):
        result = runner.evaluate(
            "FsF-F2-01M", {**metadata(), "creator": deepcopy(empty)}
        )
        assert result.metric.score.observed_earned == 0


def test_assessments_do_not_share_mutable_state(runner):
    supplied = metadata()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda value: runner.evaluate("FsF-F2-01M", value),
                [supplied, {}, supplied, {}],
            )
        )
    assert [result.metric.score.observed_earned for result in results] == [2, 0, 2, 0]
    results[0].native["output"]["core_metadata_found"]["creator"].clear()
    assert supplied["creator"] == ["Example author"]
    assert results[2].native["output"]["core_metadata_found"]["creator"] == [
        "Example author"
    ]


def test_other_metric_definitions_are_rejected():
    resources = dict(load_profile("fusji-offline@3.5.1").resources)
    resources["fuji:metrics"] += b"\n"
    with pytest.raises(ProfileError) as error:
        _fuji.Runner(resources)
    assert error.value.code == "unsupported_definitions"


@pytest.mark.parametrize(
    ("status", "outcome", "earned"),
    [(None, "indeterminate", 0), (200, "pass", 1), (404, "fail", 0)],
)
def test_retrieval_distinguishes_missing_evidence_from_failure(
    runner, status, outcome, earned
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
    result = runner.evaluate_retrievability(data=data)
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
    runner, found, status, earned
):
    result = runner.evaluate_retrievability(
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
import socket
attempts = []
def forbid_timeout(value):
    raise AssertionError('global socket timeout changed')
socket.setdefaulttimeout = forbid_timeout
def forbid_network(event, args):
    # urllib3 checks local IPv6 support during import.
    if event == 'socket.__new__' or (event == 'socket.bind' and args[1] == ('::1', 0)):
        return
    if event.startswith('socket.'):
        attempts.append(event)
        raise AssertionError(event)
sys.addaudithook(forbid_network)
from fair_offline_assessor import AssessmentInput, assess, load_profile
from fair_offline_assessor._fuji import Runner
runner = Runner(load_profile('fusji-offline@3.5.1').resources)
core = runner.evaluate('FsF-F2-01M', {})
assert core.metric.score.observed_earned == 0
missing = runner.evaluate_retrievability()
assert missing.tests[0].outcome == 'indeterminate'
for status in (200, 404):
    result = runner.evaluate_retrievability(data={
        'https://example.org/data': {'url': 'https://example.org/data',
            'scheme': 'https', 'status_code': status}})
    assert result.tests[1].outcome == ('pass' if status == 200 else 'fail')
assert not any(name.startswith('fuji_server') for name in sys.modules)
result = assess(AssessmentInput(metadata={
    '@context': 'https://schema.org', '@type': 'Dataset', 'name': 'Example',
    'creator': {'@id': 'https://example.org/person'},
    'license': {'@id': 'https://example.org/custom-licence'},
    'conditionsOfAccess': 'Available on request.',
    'distribution': {'contentUrl': 'https://example.org/data.csv'}
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
    runner, value, details
):
    result = runner.evaluate("FsF-R1.1-01M", {"license": [value]})
    assert result.native["score"] == {"earned": 1, "total": 1}
    assert result.native["output"][0]["license"] == value
    assert result.native["output"][0]["details_url"] == details


def test_access_booleans_and_evaluator_mutations_are_isolated(runner):
    profile = load_profile("fusji-offline@3.5.1")
    inputs = [
        {"isAccessibleForFree": True},
        {"isAccessibleForFree": False},
        {"conditionsOfAccess": "MIT License", "license": {"@value": "Custom licence"}},
    ]
    original = deepcopy(inputs)

    def evaluate(metadata):
        request = AssessmentInput(
            metadata={
                "@context": "https://schema.org",
                "@type": "Dataset",
                **metadata,
            }
        )
        prepared = prepare_metadata(select_dataset(request, profile))
        original_fields = deepcopy(prepared.fields)
        result = runner.evaluate("FsF-A1-01M", prepared.fields)
        assert prepared.fields == original_fields
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(evaluate, inputs))
    assert [result.native["output"]["access_level"] for result in results] == [
        "public",
        "restricted",
        None,
    ]
    assert [result.native["test_status"] for result in results] == [
        "pass",
        "pass",
        "fail",
    ]
    assert all(
        result.native["score"] == {"earned": 0, "total": 1} for result in results
    )
    assert inputs == original


def test_evaluators_cannot_change_cached_catalogues_or_definitions(runner, monkeypatch):
    implementation = _fuji.EVALUATORS["FsF-R1.1-01M"].implementation
    original = implementation.evaluate

    def evaluate(self):
        original(self)
        self.fuji.SPDX_LICENSES.clear()
        self.fuji.METRICS["FsF-R1.1-01M"]["metric_tests"].clear()

    monkeypatch.setattr(implementation, "evaluate", evaluate)
    first = runner.evaluate("FsF-R1.1-01M", {"license": ["MIT License"]})
    second = runner.evaluate("FsF-R1.1-01M", {"license": ["MIT License"]})
    assert first == second
    assert (
        first.native["output"][0]["details_url"] == "http://spdx.org/licenses/MIT.html"
    )
    assert len(first.tests) == 1
    assert first.metric.score.observed_earned == 1
