import pytest
from pydantic import ValidationError

from fair_offline_assessor.models import (
    Profile,
)


def profile_data():
    return {
        "schema_version": 1,
        "id": "example:metadata",
        "version": "1.0.0",
        "title": "Metadata checks",
        "adapter": "example",
        "engine_requires": ">=0.1,<0.2",
        "adapter_version": "1.0.0",
        "resources": [],
    }


@pytest.mark.parametrize(
    "problem",
    [
        "schema",
        "version",
        "requirement",
        "adapter",
        "duplicate_resource",
        "metrics",
    ],
)
def test_profile_model_rejects_invalid_definitions(problem):
    data = profile_data()
    assert Profile.model_validate(data).version == "1.0.0"
    match problem:
        case "schema":
            data["schema_version"] = 2
        case "version":
            data["version"] = "latest"
        case "requirement":
            data["engine_requires"] = "anything"
        case "adapter":
            data["adapter"] = ""
        case "duplicate_resource":
            data["resources"] = [
                {
                    "id": "reference",
                    "version": "1",
                    "kind": "reference",
                    "digest": "0" * 64,
                }
            ] * 2
        case "metrics":
            data["metrics"] = []
    with pytest.raises(ValidationError):
        Profile.model_validate(data)
