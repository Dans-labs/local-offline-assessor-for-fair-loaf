from dataclasses import dataclass
from typing import cast

from pydantic import JsonValue

from fair_offline_assessor._metadata import SelectedDataset
from fair_offline_assessor.models import InputError

_SCHEMA = ("http://schema.org/", "https://schema.org/")
_SCHEMA_FIELDS = {
    "name": "title",
    "headline": "title",
    "description": "summary",
    "abstract": "summary",
    "creator": "creator",
    "author": "creator",
    "publisher": "publisher",
    "provider": "publisher",
    "datePublished": "publication_date",
    "dateCreated": "publication_date",
    "keywords": "keywords",
    "identifier": "object_identifier",
    "url": "object_identifier",
    "sameAs": "object_identifier",
    "license": "license",
    "conditionsOfAccess": "access_level",
    "isAccessibleForFree": "access_free",
    "distribution": "object_content_identifier",
}
_DC_FIELDS = {
    "title": "title",
    "description": "summary",
    "creator": "creator",
    "publisher": "publisher",
    "date": "publication_date",
    "subject": "keywords",
    "identifier": "object_identifier",
    "type": "object_type",
    "rights": "access_level",
}
_FIELDS = {
    "@id": "object_identifier",
    "@type": "object_type",
    **{ns + term: field for ns in _SCHEMA for term, field in _SCHEMA_FIELDS.items()},
    **{
        ns + term: field
        for ns in ("http://purl.org/dc/elements/1.1/", "http://purl.org/dc/terms/")
        for term, field in _DC_FIELDS.items()
    },
    "http://purl.org/dc/terms/abstract": "summary",
    "http://purl.org/dc/terms/issued": "publication_date",
    "http://purl.org/dc/terms/license": "license",
    "http://purl.org/dc/terms/accessRights": "access_level",
    "http://www.w3.org/ns/dcat#keyword": "keywords",
}
_NAMES = (*(ns + "name" for ns in _SCHEMA), "http://xmlns.com/foaf/0.1/name")
_DETAILS = {
    "license": tuple(ns + "url" for ns in _SCHEMA),
    "creator": _NAMES,
    "publisher": (
        *_NAMES,
        *(ns + "url" for ns in _SCHEMA),
        "http://xmlns.com/foaf/0.1/homepage",
    ),
    "object_identifier": tuple(ns + "value" for ns in _SCHEMA),
    "object_content_identifier": tuple(
        ns + term for ns in _SCHEMA for term in ("contentUrl", "url")
    ),
}

type GraphIndex = dict[str, tuple[int, dict[str, JsonValue]]]
type SourcedValue = tuple[JsonValue, tuple[str, ...]]


@dataclass(frozen=True)
class FujiMetadata:
    fields: dict[str, JsonValue]
    # JSON pointers into SelectedDataset.graph retain the original literal details.
    sources: dict[str, tuple[str, ...]]
    unmapped: tuple[str, ...]


def _pointer(index: int, term: str) -> str:
    """Locate a property in the selected graph."""
    return f"/{index}/{term.replace('~', '~0').replace('/', '~1')}"


def _values(
    value: JsonValue, location: str, graph: GraphIndex, properties: tuple[str, ...] = ()
) -> list[SourcedValue]:
    """Read literals or identifiers, following supported local properties once."""
    if isinstance(value, dict):
        if "@list" in value:
            return [
                found
                for i, item in enumerate(cast("list[JsonValue]", value["@list"]))
                for found in _values(item, f"{location}/@list/{i}", graph, properties)
            ]
        if "@value" in value:
            value = value["@value"]
        else:
            identifier = value.get("@id")
            if not isinstance(identifier, str):
                return []
            found = _linked_values(identifier, location, graph, properties)
            if found:
                return found
            value = None if identifier.startswith("_:") else identifier
    if value is None or isinstance(value, (dict, list)):
        return []
    if isinstance(value, str) and not value.strip():
        return []
    return [(value, (location,))]


def _linked_values(
    identifier: str, location: str, graph: GraphIndex, properties: tuple[str, ...]
) -> list[SourcedValue]:
    """Read supported properties of a node in the selected graph."""
    if not properties or identifier not in graph:
        return []
    index, node = graph[identifier]
    return [
        (value, (location, *paths))
        for term in properties
        for i, item in enumerate(cast("list[JsonValue]", node.get(term, [])))
        for value, paths in _values(item, f"{_pointer(index, term)}/{i}", graph)
    ]


def prepare_metadata(dataset: SelectedDataset) -> FujiMetadata:
    """Map selected metadata into F-UJI fields, retaining all supplied values."""
    graph = {
        cast("str", node["@id"]): (i, node) for i, node in enumerate(dataset.graph)
    }
    index, node = graph[cast("str", dataset.node["@id"])]
    fields: dict[str, JsonValue] = {}
    sources: dict[str, tuple[str, ...]] = {}
    for term, items in node.items():
        if term not in _FIELDS:
            continue
        field = _FIELDS[term]
        properties = () if term.startswith("@") else _DETAILS.get(field, ())
        location = _pointer(index, term)
        entries = list(enumerate(items)) if isinstance(items, list) else [(None, items)]
        for i, item in entries:
            path = f"{location}/{i}" if i is not None else location
            entry: JsonValue = {"@id": item} if term in ("@id", "@type") else item
            for value, paths in _values(entry, path, graph, properties):
                if field == "object_content_identifier" and not isinstance(value, str):
                    continue
                normalized = (
                    {"url": value} if field == "object_content_identifier" else value
                )
                if field == "object_type" and isinstance(normalized, str):
                    for ns in _SCHEMA:
                        normalized = normalized.removeprefix(ns)
                cast("list[JsonValue]", fields.setdefault(field, [])).append(normalized)
                sources[field] = (*sources.get(field, ()), *paths)
    if "access_free" in fields:
        values = cast("list[JsonValue]", fields["access_free"])
        if any(not isinstance(value, bool) for value in values) or any(
            value != values[0] for value in values
        ):
            raise InputError(
                "invalid_access_free",
                "isAccessibleForFree must contain one unambiguous boolean value",
            )
        fields["access_free"] = values[0]
    return FujiMetadata(
        fields=fields,
        sources=sources,
        unmapped=tuple(
            sorted(
                term
                for term in node
                if not term.startswith("@") and term not in _FIELDS
            )
        ),
    )
