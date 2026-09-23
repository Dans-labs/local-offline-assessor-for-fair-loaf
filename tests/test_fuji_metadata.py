import pytest

from fair_offline_assessor import AssessmentInput, load_profile
from fair_offline_assessor.assessors.fuji import checks as fuji_checks
from fair_offline_assessor.assessors.fuji.metadata import prepare_metadata


@pytest.fixture(scope="module")
def profile():
    return load_profile("fusji-offline@3.5.1")


def test_native_core_mapping_reaches_the_existing_fuji_evaluator(profile):
    request = AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@id": "urn:data",
            "@type": "Dataset",
            "identifier": "urn:published-id",
            "name": "Example",
            "description": "Soil measurements",
            "keywords": ["soil"],
            "creator": {"@type": "Person", "name": "Alice"},
            "publisher": {"name": "Archive"},
            "datePublished": "2026-01-01",
            "value": "Not an identifier",
        }
    )
    original = request.model_copy(deep=True)

    prepared = prepare_metadata(request, profile)

    expected = {
        "object_identifier": ["urn:published-id"],
        "object_type": ["Dataset"],
        "title": "Example",
        "summary": "Soil measurements",
        "keywords": ["soil"],
        "creator": ["Alice"],
        "publisher": ["Archive"],
        "publication_date": "2026-01-01",
    }
    for field, value in expected.items():
        assert prepared.fields[field] == value
    assert all(paths == ("/metadata",) for paths in prepared.sources.values())
    result = fuji_checks.Runner(profile.resources).evaluate(
        "FsF-F2-01M", prepared.fields
    )
    assert result.metric.score.observed_earned == 2
    assert [check.outcome for check in result.tests] == ["pass", "pass"]
    assert request == original


@pytest.mark.parametrize(
    ("field", "terms", "expected"),
    [
        ("title", ("title", "title", "name"), "DC value"),
        ("summary", ("description", "description", "description"), "DC value"),
        ("publication_date", ("date", "issued", "datePublished"), "DC value"),
        ("publisher", ("publisher", "publisher", "publisher"), ["DC value"]),
    ],
)
def test_native_core_term_priority_does_not_merge_competing_values(
    profile, field, terms, expected
):
    dc, dct, schema = terms
    request = AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@type": "Dataset",
            f"http://purl.org/dc/elements/1.1/{dc}": "DC value",
            f"http://purl.org/dc/terms/{dct}": "DC Terms value",
            schema: "Schema value",
        }
    )

    assert prepare_metadata(request, profile).fields[field] == expected


def test_native_aliases_and_local_references_are_document_evidence(profile):
    request = AssessmentInput(
        metadata={
            "@context": {
                "@vocab": "https://schema.org/",
                "label": "http://purl.org/dc/terms/title",
            },
            "@graph": [
                {
                    "@id": "urn:data",
                    "@type": "Dataset",
                    "label": {"@value": "Bodem", "@language": "nl"},
                    "author": {"@id": "urn:author"},
                    "identifier": {"@id": "_:identifier"},
                    "http://www.w3.org/ns/dcat#keyword": "soil",
                },
                {"@id": "urn:author", "name": "Alice"},
                {"@id": "_:identifier", "value": "10.1234/example"},
                {"@id": "urn:other", "description": "Unrelated record"},
            ],
        }
    )
    original = request.model_copy(deep=True)

    prepared = prepare_metadata(request, profile)

    assert prepared.fields["title"] == "Bodem"
    assert prepared.fields["creator"] == ["Alice"]
    assert prepared.fields["object_identifier"] == ["10.1234/example"]
    assert prepared.fields["keywords"] == ["soil"]
    assert "summary" not in prepared.fields
    assert prepared.sources["title"] == prepared.sources["creator"] == ("/metadata",)
    assert request == original


def test_native_provenance_namespaces_cover_the_supplied_rdf_union(profile):
    request = AssessmentInput(
        metadata={
            "@context": {
                "@vocab": "http://schema.org/",
                "prov": "http://www.w3.org/ns/prov#",
                "pav": "http://purl.org/pav/",
            },
            "@graph": [
                {
                    "@id": "urn:data",
                    "@type": "Dataset",
                    "name": "Example",
                    "contributor": "Alice",
                    "dateCreated": "2020-01-01",
                    "subjectOf": {"@id": "urn:run"},
                },
                {
                    "@id": "urn:run",
                    "@type": "prov:Activity",
                    "prov:used": {"@id": "urn:data"},
                },
                {
                    "@id": "urn:other-graph",
                    "@graph": [{"@id": "urn:unrelated", "pav:createdBy": "Bob"}],
                },
            ],
        }
    )
    original = request.model_copy(deep=True)

    prepared = prepare_metadata(request, profile)

    assert prepared.fields["contributor"] == ["Alice"]
    assert prepared.fields["publication_date"] == "2020-01-01"
    assert "http://www.w3.org/ns/prov#" in prepared.fields["provenance_namespaces"]
    assert "http://purl.org/pav/" in prepared.fields["provenance_namespaces"]
    assert prepared.sources["provenance_namespaces"] == ("/metadata",)
    assert request == original


@pytest.mark.parametrize("empty", [None, "  ", []])
def test_empty_native_core_values_do_not_earn_points(profile, empty):
    request = AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@type": "Dataset",
            "identifier": "urn:data",
            "datePublished": "2026-01-01",
            "name": empty,
            "creator": empty,
            "publisher": empty,
        }
    )

    fields = prepare_metadata(request, profile).fields

    assert not {"title", "creator", "publisher"} & fields.keys()
    result = fuji_checks.Runner(profile.resources).evaluate("FsF-F2-01M", fields)
    assert result.metric.score.observed_earned == 0


def test_native_rdf_literals_use_lexical_strings(profile):
    request = AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@type": "Dataset",
            "name": {"@value": "Bodem", "@language": "nl"},
            "keywords": [
                False,
                0,
                {
                    "@value": "2026",
                    "@type": "http://www.w3.org/2001/XMLSchema#gYear",
                },
            ],
        }
    )

    fields = prepare_metadata(request, profile).fields

    assert fields["title"] == "Bodem"
    assert set(fields["keywords"]) == {"false", "0", "2026"}


@pytest.mark.parametrize(
    ("lexical", "expected"),
    [("true", "true"), ("1", "true"), ("false", None), ("0", None)],
)
def test_native_boolean_reader_keeps_its_truthiness_filter(profile, lexical, expected):
    request = AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@type": "Dataset",
            "isAccessibleForFree": {
                "@value": lexical,
                "@type": "http://www.w3.org/2001/XMLSchema#boolean",
            },
        }
    )
    original = request.model_copy(deep=True)

    prepared = prepare_metadata(request, profile)

    assert prepared.fields.get("access_free") == expected
    assert request == original


def test_native_schema_creator_lookup_requires_a_local_name(profile):
    request = AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@type": "Dataset",
            "creator": "Alice",
        }
    )

    assert "creator" not in prepare_metadata(request, profile).fields
    named = request.model_copy(
        update={"metadata": {**request.metadata, "creator": {"name": "Alice"}}}
    )
    assert prepare_metadata(named, profile).fields["creator"] == ["Alice"]


def test_native_creator_names_can_come_from_another_supplied_named_graph(profile):
    request = AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@id": "urn:data",
                    "@type": "Dataset",
                    "creator": {"@id": "https://example.org/person"},
                },
                {
                    "@id": "urn:other-graph",
                    "@graph": [{"@id": "https://example.org/person", "name": "Alice"}],
                },
            ],
        }
    )

    assert prepare_metadata(request, profile).fields["creator"] == ["Alice"]


def test_native_schema_distributions_follow_local_links_and_url_priority(profile):
    request = AssessmentInput(
        metadata={
            "@context": {
                "@vocab": "https://schema.org/",
                "files": "https://schema.org/distribution",
                "download": {"@id": "https://schema.org/contentUrl", "@type": "@id"},
                "bytes": "https://schema.org/contentSize",
            },
            "@graph": [
                {
                    "@id": "urn:data",
                    "@type": "Dataset",
                    "files": [{"@id": "urn:a"}, {"@id": "urn:b"}],
                },
                {
                    "@id": "urn:a",
                    "download": "https://example.org/a",
                    "url": "https://example.org/ignored-mirror",
                    "bytes": "100",
                    "encodingFormat": "text/csv",
                },
                {"@id": "urn:b", "url": "https://example.org/b", "fileSize": "200"},
                {"@id": "urn:unrelated", "download": "https://example.org/ignored"},
                {
                    "@id": "urn:other-graph",
                    "@graph": [{"@id": "urn:b", "encodingFormat": "application/json"}],
                },
            ],
        }
    )
    original = request.model_copy(deep=True)

    prepared = prepare_metadata(request, profile)

    assert {
        item["url"]: item for item in prepared.fields["object_content_identifier"]
    } == {
        "https://example.org/a": {
            "url": "https://example.org/a",
            "type": "text/csv",
            "size": "100",
        },
        "https://example.org/b": {
            "url": "https://example.org/b",
            "type": "application/json",
            "size": "200",
        },
    }
    assert prepared.sources["file_formats"] == ("/metadata",)
    assert request == original


def test_native_schema_haspart_media_objects_are_distributions(profile):
    request = AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@type": "Dataset",
            "name": "Example",
            "description": "More descriptive properties than the file",
            "hasPart": {
                "@type": "MediaObject",
                "contentUrl": "https://example.org/data.csv",
                "encodingFormat": "text/csv",
            },
        }
    )

    fields = prepare_metadata(request, profile).fields

    assert fields["object_content_identifier"] == [
        {"url": "https://example.org/data.csv", "type": "text/csv", "size": None}
    ]


@pytest.mark.parametrize("format_term", ["dcat:mediaType", "dc:format", "dct:format"])
def test_native_dcat_distributions_use_access_url_and_string_descriptors(
    profile, format_term
):
    request = AssessmentInput(
        subject="urn:data",
        metadata={
            "@context": {
                "dcat": "http://www.w3.org/ns/dcat#",
                "dc": "http://purl.org/dc/elements/1.1/",
                "dct": "http://purl.org/dc/terms/",
            },
            "@id": "urn:data",
            "@type": "dcat:Dataset",
            "dcat:distribution": {
                "dcat:downloadURL": {"@id": "https://example.org/download"},
                "dcat:accessURL": {"@id": "https://example.org/access"},
                format_term: {
                    "@id": "https://www.iana.org/assignments/media-types/text/csv"
                },
                "dcat:byteSize": 12,
            },
        },
    )
    original = request.model_copy(deep=True)

    prepared = prepare_metadata(request, profile)

    assert prepared.fields["object_content_identifier"] == [
        {
            "url": "https://example.org/access",
            "type": "text/csv",
            "size": "12",
            "service": None,
        }
    ]
    assert (
        prepared.fields["file_formats"] == prepared.fields["object_content_identifier"]
    )
    assert prepared.sources["file_formats"] == ("/metadata",)
    assert request == original


def test_native_dcat_unavailable_distribution_retains_uri_and_diagnostic(profile):
    request = AssessmentInput(
        metadata={
            "@context": {"@vocab": "http://www.w3.org/ns/dcat#"},
            "@id": "urn:data",
            "@type": "Dataset",
            "distribution": {"@id": "https://example.invalid/distribution"},
        }
    )

    prepared = prepare_metadata(request, profile)

    assert prepared.fields["object_content_identifier"] == [
        {
            "url": "https://example.invalid/distribution",
            "type": None,
            "size": None,
            "service": None,
        }
    ]
    assert len(prepared.diagnostics) == 1
    assert prepared.diagnostics[0].code == "offline_reference"
    assert prepared.diagnostics[0].location == "/metadata"


def test_native_datacite_content_url_is_cleaned_to_a_distribution_list(profile):
    request = AssessmentInput(
        metadata={
            "agency": "DataCite",
            "id": "10.1234/example",
            "titles": [{"title": "Downloadable dataset"}],
            "contentUrl": "https://example.org/data.csv",
        },
        metadata_format="datacite-json",
    )
    original = request.model_copy(deep=True)

    prepared = prepare_metadata(request, profile)

    assert prepared.fields["object_content_identifier"] == [
        {"url": "https://example.org/data.csv"}
    ]
    assert prepared.sources["object_content_identifier"] == ("/metadata",)
    assert request == original


@pytest.mark.parametrize("dataset_license", [None, "MIT License"])
def test_native_dcat_distribution_licence_is_a_fallback(profile, dataset_license):
    request = AssessmentInput(
        metadata={
            "@context": {
                "@vocab": "http://purl.org/dc/terms/",
                "dcat": "http://www.w3.org/ns/dcat#",
            },
            "@id": "urn:data",
            "@type": "dcat:Dataset",
            "license": dataset_license,
            "dcat:distribution": {
                "dcat:downloadURL": {"@id": "https://example.org/data.csv"},
                "license": "CC-BY-4.0",
            },
        }
    )

    prepared = prepare_metadata(request, profile)

    assert prepared.fields["license"] == [dataset_license or "CC-BY-4.0"]
    assert prepared.sources["license"] == ("/metadata",)


def test_native_related_resources_keep_reference_terms_without_dereferencing(profile):
    request = AssessmentInput(
        metadata={
            "@context": {
                "@vocab": "https://schema.org/",
                "basedOn": "https://schema.org/isBasedOn",
            },
            "@graph": [
                {
                    "@id": "urn:data",
                    "@type": "Dataset",
                    "basedOn": {"@id": "urn:source"},
                    "citation": {"@id": "https://example.org/paper"},
                    "sameAs": {"@id": "https://example.org/copy"},
                },
                {"@id": "urn:source", "name": {"@value": "Bodem", "@language": "nl"}},
                {"@id": "https://example.org/paper", "name": "Paper title"},
                {"@id": "urn:unrelated", "citation": "https://example.org/ignored"},
            ],
        }
    )
    original = request.model_copy(deep=True)

    prepared = prepare_metadata(request, profile)

    assert {
        (entry["relation_type"], entry["related_resource"])
        for entry in prepared.fields["related_resources"]
    } == {
        ("https://schema.org/isBasedOn", "urn:source"),
        ("https://schema.org/citation", "https://example.org/paper"),
        ("https://schema.org/sameAs", "https://example.org/copy"),
    }
    assert prepared.fields["object_identifier"] == ["https://example.org/copy"]
    assert prepared.sources["related_resources"] == ("/metadata",)
    assert request == original
