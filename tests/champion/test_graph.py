import json
from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256

import pytest
from pyld import jsonld

from fair_offline_assessor import ChampionInput, InputError, load_profile
from fair_offline_assessor.assessors.champion.v0_5_12.graph import prepare_graph


@pytest.fixture
def profile():
    loaded = load_profile("fusji-offline@3.5.1")
    contexts = tuple(r for r in loaded.references if r.kind == "context")
    return replace(
        loaded,
        references=contexts,
        resources={r.id: loaded.resources[r.id] for r in contexts},
    )


def graph(metadata, profile, **options):
    return prepare_graph(ChampionInput(metadata=metadata, **options), profile)


def node(subject, value="value"):
    return {"@id": subject, "urn:p": {"@value": value}}


def test_graph_accepts_non_dataset_nodes_and_preserves_rdf_term_kinds(profile):
    document = {
        "@id": "urn:record",
        "@type": "urn:Record",
        "urn:p": [
            {"@id": "https://example.org/iri"},
            {"@value": "https://example.org/literal"},
            {"@value": "Titel", "@language": "nl"},
            {"@value": "7", "@type": "http://www.w3.org/2001/XMLSchema#integer"},
            {"@id": "_:child", "urn:name": "Child"},
        ],
    }
    before = deepcopy(document)
    prepared = graph(document, profile)
    objects = {s.object.value: s.object for s in prepared.statements}
    assert objects["https://example.org/iri"].kind == "iri"
    assert objects["https://example.org/literal"].kind == "literal"
    assert (
        objects["https://example.org/literal"].datatype
        == "http://www.w3.org/2001/XMLSchema#string"
    )
    assert objects["Titel"].language == "nl"
    assert objects["7"].datatype == "http://www.w3.org/2001/XMLSchema#integer"
    assert any(s.object.kind == "blank" for s in prepared.statements)
    assert any(s.subject.kind == "blank" for s in prepared.statements)
    assert objects["urn:Record"].kind == "iri"
    assert document == before


def test_empty_graph_is_valid_evidence(profile):
    result = graph([], profile)
    assert result.statements == ()
    assert result.evidence == ()
    assert result.digest == sha256(b"[]").hexdigest()


def test_sole_nonempty_named_graph_can_be_used(profile):
    document = [
        {"@id": "urn:named", "@graph": [node("urn:chosen")]},
        {"@id": "urn:empty", "@graph": []},
    ]
    result = graph(document, profile)
    assert [s.subject.value for s in result.statements] == ["urn:chosen"]


def test_multiple_nonempty_graphs_need_explicit_selection(profile):
    document = [node("urn:default"), {"@id": "urn:g", "@graph": [node("urn:other")]}]
    with pytest.raises(InputError) as error:
        graph(document, profile)
    assert error.value.code == "ambiguous_graph"
    assert error.value.location == "/metadata"


def test_subject_selects_its_entire_graph_without_merging_nested_graphs(profile):
    document = [
        node("urn:default"),
        {
            "@id": "urn:g",
            "@graph": [
                node("urn:selected"),
                node("urn:unrelated"),
                {"@id": "urn:nested", "@graph": [node("urn:elsewhere")]},
            ],
        },
    ]
    result = graph(document, profile, subject="urn:selected")
    assert {s.subject.value for s in result.statements} == {
        "urn:selected",
        "urn:unrelated",
    }
    nested = graph(document, profile, subject="urn:elsewhere")
    assert {s.subject.value for s in nested.statements} == {"urn:elsewhere"}


@pytest.mark.parametrize("subject", ["urn:object-only", "_:missing"])
def test_missing_subject_is_not_replaced_with_another_node(profile, subject):
    document = {"@id": "urn:present", "urn:p": {"@id": "urn:object-only"}}
    with pytest.raises(InputError) as error:
        graph(document, profile, subject=subject)
    assert error.value.code == "subject_not_found"
    assert error.value.location == "/subject"


def test_same_subject_in_two_graphs_is_ambiguous(profile):
    document = [
        {"@id": name, "@graph": [node("urn:repeated")]} for name in ["urn:a", "urn:b"]
    ]
    with pytest.raises(InputError) as error:
        graph(document, profile, subject="urn:repeated")
    assert error.value.code == "ambiguous_subject"


def test_explicit_blank_node_subject_survives_pyld_relabelling(profile):
    document = [{"@id": "_:graph", "@graph": [node("_:chosen")]}, node("urn:outside")]
    result = graph(document, profile, subject="_:chosen")
    assert len(result.statements) == 1
    assert result.statements[0].subject.kind == "blank"
    assert result.statements[0].object.value == "value"


def test_relative_ids_use_metadata_origin_not_the_assessment_target(profile):
    result = graph(
        {"@id": "item", "urn:p": {"@id": "file"}},
        profile,
        target_identifier="https://target.example/id",
        metadata_url="https://source.example/path/record.jsonld",
    )
    assert result.statements[0].subject.value == "https://source.example/path/item"
    assert result.statements[0].object.value == "https://source.example/path/file"


def test_duplicate_statements_are_removed_and_value_order_is_retained(profile):
    document = {
        "@id": "urn:s",
        "urn:p": [{"@value": "second"}, {"@value": "first"}, {"@value": "second"}],
    }
    result = graph([document, deepcopy(document)], profile, subject="urn:s")
    assert [s.object.value for s in result.statements] == ["second", "first"]
    assert graph([document, deepcopy(document)], profile, subject="urn:s") == result


def test_evidence_locations_and_digest_describe_prepared_statements(profile):
    result = graph([node("urn:a"), node("urn:b")], profile)
    expected_digest = sha256(
        json.dumps(
            [asdict(s) for s in result.statements],
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assert result.digest == expected_digest
    assert [(e.resource, e.digest, e.location, e.subject) for e in result.evidence] == [
        ("prepared_metadata", expected_digest, "/0", "urn:a"),
        ("prepared_metadata", expected_digest, "/1", "urn:b"),
    ]
    assert graph(node("urn:s"), profile).digest != result.digest


@pytest.mark.parametrize(
    ("document", "code"),
    [
        ("https://example.org/metadata", "invalid_json"),
        ("null", "unsupported_input"),
        ('{"urn:p": NaN}', "invalid_json"),
        ({"@context": 42}, "invalid_jsonld"),
    ],
)
def test_unusable_metadata_is_not_treated_as_an_empty_graph(profile, document, code):
    with pytest.raises(InputError) as error:
        graph(document, profile)
    assert error.value.code == code


def test_json_text_is_parsed_locally_and_other_formats_are_rejected(profile):
    document = json.dumps(node("urn:s"))
    assert graph(document, profile) == graph(node("urn:s"), profile)
    with pytest.raises(InputError) as error:
        graph(document, profile, metadata_format="xml")
    assert error.value.code == "unsupported_metadata_format"
    assert error.value.location == "/metadata_format"


def test_contexts_remain_local_and_isolated_between_assessments(profile, monkeypatch):
    def forbidden_loader(*_args):
        pytest.fail("The default network loader must never be used")

    monkeypatch.setattr(jsonld, "_default_document_loader", forbidden_loader)
    url = "https://example.org/context"
    document = {"@context": url, "@id": "urn:s", "title": "Title"}
    for predicate in ("urn:first", "urn:second"):
        result = graph(
            document, profile, local_contexts={url: {"@context": {"title": predicate}}}
        )
        assert [s.predicate for s in result.statements] == [predicate]
    with pytest.raises(InputError) as error:
        graph(document, profile)
    assert error.value.code == "unknown_context"
    assert jsonld.get_document_loader() is forbidden_loader
