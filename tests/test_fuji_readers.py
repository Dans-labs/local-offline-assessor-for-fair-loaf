import json

import pytest
from rdflib import Dataset, Literal, URIRef
from rdflib.namespace import RDF

from fair_offline_assessor import AssessmentInput, Assessor, InputError
from fair_offline_assessor._fuji_readers import prepare_metadata
from fair_offline_assessor.profiles import load_profile


@pytest.fixture(scope="module")
def profile():
    return load_profile("fusji-offline@3.5.1")


def read(profile, metadata, metadata_format=None, **kwargs):
    return prepare_metadata(
        AssessmentInput(metadata=metadata, metadata_format=metadata_format, **kwargs),
        profile,
    )


def test_rdf_uses_upstream_title_priority_instead_of_merging_terms(profile):
    metadata = {
        "@context": "https://schema.org",
        "@id": "urn:data",
        "@type": "Dataset",
        "name": "Schema title",
        "http://purl.org/dc/terms/title": "DC Terms title",
        "http://purl.org/dc/elements/1.1/title": "DC title",
    }
    assert read(profile, metadata).fields["title"] == "DC title"


def test_upstream_selects_main_entity_and_accepts_more_than_datasets(profile):
    metadata = [
        {"@context": "https://schema.org", "@id": "urn:small", "@type": "Dataset"},
        {
            "@context": "https://schema.org",
            "@id": "urn:main",
            "@type": "ScholarlyArticle",
            "name": "Article",
            "description": "Description",
            "license": "MIT",
        },
    ]
    result = read(profile, metadata)
    assert result.fields["title"] == "Article"
    assert result.fields["object_type"] == ["ScholarlyArticle"]


def test_datacite_negotiated_json_uses_native_mapping_and_normalization(profile):
    metadata = {
        "agency": "DataCite",
        "id": "10.1234/example",
        "titles": [{"title": "DataCite title"}],
        "creators": [{"name": "Alice Example"}],
        "publisher": "Archive",
        "publicationYear": 2024,
        "types": {"resourceTypeGeneral": "Dataset"},
        "rightsList": [
            {"rights": "MIT", "rightsUri": "https://opensource.org/licenses/MIT"}
        ],
    }
    fields = read(profile, metadata, "datacite-json").fields
    assert fields["title"] == "DataCite title"
    assert fields["creator"] == ["Alice Example"]
    assert fields["object_identifier"] == "10.1234/example"
    assert fields["license"] == ["https://opensource.org/licenses/MIT"]
    assert fields["object_type"] == ["Dataset"]


@pytest.mark.parametrize(
    ("metadata", "title"),
    [
        (
            '<resource xmlns="http://datacite.org/schema/kernel-4"><titles><title>DataCite XML</title></titles><resourceType resourceTypeGeneral="Dataset">Data</resourceType></resource>',  # noqa: E501
            "DataCite XML",
        ),
        (
            '<mods xmlns="http://www.loc.gov/mods/v3"><titleInfo><title>MODS title</title></titleInfo></mods>',  # noqa: E501
            "MODS title",
        ),
        (
            '<dc xmlns="http://www.openarchives.org/OAI/2.0/oai_dc/" xmlns:d="http://purl.org/dc/elements/1.1/"><d:title>DC title</d:title></dc>',  # noqa: E501
            "DC title",
        ),
    ],
)
def test_xml_dispatch_uses_upstream_mappings(profile, metadata, title):
    fields = read(profile, metadata, "xml").fields
    assert title in fields["title"]


def test_xml_envelope_uses_first_record_as_upstream_does(profile):
    metadata = """<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
      <ListRecords><record><metadata>
      <dc xmlns="http://www.openarchives.org/OAI/2.0/oai_dc/"
          xmlns:d="http://purl.org/dc/elements/1.1/">
        <d:title>First</d:title>
      </dc></metadata></record>
      <record><metadata>
      <dc xmlns="http://www.openarchives.org/OAI/2.0/oai_dc/"
          xmlns:d="http://purl.org/dc/elements/1.1/">
        <d:title>Second</d:title>
      </dc></metadata></record></ListRecords></OAI-PMH>"""
    assert read(profile, metadata, "xml").fields["title"] == ["First"]


def test_turtle_and_jsonld_use_the_same_rdf_reader(profile):
    turtle = '@prefix s: <http://schema.org/> . <urn:data> a s:Dataset; s:name "Title"; s:license <https://opensource.org/licenses/MIT> .'  # noqa: E501
    jsonld = {
        "@context": "https://schema.org",
        "@id": "urn:data",
        "@type": "Dataset",
        "name": "Title",
        "license": "https://opensource.org/licenses/MIT",
    }
    rdf_fields = read(profile, turtle, "turtle").fields
    json_fields = read(profile, jsonld).fields
    assert rdf_fields == json_fields


def test_public_api_accepts_supplied_datacite_xml_without_fetching():
    metadata = '<resource xmlns="http://datacite.org/schema/kernel-4"><rightsList><rights rightsURI="https://opensource.org/licenses/MIT">MIT</rights></rightsList></resource>'  # noqa: E501
    result = Assessor("FUJI", version="3.5.1").assess(
        metadata=metadata, metadata_format="xml"
    )
    assert next(c for c in result.tests if c.id == "FsF-R1.1-01M-1").outcome == "pass"
    assert isinstance(result.raw, list)


@pytest.mark.parametrize("metadata_format", ["xml", "rdfxml"])
def test_xml_external_entities_are_rejected_before_native_parsing(
    profile, metadata_format
):
    metadata = (
        '<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///etc/passwd">]><x>&secret;</x>'
    )
    with pytest.raises(InputError, match="DOCTYPE"):
        read(profile, metadata, metadata_format)


def test_remote_jsonld_context_is_never_fetched(profile):
    with pytest.raises(InputError) as error:
        read(
            profile, {"@context": "https://example.invalid/context", "@type": "Dataset"}
        )
    assert error.value.code == "unknown_context"


def test_datacite_rest_envelope_is_not_silently_remapped(profile):
    with pytest.raises(InputError) as error:
        read(
            profile,
            {"data": {"attributes": {"titles": [{"title": "API"}]}}},
            "datacite-json",
        )
    assert error.value.code == "unsupported_datacite_shape"


def test_json_text_preserves_native_mapping(profile):
    metadata = {"@context": "https://schema.org", "@type": "Dataset", "name": "Title"}
    assert read(profile, json.dumps(metadata)).fields == read(profile, metadata).fields


@pytest.mark.parametrize("url", [None, "https://example.org/data.csv"])
def test_datacite_public_path_runs_native_final_cleanup(url):
    result = Assessor("FUJI").assess(
        metadata={
            "agency": "DataCite",
            "id": "10.1234/example",
            "titles": [{"title": "DataCite title"}],
            "types": {"resourceTypeGeneral": "Dataset"},
            "contentUrl": url,
            "rightsList": [{"rightsUri": "https://opensource.org/licenses/MIT"}],
        },
        metadata_format="datacite-json",
    )
    assert result.coverage.errors == 0
    checks = {check.id: check for check in result.tests}
    assert checks["FsF-R1.1-01M-1"].outcome == "pass"
    assert checks["FsF-F1-01MD-2"].outcome == ("pass" if url else "indeterminate")
    assert any(item["metric_identifier"] == "FsF-R1.1-01M" for item in result.raw)


def test_native_reader_error_keeps_independent_identifier_evidence():
    result = Assessor("FUJI").assess(
        metadata={"agency": "DataCite", "contentUrl": ["https://example.org/data"]},
        metadata_format="datacite-json",
        metadata_url="https://doi.org/10.1234/example",
    )
    assert {note.code for note in result.diagnostics} == {"metadata_reader_error"}
    checks = {check.id: check for check in result.tests}
    assert checks["FsF-R1.1-01M-1"].outcome == "indeterminate"
    assert checks["FsF-F1-02MD-1"].outcome == "pass"
    assert result.coverage.errors == 0


def test_public_html_combines_native_sources_and_reports_unreadable_contexts():
    html = """<html><head>
      <script type="application/ld+json">{"@context":"https://missing.invalid/context","@type":"Dataset"}</script>
      <meta name="DC.title" content="Title">
      <meta name="DCTERMS.license" content="https://opensource.org/licenses/MIT">
      </head><body></body></html>"""
    result = Assessor("FUJI").assess(metadata=html, metadata_format="html")
    assert "unknown_context" in {note.code for note in result.diagnostics}
    checks = {check.id: check for check in result.tests}
    assert checks["FsF-R1.1-01M-1"].outcome == "pass"
    assert checks["FsF-F2-01M-2"].outcome == "indeterminate"
    assert result.coverage.errors == 0
    assert any(item["metric_identifier"] == "FsF-R1.1-01M" for item in result.raw)


def test_public_html_uses_native_merge_priority(profile):
    html = """<html><head>
      <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Dataset","name":"First title"}
      </script>
      <meta name="DC.title" content="Different title">
      </head><body></body></html>"""
    fields = read(profile, html, "html").fields
    assert fields["title"] == "First title"


@pytest.mark.parametrize("format_", ["turtle", "n3", "nt", "nquads", "trig", "rdfxml"])
def test_explicit_rdf_encodings_use_native_reader(profile, format_):
    graph = Dataset()
    graph.default_graph.add(
        (URIRef("urn:data"), RDF.type, URIRef("http://schema.org/Dataset"))
    )
    graph.default_graph.add(
        (URIRef("urn:data"), URIRef("http://schema.org/name"), Literal("Title"))
    )
    target = graph if format_ in {"nquads", "trig"} else graph.default_graph
    content = target.serialize(format="xml" if format_ == "rdfxml" else format_)
    assert read(profile, content, format_).fields["title"] == "Title"


def test_invalid_embedded_json_keeps_other_sources_without_conclusive_absence():
    html = """<html><head>
      <script type="application/ld+json">{broken json}</script>
      <meta name="DC.title" content="Title">
      <meta name="DCTERMS.license" content="https://opensource.org/licenses/MIT">
      </head></html>"""
    result = Assessor("FUJI").assess(metadata=html, metadata_format="html")
    assert {note.code for note in result.diagnostics} == {"invalid_embedded_metadata"}
    checks = {check.id: check for check in result.tests}
    assert checks["FsF-R1.1-01M-1"].outcome == "pass"
    assert checks["FsF-F2-01M-2"].outcome == "indeterminate"
    assert checks["FsF-F2-01M-2"].score is None
    assert result.coverage.errors == 0
