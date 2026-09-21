from copy import deepcopy

import pytest
from pydantic import ValidationError

from fair_offline_assessor import AssessmentInput
from fair_offline_assessor.models import Capture


@pytest.fixture
def capture_data():
    return {
        "id": "download",
        "resource_url": "https://example.org/data?version=1&format=csv",
        "captured_at": "2026-01-01T12:00:00+01:00",
        "exchanges": [
            {
                "method": "GET",
                "url": "https://example.org/data?version=1&format=csv",
                "status": 307,
                "headers": [["Location", "/files/data?token=a%2Fb&part=1&part=2"]],
            },
            {
                "method": "GET",
                "url": "https://example.org/files/data?token=a%2Fb&part=1&part=2",
                "status": 200,
                "body": "x,y\n1,2\n",
            },
        ],
    }


def test_capture_round_trip_preserves_the_observation(capture_data):
    capture_data["resource_url"] = (
        "https://EXAMPLE.org:443/data?version=1&format=csv#dataset"
    )
    capture_data["exchanges"][0]["headers"][0][0] = "lOcAtIoN"
    captured = Capture.model_validate(capture_data)
    assert captured.model_dump(mode="json") == {
        **capture_data,
        "exchanges": [
            {"request_headers": [], "headers": [], "body": None, **exchange}
            for exchange in capture_data["exchanges"]
        ],
    }
    assert Capture.model_validate_json(captured.model_dump_json()) == captured


@pytest.mark.parametrize(
    "url",
    ["ftp://example.org/data", "https://example.org:bad/data", "https://exa\nmple.org"],
)
def test_capture_rejects_invalid_http_urls(capture_data, url):
    for field in ("resource_url", "exchange_url"):
        data = deepcopy(capture_data)
        if field == "resource_url":
            data[field] = url
        else:
            data["exchanges"][0]["url"] = url
        with pytest.raises(ValidationError, match=r"URL|url") as error:
            Capture.model_validate(data)
        assert error.value.errors()[0]["loc"] == (
            ("resource_url",) if field == "resource_url" else ("exchanges", 0, "url")
        )


def test_redirect_can_clear_the_query(capture_data):
    first, last = capture_data["exchanges"]
    first["headers"] = [["Location", "?#section"]]
    last["url"] = "https://example.org/data?"
    assert Capture.model_validate(capture_data).exchanges[-1].url == last["url"]


@pytest.mark.parametrize(
    "problem",
    [
        "start",
        "query",
        "query_escaping",
        "invalid_location",
        "location",
        "duplicate_location",
        "status",
        "method",
    ],
)
def test_capture_rejects_disconnected_requests(capture_data, problem):
    first, last = capture_data["exchanges"]
    match problem:
        case "start":
            capture_data["resource_url"] = "https://example.org/other"
        case "query":
            last["url"] = "https://example.org/files/data?token=a/b&part=2&part=1"
        case "query_escaping":
            first["headers"] = [["Location", "/files/data?name=O'Reilly"]]
            last["url"] = "https://example.org/files/data?name=O%27Reilly"
        case "invalid_location":
            first["headers"] = [["Location", "https:///files/data"]]
            last["url"] = "https://example.org/files/data"
        case "location":
            first["headers"] = []
        case "duplicate_location":
            first["headers"].append(["location", "https://example.org/other"])
        case "status":
            first["status"] = 200
        case "method":
            last["method"] = "HEAD"
    with pytest.raises(ValidationError):
        Capture.model_validate(capture_data)


def test_capture_ids_must_be_unique(capture_data):
    with pytest.raises(ValidationError, match="Duplicate capture"):
        AssessmentInput(metadata={}, captures=[capture_data, capture_data])
