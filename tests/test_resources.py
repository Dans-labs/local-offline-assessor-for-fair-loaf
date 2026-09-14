import json
from hashlib import sha256
from importlib.resources import files

from pyld import jsonld
from pyld.documentloader.frozen import FrozenDocumentLoader


def read_resources():
    root = files("fair_offline_assessor").joinpath("resources")
    manifest = json.loads(root.joinpath("resources.json").read_bytes())
    resources = {}
    for resource in manifest:
        content = root.joinpath(*resource["path"].split("/")).read_bytes()
        assert sha256(content).hexdigest() == resource["digest"]
        resources[resource["id"]] = resource, content
    return resources


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
