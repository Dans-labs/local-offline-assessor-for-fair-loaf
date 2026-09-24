import pytest

from fair_offline_assessor import ChampionInput
from fair_offline_assessor.assessors.champion.v0_5_12.graph import prepare_graph
from fair_offline_assessor.assessors.champion.v0_5_12.identifiers import (
    classify_identifier,
    data_identifier,
    self_identifiers,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("prefix\n10x1234/abc\nsuffix", "doi"),  # Ruby line anchors and unescaped dot.
        ("https://doi.org/10.1234/abc", "uri"),
        ("12345/abc", "handle1"),  # First matching pattern wins.
        ("see ark:/12345/abc here", "ark"),
        ("éBCDEFGHIJKLMN-ABCDEFGHIJ-A", None),  # Ruby \w is ASCII.
        ("éark:/12345/abc", None),  # Ruby \b still treats Unicode letters as words.
    ],
)
def test_classifier_matches_pinned_ruby_rules(definitions, value, expected):
    assert classify_identifier(value, definitions) == expected


def test_self_identifiers_use_predicate_order_and_root_property_values(
    champion_profile, definitions
):
    request = ChampionInput(
        metadata={
            "@context": {"s": "http://schema.org/", "dc": "http://purl.org/dc/terms/"},
            "@id": "urn:root",
            "dc:identifier": ["first", {"@id": "urn:second"}, {"@id": "_:ignored"}],
            "s:identifier": {"@type": "s:PropertyValue", "s:value": "root-id"},
            "s:mainEntity": {
                "s:identifier": {"@type": "s:PropertyValue", "s:value": "nested-id"}
            },
        }
    )
    result = self_identifiers(prepare_graph(request, champion_profile), definitions)
    # The root PropertyValue query is repeated for both schema identifier predicates.
    assert result == ("first", "urn:second", "root-id", "root-id")


def test_nonroot_property_value_does_not_hide_direct_schema_identifiers(
    champion_profile, definitions
):
    request = ChampionInput(
        metadata={
            "http://schema.org/identifier": "direct",
            "urn:child": {
                "http://schema.org/identifier": {
                    "@type": "http://schema.org/PropertyValue",
                    "http://schema.org/value": "nested",
                }
            },
        }
    )
    assert self_identifiers(prepare_graph(request, champion_profile), definitions) == (
        "direct",
    )


def test_data_identifier_skips_blank_first_candidate_then_uses_predicate_order(
    champion_profile, definitions
):
    request = ChampionInput(
        metadata={
            "http://www.w3.org/ns/ldp#contains": [
                {"@id": "_:first"},
                "ignored-later-value",
            ],
            "http://schema.org/contentUrl": "later-predicate",
            "http://schema.org/mainEntity": {"https://schema.org/identifier": "chosen"},
        }
    )
    assert (
        data_identifier(prepare_graph(request, champion_profile), definitions)
        == "chosen"
    )


def test_distribution_and_dcat_queries_keep_unbound_variables(
    champion_profile, definitions
):
    request = ChampionInput(
        metadata={
            "http://schema.org/distribution": {
                "@id": "https://example.org/distribution"
            },
            "http://www.w3.org/ns/dcat#downloadURL": {
                "@id": "https://example.org/file"
            },
        }
    )
    assert (
        data_identifier(prepare_graph(request, champion_profile), definitions) is None
    )
