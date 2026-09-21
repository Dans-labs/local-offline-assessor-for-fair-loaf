from copy import deepcopy

import pytest

from fair_offline_assessor import AssessmentInput, _fuji, load_profile
from fair_offline_assessor._fuji_metadata import prepare_metadata
from fair_offline_assessor._metadata import select_dataset


@pytest.fixture
def profile():
    return load_profile("fusji-offline@3.5.1")


def at_pointer(value, pointer):
    for part in pointer.split("/")[1:]:
        key = part.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def test_provenance_fields_keep_local_names_and_dates(profile):
    expected = {
        "contributor": ["Alice"],
        "right_holder": ["Archive"],
        "created_date": ["2020-01-01"],
        "modified_date": ["2021-01-01"],
        "accepted_date": ["2022-01-01"],
        "submitted_date": ["2023-01-01"],
    }
    request = AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@type": "Dataset",
            "contributor": {"name": "Alice"},
            "copyrightHolder": {"name": "Archive"},
            **{
                "http://purl.org/dc/terms/" + term: expected[field][0]
                for term, field in (
                    ("created", "created_date"),
                    ("modified", "modified_date"),
                    ("dateAccepted", "accepted_date"),
                    ("dateSubmitted", "submitted_date"),
                )
            },
        }
    )
    prepared = prepare_metadata(select_dataset(request, profile))
    assert prepared.fields == {
        "object_type": ["Dataset"],
        "namespaces": ["http://purl.org/dc/terms/", "http://schema.org/"],
        **expected,
    }
    assert not prepared.unmapped


def test_provenance_namespaces_follow_local_nodes_without_crossing_graphs(profile):
    request = AssessmentInput(
        metadata={
            "@context": {
                "@vocab": "http://schema.org/",
                "prov": "http://www.w3.org/ns/prov#",
                "pav": "http://purl.org/pav/",
                "activity": "prov:Activity",
            },
            "@graph": [
                {
                    "@id": "urn:data",
                    "@type": "Dataset",
                    "subjectOf": {"@list": [{"@id": "urn:run"}]},
                    "isPartOf": {"@id": "urn:other-graph"},
                    "description": {"@value": "text", "@type": "pav:Literal"},
                },
                {
                    "@id": "urn:run",
                    "@type": "activity",
                    "prov:used": {"@id": "urn:data"},
                },
                {"@id": "urn:unrelated", "pav:createdBy": "Bob"},
                {
                    "@id": "urn:other-graph",
                    "@graph": [{"@id": "urn:run", "pav:createdBy": "Bob"}],
                },
            ],
        }
    )
    selected = select_dataset(request, profile)
    original = deepcopy(selected)
    prepared = prepare_metadata(selected)
    assert prepared.fields["provenance_namespaces"] == ["http://www.w3.org/ns/prov#"]
    values = [
        at_pointer(selected.graph, path)
        for path in prepared.sources["provenance_namespaces"]
    ]
    assert len(values) == 2
    assert "http://www.w3.org/ns/prov#Activity" in values
    assert [{"@id": "urn:data"}] in values
    assert selected == original


def test_maps_core_fields_into_the_existing_fuji_evaluator(profile):
    request = AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@id": "urn:data",
            "@type": "Dataset",
            "name": "Example",
            "description": "Soil measurements",
            "keywords": ["soil"],
            "creator": {"@type": "Person", "name": "Alice"},
            "publisher": {"name": "Archive"},
            "datePublished": "2026-01-01",
            "value": "Not an identifier",
        }
    )
    selected = select_dataset(request, profile)
    original = deepcopy(selected)
    prepared = prepare_metadata(selected)
    assert prepared.fields == {
        "object_identifier": ["urn:data"],
        "object_type": ["Dataset"],
        "title": ["Example"],
        "summary": ["Soil measurements"],
        "keywords": ["soil"],
        "creator": ["Alice"],
        "publisher": ["Archive"],
        "publication_date": ["2026-01-01"],
        "namespaces": ["http://schema.org/"],
    }
    result = _fuji.Runner(profile.resources).evaluate("FsF-F2-01M", prepared.fields)
    assert result.metric.score.observed_earned == 2
    assert [check.outcome for check in result.tests] == ["pass", "pass"]
    assert selected == original


def test_mixed_vocabularies_aliases_and_local_references_keep_their_sources(profile):
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
                    "urn:unrelated/title": "Ignore",
                },
                {"@id": "urn:author", "name": "Alice"},
                {"@id": "_:identifier", "value": "10.1234/example"},
                {"@id": "urn:other", "description": "Not the selected dataset"},
            ],
        }
    )
    selected = select_dataset(request, profile)
    prepared = prepare_metadata(selected)
    assert prepared.fields["title"] == ["Bodem"]
    assert prepared.fields["creator"] == ["Alice"]
    assert prepared.fields["object_identifier"] == ["urn:data", "10.1234/example"]
    assert prepared.fields["keywords"] == ["soil"]
    assert "summary" not in prepared.fields
    assert prepared.unmapped == ("urn:unrelated/title",)
    sources = [
        at_pointer(selected.graph, pointer)
        for pointer in prepared.sources["title"] + prepared.sources["creator"]
    ]
    assert {"@value": "Bodem", "@language": "nl"} in sources
    assert {"@id": "urn:author"} in sources
    assert {"@value": "Alice"} in sources


@pytest.mark.parametrize("empty", [None, "  ", [], {"name": ""}])
def test_empty_values_and_blank_identifiers_do_not_earn_points(profile, empty):
    request = AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@type": "Dataset",
            "name": empty,
            "creator": empty,
            "publisher": empty,
        }
    )
    prepared = prepare_metadata(select_dataset(request, profile))
    assert prepared.fields == {
        "object_type": ["Dataset"],
        "namespaces": ["http://schema.org/"],
    }
    result = _fuji.Runner(profile.resources).evaluate("FsF-F2-01M", prepared.fields)
    assert result.metric.score.observed_earned == 0


def test_literal_values_keep_zero_false_and_multiple_languages(profile):
    request = AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@type": "Dataset",
            "name": [
                {"@value": "Soil", "@language": "en"},
                {"@value": "Bodem", "@language": "nl"},
            ],
            "keywords": {
                "@list": [
                    False,
                    0,
                    {
                        "@value": "2026",
                        "@type": "http://www.w3.org/2001/XMLSchema#gYear",
                    },
                ]
            },
        }
    )
    selected = select_dataset(request, profile)
    prepared = prepare_metadata(selected)
    assert prepared.fields["title"] == ["Soil", "Bodem"]
    assert prepared.fields["keywords"] == [False, 0, "2026"]
    assert type(prepared.fields["keywords"][0]) is bool
    assert type(prepared.fields["keywords"][1]) is int
    assert len(prepared.sources["keywords"]) == 3
    assert at_pointer(selected.graph, prepared.sources["keywords"][-1]) == {
        "@value": "2026",
        "@type": "http://www.w3.org/2001/XMLSchema#gYear",
    }


def test_links_are_not_fetched_or_followed_outside_the_selected_graph(profile):
    request = AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@id": "urn:data",
                    "@type": "Dataset",
                    "creator": {"@id": "https://example.org/person"},
                    "publisher": {"@id": "_:cycle"},
                },
                {"@id": "_:cycle", "name": {"@id": "_:cycle"}},
                {
                    "@id": "urn:other-graph",
                    "@graph": [
                        {"@id": "https://example.org/person", "name": "Must not use"}
                    ],
                },
            ],
        }
    )
    prepared = prepare_metadata(select_dataset(request, profile))
    assert prepared.fields["creator"] == ["https://example.org/person"]
    assert "publisher" not in prepared.fields


def test_distribution_links_keep_local_sources_and_multiple_downloads(profile):
    request = AssessmentInput(
        metadata={
            "@context": {
                "@vocab": "https://schema.org/",
                "files": "https://schema.org/distribution",
                "download": {"@id": "https://schema.org/contentUrl", "@type": "@id"},
            },
            "@graph": [
                {
                    "@id": "urn:data",
                    "@type": "Dataset",
                    "files": [{"@id": "urn:file"}, {"@id": "_:foreign"}],
                },
                {
                    "@id": "urn:file",
                    "download": [
                        "https://example.org/a.csv",
                        "https://example.org/b.csv",
                    ],
                },
                {"@id": "urn:unrelated", "download": "https://example.org/unrelated"},
                {
                    "@id": "urn:other-graph",
                    "@graph": [
                        {"@id": "_:foreign", "download": "https://example.org/foreign"}
                    ],
                },
            ],
        }
    )
    selected = select_dataset(request, profile)
    original = deepcopy(selected)
    prepared = prepare_metadata(selected)
    assert prepared.fields["object_content_identifier"] == [
        {"url": "https://example.org/a.csv"},
        {"url": "https://example.org/b.csv"},
    ]
    values = [
        at_pointer(selected.graph, path)
        for path in prepared.sources["object_content_identifier"]
    ]
    assert {"@id": "urn:file"} in values
    assert {"@id": "https://example.org/a.csv"} in values
    assert {"@id": "https://example.org/b.csv"} in values
    assert not prepared.unmapped
    assert selected == original


def test_distribution_descriptors_stay_with_their_files_and_sources(profile):
    request = AssessmentInput(
        metadata={
            "@context": {
                "@vocab": "https://schema.org/",
                "bytes": "https://schema.org/contentSize",
            },
            "@graph": [
                {
                    "@id": "urn:data",
                    "@type": "Dataset",
                    "distribution": {"@list": [{"@id": "urn:a"}, {"@id": "urn:b"}]},
                },
                {
                    "@id": "urn:a",
                    "contentUrl": [
                        "https://example.org/a",
                        "https://example.org/mirror",
                    ],
                    "bytes": "100",
                    "encodingFormat": ["text/csv", "application/csv"],
                },
                {"@id": "urn:b", "url": "https://example.org/b", "fileSize": "200"},
                {"@id": "urn:unrelated", "encodingFormat": "text/csv"},
                {
                    "@id": "urn:other-graph",
                    "@graph": [{"@id": "urn:b", "encodingFormat": "text/csv"}],
                },
            ],
        }
    )
    selected = select_dataset(request, profile)
    original = deepcopy(selected)
    prepared = prepare_metadata(selected)
    assert prepared.fields["object_content_identifier"] == [
        {
            "url": "https://example.org/a",
            "type": ["text/csv", "application/csv"],
            "size": "100",
        },
        {
            "url": "https://example.org/mirror",
            "type": ["text/csv", "application/csv"],
            "size": "100",
        },
        {"url": "https://example.org/b", "size": "200"},
    ]
    details = [
        at_pointer(selected.graph, path)
        for path in prepared.sources["distribution_details"]
    ]
    assert {"@value": "100"} in details
    assert {"@value": "200"} in details
    assert {"@value": "text/csv"} in details
    assert {"@value": "application/csv"} in details
    assert all(
        "encodingFormat" not in path and "contentSize" not in path
        for path in prepared.sources["object_content_identifier"]
    )
    assert selected == original


def test_related_resources_keep_relation_types_and_local_graph_sources(profile):
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
                    "basedOn": {
                        "@list": [
                            {"@id": "_:source"},
                            {"@id": "_:foreign"},
                            {"@id": "https://example.org/derived"},
                        ]
                    },
                    "citation": {"@id": "https://example.org/paper"},
                    "sameAs": {"@id": "https://example.org/copy"},
                },
                {"@id": "_:source", "name": {"@value": "Bodem", "@language": "nl"}},
                {"@id": "https://example.org/paper", "name": "Keep the paper ID"},
                {"@id": "urn:unrelated", "citation": "https://example.org/ignored"},
                {
                    "@id": "urn:other-graph",
                    "@graph": [
                        {"@id": "_:foreign", "url": "https://example.org/foreign"}
                    ],
                },
            ],
        }
    )
    selected = select_dataset(request, profile)
    original = deepcopy(selected)
    prepared = prepare_metadata(selected)
    assert {
        (entry["relation_type"], entry["related_resource"])
        for entry in prepared.fields["related_resources"]
    } == {
        ("https://schema.org/isBasedOn", "Bodem"),
        ("https://schema.org/isBasedOn", "https://example.org/derived"),
        ("https://schema.org/citation", "https://example.org/paper"),
        ("https://schema.org/sameAs", "https://example.org/copy"),
    }
    assert prepared.fields["object_identifier"] == [
        "urn:data",
        "https://example.org/copy",
    ]
    values = [
        at_pointer(selected.graph, pointer)
        for pointer in prepared.sources["related_resources"]
    ]
    assert {"@value": "Bodem", "@language": "nl"} in values
    assert {"@id": "https://example.org/paper"} in values
    assert not prepared.unmapped
    assert selected == original
