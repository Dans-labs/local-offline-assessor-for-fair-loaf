import json
from hashlib import sha256
from importlib.resources import as_file, files

import pytest
from lxml import etree
from pyld import jsonld
from pyld.documentloader.frozen import FrozenDocumentLoader

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


def test_bundled_vocabularies_define_dataset_terms():
    resources = read_resources()
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    for name, term in (
        ("dublincore:terms", "http://purl.org/dc/terms/title"),
        ("dublincore:elements", "http://purl.org/dc/elements/1.1/title"),
        ("dublincore:types", "http://purl.org/dc/dcmitype/Dataset"),
    ):
        root = etree.fromstring(resources[name][1], parser)
        assert term in root.xpath(
            "//@rdf:about",
            namespaces={"rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"},
        )
    graph = jsonld.expand(
        json.loads(resources["dcat:vocabulary"][1]),
        options={"documentLoader": FrozenDocumentLoader(documents={})},
    )
    assert "http://www.w3.org/ns/dcat#Dataset" in {node["@id"] for node in graph}


def test_datacite_schema_resolves_all_includes_offline():
    root = files("fair_offline_assessor").joinpath("resources/metadata/datacite/4.7")
    with as_file(root) as directory:
        schema = etree.XMLSchema(
            etree.parse(
                str(directory / "metadata.xsd"),
                etree.XMLParser(resolve_entities=False, no_network=True),
            )
        )
    document = b"""<resource xmlns="http://datacite.org/schema/kernel-4">
      <identifier identifierType="DOI">10.1234/example</identifier>
      <creators><creator><creatorName>Example</creatorName></creator></creators>
      <titles><title>Example dataset</title></titles><publisher>Example</publisher>
      <publicationYear>2026</publicationYear>
      <resourceType resourceTypeGeneral="Dataset"/>
    </resource>"""
    assert schema.validate(etree.fromstring(document))
    assert not schema.validate(
        etree.fromstring(document.replace(b"Dataset", b"Unknown"))
    )
