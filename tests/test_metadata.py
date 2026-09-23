from copy import deepcopy
from dataclasses import replace

import pytest
from pyld import FrozenDocumentLoader, jsonld

from fair_offline_assessor import (
    AssessmentInput,
    InputError,
    ProfileError,
    load_profile,
)
from fair_offline_assessor._metadata import expand_metadata


@pytest.fixture
def profile():
    return load_profile("fusji-offline@3.5.1")


def test_bundled_context_aliases_expand_without_network(profile):
    for alias in (
        "http://schema.org",
        "http://schema.org/",
        "https://schema.org",
        "https://schema.org/",
        "https://schema.org/version/30.0/schemaorgcontext.jsonld",
    ):
        request = AssessmentInput(
            metadata={
                "@context": alias,
                "@type": "Dataset",
                "name": "Example",
                "isAccessibleForFree": False,
            }
        )
        assert expand_metadata(request, profile) == [
            {
                "@type": ["http://schema.org/Dataset"],
                "http://schema.org/name": [{"@value": "Example"}],
                "http://schema.org/isAccessibleForFree": [{"@value": False}],
            }
        ]
    with pytest.raises(InputError) as error:
        expand_metadata(request, replace(profile, references=()))
    assert error.value.code == "unknown_context"


@pytest.mark.parametrize(
    "context", ["terms", {"@import": "https://example.org/contexts/terms"}]
)
def test_nested_contexts_preserve_inputs_and_resolve_relative_ids(profile, context):
    request = AssessmentInput(
        metadata={
            "@context": "https://example.org/contexts/main",
            "@id": "dataset",
            "label": "Example",
        },
        metadata_url="https://example.org/metadata.jsonld",
        local_contexts={
            "https://example.org/contexts/main": {"@context": context},
            "https://example.org/contexts/terms": {
                "@context": {"label": "http://purl.org/dc/terms/title"}
            },
        },
    )
    original = request.model_copy(deep=True)
    assert expand_metadata(request, profile) == [
        {
            "@id": "https://example.org/dataset",
            "http://purl.org/dc/terms/title": [{"@value": "Example"}],
        }
    ]
    assert request == original


@pytest.mark.parametrize(
    "context",
    [
        "https://missing.invalid/context",
        {"@import": "https://missing.invalid/context"},
        {
            "nested": {
                "@id": "urn:nested",
                "@context": "https://missing.invalid/context",
            }
        },
        "file:///missing-context.jsonld",
    ],
)
def test_unknown_contexts_never_use_the_default_loader(profile, monkeypatch, context):
    attempts = []

    def network_loader(url, _options):
        attempts.append(url)
        raise AssertionError("Default document loader called")

    monkeypatch.setattr(jsonld, "_default_document_loader", network_loader)
    request = AssessmentInput(
        metadata={"@context": context, "nested": {"@id": "urn:data"}}
    )
    with pytest.raises(InputError) as error:
        expand_metadata(request, profile)
    assert error.value.code == "unknown_context"
    assert "missing" in str(error.value)
    assert attempts == []
    assert jsonld.get_document_loader() is network_loader


def test_conflicting_caller_context_cannot_replace_a_pinned_context(profile):
    request = AssessmentInput(
        metadata={"@context": "https://schema.org", "name": "Example"},
        local_contexts={"https://schema.org": {"@context": {"name": "urn:wrong"}}},
    )
    with pytest.raises(InputError) as error:
        expand_metadata(request, profile)
    assert error.value.code == "context_conflict"


def test_conflicting_bundled_aliases_are_profile_errors(profile):
    reference = next(r for r in profile.references if r.kind == "context")
    conflicting = replace(
        profile,
        references=(*profile.references, reference.model_copy(update={"id": "other"})),
        resources={
            **profile.resources,
            "other": b'{"@context": {"name": "urn:wrong"}}',
        },
    )
    with pytest.raises(ProfileError) as error:
        expand_metadata(AssessmentInput(metadata={}), conflicting)
    assert error.value.code == "context_conflict"


@pytest.mark.parametrize(
    "document",
    [
        {"@context": 42},
        {"name": "urn:name"},
        {"@context": "https://example.org/context"},
    ],
)
def test_invalid_and_recursive_contexts_are_input_errors(profile, document):
    request = AssessmentInput(
        metadata={"@context": "https://example.org/context", "name": "Example"},
        local_contexts={"https://example.org/context": document},
    )
    with pytest.raises(InputError) as error:
        expand_metadata(request, profile)
    assert error.value.code in {"invalid_context", "invalid_jsonld"}


def test_contexts_do_not_leak_between_calls_or_from_pyld_cache(profile, monkeypatch):
    url = "https://example.org/context"
    metadata = {"@context": url, "name": "Example"}
    frozen = FrozenDocumentLoader(documents={url: {"@context": {"name": "urn:cached"}}})

    def cached_loader(url, options):
        return {**frozen(url, options), "tag": "static"}

    monkeypatch.setattr(jsonld, "_resolved_context_cache", {})
    jsonld.expand(metadata, options={"documentLoader": cached_loader})
    for term in ("urn:first", "urn:second"):
        request = AssessmentInput(
            metadata=deepcopy(metadata),
            local_contexts={url: {"@context": {"name": term}}},
        )
        assert expand_metadata(request, profile) == [{term: [{"@value": "Example"}]}]
    with pytest.raises(InputError) as error:
        expand_metadata(AssessmentInput(metadata=metadata), profile)
    assert error.value.code == "unknown_context"
