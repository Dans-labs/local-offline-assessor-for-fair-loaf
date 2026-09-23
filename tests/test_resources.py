import json
from hashlib import sha256
from importlib.resources import files

import pytest
import yaml
from pyld import jsonld
from pyld.documentloader.frozen import FrozenDocumentLoader

from fair_offline_assessor import list_profiles, load_profile
from fair_offline_assessor.models import AssessmentResult, Profile


@pytest.mark.parametrize(
    ("name", "model", "mode"),
    [("profile", Profile, "validation"), ("result", AssessmentResult, "serialization")],
)
def test_bundled_schemas_match_current_models(name, model, mode):
    path = files("fair_offline_assessor").joinpath(
        "resources", "schemas", f"{name}-v1.json"
    )
    assert path.is_file(), f"Missing bundled schema: {name}"
    schema = json.loads(path.read_bytes())
    assert schema.pop("$schema") == "https://json-schema.org/draft/2020-12/schema"
    assert schema == model.model_json_schema(mode=mode)


def read_resources():
    root = files("fair_offline_assessor").joinpath("resources")
    manifest = json.loads(root.joinpath("resources.json").read_bytes())
    resources = {}
    for resource in manifest:
        content = root.joinpath(*resource["path"].split("/")).read_bytes()
        assert sha256(content).hexdigest() == resource["digest"]
        resources[resource["id"]] = resource, content
    return resources


def test_bundled_fuji_profile_loads_pinned_definitions():
    selection = "fusji-offline@3.5.1"
    assert selection in {f"{info.id}@{info.version}" for info in list_profiles()}
    loaded = load_profile(selection)
    assert loaded.info in list_profiles()
    assert loaded.profile.adapter == "fuji"
    assert loaded.profile.adapter_version == "1.0.0"
    resources = read_resources()
    reference, content = resources["fuji:metrics"]
    assert reference["format"] == "yaml"
    assert reference["version"] == loaded.profile.version == "3.5.1"
    assert reference["source"]["metric_version"] == "0.8"
    assert reference["source"]["commit"] == "9227fabb7f047475714f2e7622798b855c883f72"
    assert loaded.resources["fuji:metrics"] == content
    assert loaded.resources["schemaorg:context"] == resources["schemaorg:context"][1]
    metrics = yaml.safe_load(content)["metrics"]
    assert len({metric["metric_identifier"] for metric in metrics}) == 17
    assert (
        len(
            {
                test["metric_test_identifier"]
                for metric in metrics
                for test in metric["metric_tests"]
            }
        )
        == 31
    )
    assert sum(metric["total_score"] for metric in metrics) == 26


def test_bundled_context_expands_dataset_without_network():
    resource, content = read_resources()["schemaorg:context"]
    loader = FrozenDocumentLoader(
        documents={alias: json.loads(content) for alias in resource["aliases"]}
    )
    for alias in (
        "http://schema.org",
        "http://schema.org/",
        "https://schema.org",
        "https://schema.org/",
        "https://schema.org/version/30.0/schemaorgcontext.jsonld",
    ):
        assert jsonld.expand(
            {
                "@context": alias,
                "@type": "Dataset",
                "name": "Example",
                "isAccessibleForFree": False,
            },
            options={"documentLoader": loader},
        ) == [
            {
                "@type": ["http://schema.org/Dataset"],
                "http://schema.org/name": [{"@value": "Example"}],
                "http://schema.org/isAccessibleForFree": [{"@value": False}],
            }
        ]
