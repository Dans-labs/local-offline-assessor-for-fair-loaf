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
    assert prepared.fields == {"object_type": ["Dataset"]}
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
