import re
import unicodedata
from typing import cast

from fair_offline_assessor.assessors.champion.v0_5_12.definitions import (
    ChampionDefinitions,
)
from fair_offline_assessor.assessors.champion.v0_5_12.graph import (
    ChampionGraph,
    RdfTerm,
)

SCHEMA = ("http://schema.org/", "https://schema.org/")
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


def matches_ruby_pattern(pattern: str, value: str) -> bool:
    """Match the pinned /.../ and %r{...} patterns, with Ruby line anchors."""
    if pattern.startswith("%r{"):
        body, _, modifiers = pattern[3:].rpartition("}")
    else:
        body, _, modifiers = pattern[1:].rpartition("/")
    flags = re.ASCII | re.MULTILINE
    if "i" in modifiers:
        flags |= re.IGNORECASE
    if "x" in modifiers:
        flags |= re.VERBOSE
    # Only the pinned ARK pattern uses \b, immediately before "ark". Ruby's
    # boundary uses Unicode Letter/Mark/Number/Connector_Punctuation even
    # though its shorthand classes are ASCII. Check that boundary separately.
    boundary = r"\b" in body
    for match in re.finditer(body.replace(r"\b", ""), value, flags):
        if boundary and match.start():
            category = unicodedata.category(value[match.start() - 1])
            if category[0] in "LMN" or category == "Pc":
                continue
        return True
    return False


def classify_identifier(value: str, definitions: ChampionDefinitions) -> str | None:
    """Return the first matching type, preserving the harvester's precedence."""
    for pattern in cast(
        "list[dict[str, str]]", definitions.references["identifier_patterns"]
    ):
        if matches_ruby_pattern(pattern["ruby"], value):
            return pattern["type"]
    return None


def _objects(
    graph: ChampionGraph, predicate: str, subject: RdfTerm | None = None
) -> list[RdfTerm]:
    return [
        s.object
        for s in graph.statements
        if s.predicate == predicate and (subject is None or s.subject == subject)
    ]


def _property_values(graph: ChampionGraph) -> list[RdfTerm]:
    values: list[RdfTerm] = []
    for link in graph.statements:
        if link.predicate not in {prefix + "identifier" for prefix in SCHEMA}:
            continue
        if any(s.object == link.subject for s in graph.statements):
            continue  # FILTER NOT EXISTS: only identifiers attached to a root.
        for type_ in _objects(graph, RDF_TYPE, link.object):
            if type_.kind == "iri" and type_.value in {
                prefix + "PropertyValue" for prefix in SCHEMA
            }:
                values.extend(
                    s.object
                    for s in graph.statements
                    if s.subject == link.object
                    and s.predicate in {prefix + "value" for prefix in SCHEMA}
                )
    return values


def self_identifiers(
    graph: ChampionGraph, definitions: ChampionDefinitions
) -> tuple[str, ...]:
    """Port GetSelfIdentifier, including root-only PropertyValue precedence."""
    properties = _property_values(graph)
    result: list[str] = []
    for predicate in cast(
        "list[str]", definitions.references["self_identifier_predicates"]
    ):
        candidates = (
            properties
            if "schema.org/identifier" in predicate and properties
            else _objects(graph, predicate)
        )
        result.extend(term.value for term in candidates if term.kind != "blank")
    return tuple(result)


def data_identifier(
    graph: ChampionGraph, definitions: ChampionDefinitions
) -> str | None:
    """Port GetDataIdentifier without repairing upstream unbound query variables."""
    for predicate in cast("list[str]", definitions.references["data_predicates"]):
        if "schema.org/distribution" in predicate or "dcat#" in predicate:
            continue  # The selected/query variables leave the inspected value unbound.
        candidates = _objects(graph, predicate)
        if "mainEntity" in predicate:
            candidates = [
                s.object
                for entity in candidates
                for s in graph.statements
                if s.subject == entity
                and s.predicate in {prefix + "identifier" for prefix in SCHEMA}
            ]
        # A blank first result skips this predicate, not just that result.
        if candidates and candidates[0].kind != "blank":
            return candidates[0].value
    return None


def doi_equivalent_forms(value: str, definitions: ChampionDefinitions) -> set[str]:
    """Keep the F3 check's DOI forms separate from identifier classification."""
    doi = next(
        p["ruby"]
        for p in cast(
            "list[dict[str, str]]", definitions.references["identifier_patterns"]
        )
        if p["type"] == "doi"
    )
    if matches_ruby_pattern(doi, value):
        bare = value
    else:
        match = re.fullmatch(
            r"https?://(?:dx\.)?doi\.org/(10\.\d{4,9}/[-._;()/:A-Z0-9]+)",
            value,
            re.ASCII | re.IGNORECASE,
        )
        if match is None:
            return {value}
        bare = match[1]
    return {
        value,
        bare,
        *(
            f"{scheme}://{host}/{bare}"
            for scheme in ("https", "http")
            for host in ("doi.org", "dx.doi.org")
        ),
    }
