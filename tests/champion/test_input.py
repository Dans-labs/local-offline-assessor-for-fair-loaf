from copy import deepcopy

import pytest

from fair_offline_assessor import AssessmentInput, ChampionInput
from fair_offline_assessor.assessors.champion.v0_5_12.input import (
    prepare_champion_input as prepare,
)


def test_target_subject_and_origin_are_distinct_and_preserved():
    request = {
        "metadata": {"@id": "urn:metadata", "urn:name": "Example"},
        "target_identifier": "10.1234/target",
        "subject": "urn:node",
        "metadata_url": "https://example.org/record.jsonld",
    }
    original = deepcopy(request)
    result = prepare(request)
    assert result.request.target_identifier == "10.1234/target"
    assert result.request.subject == "urn:node"
    assert result.request.metadata_url == "https://example.org/record.jsonld"
    assert result.invalid == {}
    assert request == original
    assert prepare(ChampionInput(**request)).request == result.request
    assert prepare({**request, "target_identifier": "other"}).digest != result.digest
    assert prepare({**request, "unexpected": "evidence"}).digest != result.digest


def test_omitted_and_none_target_have_same_digest_without_inference():
    request = AssessmentInput(
        metadata={"@id": "urn:metadata"},
        subject="urn:metadata",
        metadata_url="https://example.org/record",
    )
    absent = prepare(request)
    explicit = prepare({**request.model_dump(), "target_identifier": None})
    assert absent.digest == explicit.digest
    assert absent.request.target_identifier is None
    assert prepare(absent.request).digest == absent.digest


@pytest.mark.parametrize("target", [b"bytes", "\ud800"], ids=["type", "unicode"])
def test_invalid_target_is_diagnosed_without_discarding_metadata(target):
    result = prepare(
        {"metadata": {"urn:title": "Example"}, "target_identifier": target}
    )
    assert result.request.target_identifier is None
    assert result.request.metadata == {"urn:title": "Example"}
    assert result.invalid["target_identifier"].code == "invalid_target_identifier"
    assert result.invalid["target_identifier"].location == "/target_identifier"
    assert result.digest != prepare({"metadata": {"urn:title": "Example"}}).digest


def test_bad_metadata_retains_a_usable_target_and_original_digest():
    result = prepare({"metadata": None, "target_identifier": "10.1234/data"})
    assert "metadata" in result.invalid
    assert result.request.metadata == {}
    assert result.request.target_identifier == "10.1234/data"
    assert (
        result.digest
        != prepare({"metadata": {}, "target_identifier": "10.1234/data"}).digest
    )


def test_invalid_base_fields_and_extra_fields_still_have_diagnostics():
    result = prepare(
        {
            "metadata": {},
            "metadata_url": 42,
            "extra/value": True,
            "target_identifier": "urn:target",
        }
    )
    assert set(result.invalid) == {"metadata_url", "extra/value"}
    assert result.invalid["extra/value"].location == "/extra~1value"
    assert result.request.metadata_url is None
    assert result.request.target_identifier == "urn:target"
