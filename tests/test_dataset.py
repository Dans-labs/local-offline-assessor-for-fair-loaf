import pytest

from fair_offline_assessor import AssessmentInput, InputError, _metadata, load_profile
from fair_offline_assessor._fuji_metadata import select_dataset


@pytest.fixture
def profile():
    return load_profile("fusji-offline@3.5.1")


def test_resource_selection_uses_supplied_types(profile):
    request = AssessmentInput(
        metadata=[
            {"@id": "urn:data", "@type": "https://schema.org/Dataset"},
            {"@id": "urn:other", "@type": "urn:Other"},
        ]
    )
    selected = _metadata.select_resource(
        request, profile, resource_types=("urn:Other",)
    )
    assert selected.node["@id"] == "urn:other"
    assert select_dataset(request, profile).node["@id"] == "urn:data"


@pytest.mark.parametrize(
    "shape", ["single", "graph", "nested", "named_graph", "aliased"]
)
def test_selects_dataset_without_selecting_its_author(profile, shape):
    dataset = {"@id": "urn:data", "@type": "Dataset", "name": "Example"}
    author = {"@id": "urn:author", "@type": "Person", "name": "Author"}
    bodies = {
        "single": {**dataset, "creator": author},
        "graph": {"@graph": [author, dataset]},
        "nested": {"@type": "DataCatalog", "dataset": dataset},
        "named_graph": {"@id": "urn:graph", "@graph": [author, dataset]},
        "aliased": {"@id": "urn:data", "kind": "Dataset", "label": "Example"},
    }
    request = AssessmentInput(
        metadata={
            "@context": ["https://schema.org", {"kind": "@type", "label": "name"}],
            **bodies[shape],
        }
    )
    original = request.model_copy(deep=True)
    selected = select_dataset(request, profile)
    assert selected.node["@id"] == "urn:data"
    assert selected.node["http://schema.org/name"] == [{"@value": "Example"}]
    assert request == original


def test_combines_descriptions_of_the_same_dataset_and_keeps_local_references(profile):
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
                "urn:custom": [{"@value": False}],
            },
            {"@id": "urn:author", "https://schema.org/name": [{"@value": "Author"}]},
        ]
    )
    selected = select_dataset(request, profile)
    assert selected.node == {
        "@id": "urn:data",
        "@type": ["https://schema.org/Dataset"],
        "https://schema.org/creator": [{"@id": "urn:author"}],
        "https://schema.org/name": [{"@value": "Example"}],
        "urn:custom": [{"@value": False}],
    }
    assert next(node for node in selected.graph if node["@id"] == "urn:author") == {
        "@id": "urn:author",
        "https://schema.org/name": [{"@value": "Author"}],
    }


@pytest.mark.parametrize("types", [[], ["Dataset"]])
def test_subject_selects_record_with_or_without_a_dataset_type(profile, types):
    request = AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@graph": [
                {"@id": "first", "@type": "Dataset", "name": "First"},
                {"@id": "second", "@type": types, "name": "Second"},
            ],
        },
        metadata_url="https://example.org/metadata",
        subject="https://example.org/second",
    )
    selected = select_dataset(request, profile)
    assert selected.node["@id"] == request.subject
    assert selected.node["http://schema.org/name"] == [{"@value": "Second"}]


@pytest.mark.parametrize(
    ("nodes", "subject", "code"),
    [
        ([], None, "dataset_not_found"),
        ([{"@type": "Person"}], None, "dataset_not_found"),
        ([{"@type": "urn:Dataset"}], None, "dataset_not_found"),
        ([{"@type": "Dataset"}, {"@type": "Dataset"}], None, "ambiguous_dataset"),
        ([{"@id": "urn:data", "@type": "Dataset"}], "urn:missing", "subject_not_found"),
        ([{"@id": "_:record", "@type": "Dataset"}], "_:b0", "subject_not_found"),
        (
            [{"@type": "Dataset", "creator": {"@id": "urn:author"}}],
            "urn:author",
            "subject_not_found",
        ),
        (
            [
                {"@id": "urn:data", "@index": "one", "@type": "Dataset"},
                {"@id": "urn:data", "@index": "two", "@type": "Dataset"},
            ],
            None,
            "invalid_jsonld",
        ),
    ],
)
def test_missing_or_ambiguous_records_are_input_errors(profile, nodes, subject, code):
    request = AssessmentInput(
        metadata={"@context": "https://schema.org", "@graph": nodes}, subject=subject
    )
    with pytest.raises(InputError) as error:
        select_dataset(request, profile)
    assert error.value.code == code


def test_same_subject_in_different_graphs_is_not_silently_combined(profile):
    request = AssessmentInput(
        metadata={
            "@context": "https://schema.org",
            "@graph": [
                {"@id": "urn:one", "@graph": [{"@id": "urn:data", "name": "One"}]},
                {"@id": "urn:two", "@graph": [{"@id": "urn:data", "name": "Two"}]},
            ],
        },
        subject="urn:data",
    )
    with pytest.raises(InputError) as error:
        select_dataset(request, profile)
    assert error.value.code == "ambiguous_subject"


@pytest.mark.parametrize(
    ("identifier", "subject"), [(None, None), ("_:record", "_:record")]
)
def test_selects_datasets_without_a_public_identifier(profile, identifier, subject):
    metadata = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": "Unpublished",
    }
    if identifier is not None:
        metadata["@id"] = identifier
    request = AssessmentInput(
        metadata=metadata,
        subject=subject,
    )
    selected = select_dataset(request, profile)
    assert selected.node["http://schema.org/name"] == [{"@value": "Unpublished"}]
