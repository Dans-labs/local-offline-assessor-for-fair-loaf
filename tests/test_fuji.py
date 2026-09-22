import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from fair_offline_assessor import AssessmentInput, _fuji, load_profile
from fair_offline_assessor._fuji_metadata import prepare_metadata, select_dataset
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
assert not any(name.startswith('fuji_server') for name in sys.modules)
result = assess(AssessmentInput(metadata={
    '@context': 'https://schema.org', '@type': 'Dataset', 'name': 'Example',
    'creator': {'@id': 'https://example.org/person'},
    'http://www.w3.org/ns/prov#wasGeneratedBy': {'@id': 'https://example.org/run'},
    'http://purl.org/pav/createdBy': {'@id': 'https://example.org/person'},
    'license': {'@id': 'https://example.org/custom-licence'},
    'conditionsOfAccess': 'Available on request.',
    'citation': ['A study by Alice', '10.5072/example', 'taxonomy:9606'],
    'variableMeasured': {'name': 'temperature'},
    'distribution': [{'contentUrl': {'@value': identifier},
        'encodingFormat': 'text/csv', 'contentSize': '123'} for identifier in (
        'https://example.org/data.csv', 'taxonomy:9606', 'ark:/12345/example',
        'https://w3id.org/example', 'hdl:12345/example', 'unrecognised',
        '550e8400-e29b-41d4-a716-446655440000', 'd41d8cd98f00b204e9800998ecf8427e'
    )]
}, metadata_url='https://doi.org/10.5072/example'), profile='fusji-offline@3.5.1')
assert result.status == 'completed'
outcomes = {check.id: check.outcome for check in result.tests}
assert outcomes['FsF-F1-02MD-1'] == 'pass'
assert outcomes['FsF-F1-02MD-4'] == 'pass'
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
