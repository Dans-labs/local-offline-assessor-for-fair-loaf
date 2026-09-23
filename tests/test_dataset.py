import pytest

from fair_offline_assessor import AssessmentInput, InputError, load_profile
from fair_offline_assessor._fuji_readers import prepare_metadata


@pytest.fixture(scope="module")
def profile():
    return load_profile("fusji-offline@3.5.1")


@pytest.mark.parametrize(
    "shape", ["single", "graph", "nested", "named_graph", "aliased"]
)
def test_native_main_entity_selects_the_more_described_dataset(profile, shape):
    dataset = {
        "@id": "urn:data",
        "@type": "Dataset",
        "name": "Example",
        "description": "Dataset description",
    }
    author = {"@id": "urn:author", "@type": "Person", "name": "Author"}
    bodies = {
        "single": {**dataset, "creator": author},
        "graph": {"@graph": [author, dataset]},
        "nested": {"@type": "DataCatalog", "dataset": dataset},
        "named_graph": {"@id": "urn:graph", "@graph": [author, dataset]},
        "aliased": {
            "@id": "urn:data",
            "kind": "Dataset",
            "label": "Example",
            "description": "Dataset description",
        },
    }
    request = AssessmentInput(
        metadata={
            "@context": ["https://schema.org", {"kind": "@type", "label": "name"}],
            **bodies[shape],
        },
        subject="urn:data",
    )
    original = request.model_copy(deep=True)

    fields = prepare_metadata(request, profile).fields

    assert fields["title"] == "Example"
    assert fields["summary"] == "Dataset description"
    assert fields["object_type"] == ["Dataset"]
    assert request == original


def test_native_schema_selection_is_not_restricted_to_datasets(profile):
    request = AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@graph": [
                {"@id": "urn:data", "@type": "Dataset", "name": "Sparse dataset"},
                {
                    "@id": "urn:article",
                    "@type": "ScholarlyArticle",
                    "name": "Main article",
                    "description": "More descriptive properties",
                    "license": "MIT",
                },
            ],
        },
        subject="urn:article",
    )

    fields = prepare_metadata(request, profile).fields

    assert fields["title"] == "Main article"
    assert fields["object_type"] == ["ScholarlyArticle"]


def test_native_reader_combines_same_subject_statements_and_local_references(profile):
    request = AssessmentInput(
        metadata=[
            {
                "@id": "urn:data",
                "@type": ["https://schema.org/Dataset"],
                "https://schema.org/creator": [{"@id": "urn:author"}],
            },
            {
                "@id": "urn:data",
                "https://schema.org/name": [{"@value": "Example"}],
                "https://schema.org/identifier": [{"@value": "urn:published-id"}],
            },
            {"@id": "urn:author", "https://schema.org/name": [{"@value": "Author"}]},
        ],
        subject="urn:data",
    )
    original = request.model_copy(deep=True)

    fields = prepare_metadata(request, profile).fields

    assert fields["title"] == "Example"
    assert fields["creator"] == ["Author"]
    assert fields["object_identifier"] == ["urn:published-id"]
    assert request == original


@pytest.mark.parametrize("types", [[], ["Dataset"]])
def test_explicit_subject_cannot_override_native_main_entity_selection(profile, types):
    request = AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@id": "first",
                    "@type": "Dataset",
                    "name": "First",
                    "description": "Native main entity",
                },
                {"@id": "second", "@type": types, "name": "Second"},
            ],
        },
        metadata_url="https://example.org/metadata",
        subject="https://example.org/second",
    )

    with pytest.raises(InputError) as error:
        prepare_metadata(request, profile)

    assert error.value.code == "subject_not_selected"
    assert error.value.location == "/subject"
    selected = prepare_metadata(
        request.model_copy(update={"subject": "https://example.org/first"}), profile
    )
    assert selected.fields["title"] == "First"


def test_multiple_datasets_follow_native_main_entity_scoring(profile):
    request = AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@graph": [
                {"@id": "urn:sparse", "@type": "Dataset", "name": "Sparse"},
                {
                    "@id": "urn:rich",
                    "@type": "Dataset",
                    "name": "Rich",
                    "description": "Native selection uses the more described record",
                    "license": "MIT",
                },
            ],
        }
    )

    assert prepare_metadata(request, profile).fields["title"] == "Rich"
    checked = request.model_copy(update={"subject": "urn:rich"})
    assert prepare_metadata(checked, profile).fields["title"] == "Rich"


def test_dcat_selects_its_dataset_even_when_another_type_has_more_properties(profile):
    request = AssessmentInput(
        metadata={
            "@context": {
                "dcat": "http://www.w3.org/ns/dcat#",
                "dct": "http://purl.org/dc/terms/",
            },
            "@graph": [
                {"@id": "urn:data", "@type": "dcat:Dataset", "dct:title": "Dataset"},
                {
                    "@id": "urn:catalogue",
                    "@type": "dcat:Catalog",
                    "dct:title": "Catalogue",
                    "dct:description": "More descriptive properties",
                    "dct:publisher": "Archive",
                    "dcat:dataset": {"@id": "urn:data"},
                },
            ],
        },
        subject="urn:data",
    )

    fields = prepare_metadata(request, profile).fields

    assert fields["title"] == "Dataset"
    assert fields["object_type"] == ["Dataset"]


def test_dublin_core_dataset_uses_the_native_generic_rdf_query(profile):
    request = AssessmentInput(
        metadata={
            "@id": "urn:data",
            "@type": "http://purl.org/dc/dcmitype/Dataset",
            "http://purl.org/dc/terms/title": "Soil",
            "http://purl.org/dc/terms/identifier": "urn:published-id",
        }
    )

    fields = prepare_metadata(request, profile).fields

    assert fields["title"] == "Soil"
    assert fields["object_type"] == ["http://purl.org/dc/dcmitype/Dataset"]
    assert fields["object_identifier"] == "urn:published-id"


@pytest.mark.parametrize("subject", ["urn:dcat", "urn:schema"])
def test_explicit_subject_rejects_native_readers_selecting_different_roots(
    profile, subject
):
    request = AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@id": "urn:dcat",
                    "@type": "http://www.w3.org/ns/dcat#Dataset",
                    "http://purl.org/dc/terms/title": "DCAT title",
                },
                {
                    "@id": "urn:schema",
                    "@type": "ScholarlyArticle",
                    "name": "Schema title",
                    "description": "More descriptive properties",
                    "license": "MIT",
                },
            ],
        },
        subject=subject,
    )

    with pytest.raises(InputError) as error:
        prepare_metadata(request, profile)

    assert error.value.code == "subject_not_selected"
    default = prepare_metadata(request.model_copy(update={"subject": None}), profile)
    assert default.fields["title"] == "Schema title"


def test_named_graphs_are_a_union_for_native_rdf_selection(profile):
    request = AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@id": "urn:one",
                    "@graph": [
                        {"@id": "urn:data", "@type": "Dataset", "name": "Title"}
                    ],
                },
                {
                    "@id": "urn:two",
                    "@graph": [{"@id": "urn:data", "description": "Description"}],
                },
            ],
        },
        subject="urn:data",
    )

    fields = prepare_metadata(request, profile).fields

    assert fields["title"] == "Title"
    assert fields["summary"] == "Description"


@pytest.mark.parametrize("identifier", [None, "_:record"])
def test_native_dataset_without_identifier_does_not_invent_one(profile, identifier):
    metadata = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": "Unpublished",
    }
    if identifier is not None:
        metadata["@id"] = identifier
    request = AssessmentInput(metadata=metadata)

    fields = prepare_metadata(request, profile).fields

    assert fields["title"] == "Unpublished"
    assert "object_identifier" not in fields
    assert prepare_metadata(request, profile).fields == fields


def test_empty_rdf_document_has_no_native_metadata(profile):
    request = AssessmentInput(metadata={"@context": "https://schema.org", "@graph": []})

    with pytest.raises(InputError) as error:
        prepare_metadata(request, profile)

    assert error.value.code == "metadata_not_found"
