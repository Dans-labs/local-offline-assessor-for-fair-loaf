from collections.abc import Iterator
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import cast

from pydantic import JsonValue

from fair_offline_assessor._metadata import SelectedDataset
from fair_offline_assessor.models import Diagnostic, InputError

_SCHEMA = ("http://schema.org/", "https://schema.org/")
_PROVENANCE = ("http://www.w3.org/ns/prov#", "http://purl.org/pav/")
_DISTRIBUTIONS = tuple(ns + "distribution" for ns in _SCHEMA)
_SCHEMA_FIELDS = {
    "name": "title",
    "headline": "title",
    "description": "summary",
    "abstract": "summary",
    "creator": "creator",
    "author": "creator",
    "contributor": "contributor",
    "copyrightHolder": "right_holder",
    "publisher": "publisher",
    "provider": "publisher",
    "datePublished": "publication_date",
    "dateCreated": "publication_date",
    "dateModified": "modified_date",
    "keywords": "keywords",
    "identifier": "object_identifier",
    "url": "object_identifier",
    "sameAs": "object_identifier",
    "license": "license",
    "conditionsOfAccess": "access_level",
    "isAccessibleForFree": "access_free",
    "size": "object_size",
    "contentSize": "object_size",
    "encodingFormat": "object_format",
    "fileFormat": "object_format",
    "variableMeasured": "measured_variable",
}
_DC_FIELDS = {
    "title": "title",
    "description": "summary",
    "creator": "creator",
    "contributor": "contributor",
    "publisher": "publisher",
    "date": "publication_date",
    "subject": "keywords",
    "identifier": "object_identifier",
    "type": "object_type",
    "rights": "access_level",
    "format": "object_format",
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
    "http://purl.org/dc/terms/created": "created_date",
    "http://purl.org/dc/terms/modified": "modified_date",
    "http://purl.org/dc/terms/dateAccepted": "accepted_date",
    "http://purl.org/dc/terms/dateSubmitted": "submitted_date",
    "http://purl.org/dc/terms/rightsHolder": "right_holder",
    "http://purl.org/dc/terms/license": "license",
    "http://purl.org/dc/terms/accessRights": "access_level",
    "http://purl.org/dc/terms/extent": "object_size",
    "http://www.w3.org/ns/dcat#keyword": "keywords",
}
_NAMES = (*(ns + "name" for ns in _SCHEMA), "http://xmlns.com/foaf/0.1/name")
_RELATIONS = {
    ns + term
    for ns in _SCHEMA
    for term in (
        "isPartOf",
        "includedInDataCatalog",
        "subjectOf",
        "isBasedOn",
        "sameAs",
        "citation",
    )
} | {
    "http://purl.org/dc/terms/" + term
    for term in (
        "references",
        "source",
        "isVersionOf",
        "isReferencedBy",
        "isPartOf",
        "hasVersion",
        "replaces",
        "hasPart",
        "isReplacedBy",
        "requires",
        "isRequiredBy",
    )
}
_DETAILS = {
    "license": tuple(ns + "url" for ns in _SCHEMA),
    "creator": _NAMES,
    "contributor": _NAMES,
    "right_holder": _NAMES,
    "measured_variable": _NAMES,
    "object_size": tuple(ns + "value" for ns in _SCHEMA),
    "publisher": (
        *_NAMES,
        *(ns + "url" for ns in _SCHEMA),
        "http://xmlns.com/foaf/0.1/homepage",
    ),
    "object_identifier": tuple(ns + "value" for ns in _SCHEMA),
    "object_content_identifier": tuple(
        ns + term for ns in _SCHEMA for term in ("contentUrl", "url")
    ),
    "type": tuple(
        ns + term for ns in _SCHEMA for term in ("encodingFormat", "fileFormat")
    ),
    "size": tuple(ns + term for ns in _SCHEMA for term in ("contentSize", "fileSize")),
    "related_resources": (
        *(ns + term for ns in _SCHEMA for term in ("url", "identifier")),
        *_NAMES,
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
    invalid: dict[str, Diagnostic] = dataclass_field(default_factory=dict)


def _pointer(index: int, term: str) -> str:
    """Locate a property in the selected graph."""
    return f"/{index}/{term.replace('~', '~0').replace('/', '~1')}"


def _values(
    value: JsonValue,
    location: str,
    graph: GraphIndex,
    properties: tuple[str, ...] = (),
    *,
    prefer_id: bool = False,
) -> list[SourcedValue]:
    """Read literals or identifiers, following supported local properties once."""
    if isinstance(value, dict):
        if "@list" in value:
            return [
                found
                for i, item in enumerate(cast("list[JsonValue]", value["@list"]))
                for found in _values(
                    item,
                    f"{location}/@list/{i}",
                    graph,
                    properties,
                    prefer_id=prefer_id,
                )
            ]
        if "@value" in value:
            value = value["@value"]
        else:
            identifier = value.get("@id")
            if not isinstance(identifier, str):
                return []
            if prefer_id and not identifier.startswith("_:"):
                properties = ()
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


def _related_resources(
    node: dict[str, JsonValue], index: int, graph: GraphIndex
) -> list[SourcedValue]:
    """Keep typed references, using local details only for anonymous resources."""
    related: list[SourcedValue] = []
    for term, items in node.items():
        if term not in _RELATIONS:
            continue
        for i, item in enumerate(cast("list[JsonValue]", items)):
            location = f"{_pointer(index, term)}/{i}"
            values = _values(
                item, location, graph, _DETAILS["related_resources"], prefer_id=True
            )
            related.extend(
                ({"related_resource": value, "relation_type": term}, paths)
                for value, paths in values
                if isinstance(value, str)
            )
    return related


def _distribution_details(
    identifier: str, location: str, graph: GraphIndex
) -> tuple[dict[str, JsonValue], dict[str, tuple[str, ...]]]:
    """Read each distribution's declarations without combining different files."""
    fields: dict[str, JsonValue] = {}
    sources: dict[str, tuple[str, ...]] = {}
    for field in ("type", "size"):
        entries = _linked_values(identifier, location, graph, _DETAILS[field])
        values = [value for value, _ in entries]
        if values:
            fields[field] = values[0] if len(values) == 1 else values
            sources[field] = tuple(path for _, paths in entries for path in paths)
    return fields, sources


def _distributions(
    node: dict[str, JsonValue], index: int, graph: GraphIndex
) -> tuple[dict[str, list[SourcedValue]], tuple[str, ...]]:
    """Pair download links with their declarations, keeping their sources separate."""
    pending = [
        (node[term], _pointer(index, term)) for term in _DISTRIBUTIONS if term in node
    ]
    pending.reverse()
    found: list[SourcedValue] = []
    formats: list[SourcedValue] = []
    sources: list[str] = []
    while pending:
        value, location = pending.pop()
        if isinstance(value, list):
            pending.extend(
                (item, f"{location}/{i}")
                for i, item in reversed(list(enumerate(value)))
            )
            continue
        if isinstance(value, dict) and "@list" in value:
            pending.append((value["@list"], location + "/@list"))
            continue
        urls = [
            (url, paths)
            for url, paths in _values(
                value, location, graph, _DETAILS["object_content_identifier"]
            )
            if isinstance(url, str)
        ]
        details: dict[str, JsonValue] = {}
        detail_sources: dict[str, tuple[str, ...]] = {}
        identifier = value.get("@id") if isinstance(value, dict) else None
        if urls and isinstance(identifier, str):
            details, detail_sources = _distribution_details(identifier, location, graph)
            sources.extend(path for paths in detail_sources.values() for path in paths)
        found.extend(({"url": url, **details}, paths) for url, paths in urls)
        types = details.get("type", [])
        formats.extend(
            ({"url": url, "type": mime}, (*paths, *detail_sources.get("type", ())))
            for url, paths in urls
            for mime in (types if isinstance(types, list) else [types])
            if isinstance(mime, str) and mime.strip()
        )
    return {"object_content_identifier": found, "file_formats": formats}, tuple(sources)


def _access_free(values: list[JsonValue]) -> bool:
    """Require one unambiguous boolean value for isAccessibleForFree."""
    if any(not isinstance(value, bool) for value in values) or any(
        value != values[0] for value in values
    ):
        raise InputError(
            "invalid_access_free",
            "isAccessibleForFree must contain one unambiguous boolean value",
        )
    return cast("bool", values[0])


def _local_nodes(
    node: dict[str, JsonValue], graph: GraphIndex
) -> Iterator[tuple[int, dict[str, JsonValue]]]:
    """Follow local references and lists, staying inside the selected graph."""
    pending: list[JsonValue] = [node]
    visited = set()
    while pending:
        value = pending.pop()
        if isinstance(value, list):
            pending.extend(reversed(value))
        elif isinstance(value, dict) and "@value" not in value:
            if "@list" in value:
                pending.append(value["@list"])
                continue
            identifier = value.get("@id")
            if (
                isinstance(identifier, str)
                and identifier in graph
                and identifier not in visited
            ):
                visited.add(identifier)
                index, linked = graph[identifier]
                yield index, linked
                pending.extend(
                    item for term, item in linked.items() if not term.startswith("@")
                )


def _namespaces(node: dict[str, JsonValue], graph: GraphIndex) -> list[SourcedValue]:
    """Locate namespaces of predicates and types used by the dataset."""
    found: dict[str, list[str]] = {}
    for index, linked in _local_nodes(node, graph):
        terms = [
            (term, _pointer(index, term))
            for term, values in linked.items()
            if not term.startswith("@") and values
        ]
        terms.extend(
            (term, f"/{index}/@type/{i}")
            for i, term in enumerate(cast("list[str]", linked.get("@type", [])))
        )
        for term, path in terms:
            separator = "#" if "#" in term else "/" if "/" in term else ":"
            prefix, _, local = term.rpartition(separator)
            if prefix and local:
                found.setdefault(prefix + separator, []).append(path)
    return [(namespace, tuple(paths)) for namespace, paths in found.items()]


def _linked_uris(node: dict[str, JsonValue], graph: GraphIndex) -> list[SourcedValue]:
    """Read object IRIs and types, excluding literal text and other graphs."""
    found: dict[str, list[str]] = {}
    pending: list[tuple[JsonValue, str]] = []
    for index, linked in _local_nodes(node, graph):
        for i, uri in enumerate(cast("list[str]", linked.get("@type", []))):
            if not uri.startswith("_:"):
                found.setdefault(uri, []).append(f"/{index}/@type/{i}")
        pending.extend(
            (values, _pointer(index, term))
            for term, values in linked.items()
            if not term.startswith("@")
        )
    while pending:
        value, path = pending.pop()
        if isinstance(value, list):
            pending.extend((item, f"{path}/{i}") for i, item in enumerate(value))
        elif isinstance(value, dict):
            if "@list" in value:
                pending.append((value["@list"], path + "/@list"))
            elif isinstance(
                identifier := value.get("@id"), str
            ) and not identifier.startswith("_:"):
                found.setdefault(identifier, []).append(path)
    return [(uri, tuple(paths)) for uri, paths in found.items()]


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
                normalized = value
                if field == "object_type" and isinstance(normalized, str):
                    for ns in _SCHEMA:
                        normalized = normalized.removeprefix(ns)
                cast("list[JsonValue]", fields.setdefault(field, [])).append(normalized)
                sources[field] = (*sources.get(field, ()), *paths)
    distributions, details = _distributions(node, index, graph)
    if details:
        sources["distribution_details"] = details
    namespaces = _namespaces(node, graph)
    derived = {
        **distributions,
        "related_resources": _related_resources(node, index, graph),
        "namespaces": namespaces,
        "linked_uris": _linked_uris(node, graph),
        "provenance_namespaces": [
            entry for entry in namespaces if entry[0] in _PROVENANCE
        ],
    }
    fields.update(
        {
            field: [value for value, _ in values]
            for field, values in derived.items()
            if values
        }
    )
    sources.update(
        {
            field: tuple(path for _, paths in values for path in paths)
            for field, values in derived.items()
            if values
        }
    )
    invalid = {}
    if "access_free" in fields:
        try:
            fields["access_free"] = _access_free(
                cast("list[JsonValue]", fields["access_free"])
            )
        except InputError as exc:
            fields.pop("access_free")
            invalid["access_free"] = Diagnostic(
                code=exc.code, message=str(exc), location="/metadata"
            )
    return FujiMetadata(
        fields=fields,
        sources=sources,
        invalid=invalid,
        unmapped=tuple(
            sorted(
                term
                for term in node
                if not term.startswith("@")
                and term not in _FIELDS
                and term not in _RELATIONS
                and term not in _DISTRIBUTIONS
                and not term.startswith(_PROVENANCE)
            )
        ),
    )
