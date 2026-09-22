from collections.abc import Iterator
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import cast

from pydantic import JsonValue

from fair_offline_assessor._metadata import SelectedResource, select_resource
from fair_offline_assessor.models import AssessmentInput, Diagnostic, InputError
from fair_offline_assessor.profiles import LoadedProfile

_SCHEMA = ("http://schema.org/", "https://schema.org/")
_BOOLEAN_VALUES = {"true": True, "1": True, "false": False, "0": False}
_DCAT = "http://www.w3.org/ns/dcat#"
_DATASET_TYPES = (
    *(ns + "Dataset" for ns in _SCHEMA),
    _DCAT + "Dataset",
    "http://purl.org/dc/dcmitype/Dataset",
)
_PROVENANCE = ("http://www.w3.org/ns/prov#", "http://purl.org/pav/")
_DISTRIBUTIONS = (*(ns + "distribution" for ns in _SCHEMA), _DCAT + "distribution")
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
    "object_content_identifier": (
        *(ns + term for ns in _SCHEMA for term in ("contentUrl", "url")),
        _DCAT + "downloadURL",
        _DCAT + "accessURL",
    ),
    "type": (
        *(ns + term for ns in _SCHEMA for term in ("encodingFormat", "fileFormat")),
        _DCAT + "mediaType",
        "http://purl.org/dc/elements/1.1/format",
        "http://purl.org/dc/terms/format",
    ),
    "size": (
        *(ns + term for ns in _SCHEMA for term in ("contentSize", "fileSize")),
        _DCAT + "byteSize",
    ),
    "related_resources": (
        *(ns + term for ns in _SCHEMA for term in ("url", "identifier")),
        *_NAMES,
    ),
}

type GraphIndex = dict[str, tuple[int, dict[str, JsonValue]]]
# None marks an unreadable structure; absent values produce no entry.
type SourcedValue = tuple[JsonValue, tuple[str, ...]]
type Unreadable = dict[str, list[Diagnostic]]


@dataclass(frozen=True)
class FujiMetadata:
    fields: dict[str, JsonValue]
    # JSON pointers into SelectedResource.graph retain the original literal details.
    sources: dict[str, tuple[str, ...]]
    unmapped: tuple[str, ...]
    invalid: dict[str, Diagnostic] = dataclass_field(default_factory=dict)
    unreadable: Unreadable = dataclass_field(default_factory=dict)


def select_dataset(
    request: AssessmentInput, profile: LoadedProfile
) -> SelectedResource:
    """Select the requested subject or the sole supported Dataset."""
    try:
        return select_resource(request, profile, resource_types=_DATASET_TYPES)
    except InputError as exc:
        if exc.code == "resource_not_found":
            raise InputError(
                "dataset_not_found", "No supported Dataset found; supply subject"
            ) from exc
        if exc.code == "ambiguous_resource":
            raise InputError(
                "ambiguous_dataset", "Multiple datasets found; supply subject"
            ) from exc
        raise


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
            literal = value["@value"]
            if (
                isinstance(literal, str)
                and value.get("@type") == "http://www.w3.org/2001/XMLSchema#boolean"
            ):
                return [(_BOOLEAN_VALUES.get(literal, literal), (location,))]
            value = literal
        else:
            return _reference_values(
                value, location, graph, properties, prefer_id=prefer_id
            )
    if value is None or (isinstance(value, str) and not value.strip()):
        return []
    return [(None if isinstance(value, (dict, list)) else value, (location,))]


def _reference_values(
    value: dict[str, JsonValue],
    location: str,
    graph: GraphIndex,
    properties: tuple[str, ...],
    *,
    prefer_id: bool,
) -> list[SourcedValue]:
    """Read local details, retaining unsupported references and usable IRIs."""
    identifier = value.get("@id")
    if not isinstance(identifier, str):
        return [(None, (location,))] if value else []
    if prefer_id and not identifier.startswith("_:"):
        properties = ()
    found = _linked_values(identifier, location, graph, properties)
    if any(item is not None for item, _ in found):
        return found
    if not identifier.startswith("_:"):
        return [*found, (identifier, (location,))]
    if found:
        return found
    node = graph.get(identifier, (0, {}))[1]
    return [] if any(term in node for term in properties) else [(None, (location,))]


def _readable(
    entries: list[SourcedValue],
    fields: tuple[str, ...],
    unreadable: Unreadable,
    *,
    strings: bool = False,
) -> list[SourcedValue]:
    """Separate usable values from findings at their original graph locations."""
    found: list[SourcedValue] = []
    for value, paths in entries:
        if value is None or (strings and not isinstance(value, str)):
            note = Diagnostic(
                code="unsupported_structure",
                message="F-UJI cannot interpret this metadata structure.",
                location=paths[-1],
            )
            for field in fields:
                unreadable.setdefault(field, []).append(note)
        else:
            found.append((value, paths))
    return found


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
    node: dict[str, JsonValue], index: int, graph: GraphIndex, unreadable: Unreadable
) -> list[SourcedValue]:
    """Keep typed references, using local details only for anonymous resources."""
    related: list[SourcedValue] = []
    for term, items in node.items():
        if term not in _RELATIONS:
            continue
        for i, item in enumerate(cast("list[JsonValue]", items)):
            location = f"{_pointer(index, term)}/{i}"
            values = _readable(
                _values(
                    item, location, graph, _DETAILS["related_resources"], prefer_id=True
                ),
                ("related_resources",),
                unreadable,
                strings=True,
            )
            related.extend(
                ({"related_resource": value, "relation_type": term}, paths)
                for value, paths in values
            )
    return related


def _distribution_details(
    identifier: str, location: str, graph: GraphIndex, unreadable: Unreadable
) -> tuple[dict[str, JsonValue], dict[str, tuple[str, ...]]]:
    """Read each distribution's declarations without combining different files."""
    fields: dict[str, JsonValue] = {}
    sources: dict[str, tuple[str, ...]] = {}
    for field in ("type", "size"):
        entries = _readable(
            _linked_values(identifier, location, graph, _DETAILS[field]),
            ("distribution_details", "file_formats")
            if field == "type"
            else ("distribution_details",),
            unreadable,
            strings=field == "type",
        )
        values = [value for value, _ in entries]
        if field == "type":
            values = [
                value.removeprefix(
                    "https://www.iana.org/assignments/media-types/"
                ).removeprefix("http://www.iana.org/assignments/media-types/")
                if isinstance(value, str)
                else value
                for value in values
            ]
        if values:
            fields[field] = values[0] if len(values) == 1 else values
            sources[field] = tuple(path for _, paths in entries for path in paths)
    return fields, sources


def _distribution_links(
    value: JsonValue, location: str, term: str, graph: GraphIndex
) -> list[SourcedValue]:
    """Distinguish declared data links from unsupported distribution structures."""
    properties = _DETAILS["object_content_identifier"]
    if term != _DCAT + "distribution":
        return _values(value, location, graph, properties)
    identifier = value.get("@id") if isinstance(value, dict) else None
    if not isinstance(identifier, str):
        return [(None, (location,))] if _values(value, location, graph) else []
    found = _linked_values(identifier, location, graph, properties)
    node = graph.get(identifier, (0, {}))[1]
    return (
        found
        if found or any(prop in node for prop in properties)
        else [(None, (location,))]
    )


def _distributions(
    node: dict[str, JsonValue],
    index: int,
    graph: GraphIndex,
    unreadable: Unreadable,
    *,
    dataset_fields: dict[str, JsonValue],
) -> tuple[dict[str, list[SourcedValue]], tuple[str, ...]]:
    """Pair download links with their declarations, keeping their sources separate."""
    pending = [
        (node[term], _pointer(index, term), term)
        for term in _DISTRIBUTIONS
        if term in node
    ]
    pending.reverse()
    found: list[SourcedValue] = []
    formats: list[SourcedValue] = []
    fallbacks: dict[str, list[SourcedValue]] = {"license": [], "access_level": []}
    sources: list[str] = []
    while pending:
        value, location, term = pending.pop()
        if isinstance(value, list):
            pending.extend(
                (item, f"{location}/{i}", term)
                for i, item in reversed(list(enumerate(value)))
            )
            continue
        if isinstance(value, dict) and "@list" in value:
            pending.append((value["@list"], location + "/@list", term))
            continue
        identifier = value.get("@id") if isinstance(value, dict) else None
        urls = _readable(
            _distribution_links(value, location, term, graph),
            ("object_content_identifier", "distribution_details", "file_formats"),
            unreadable,
            strings=True,
        )
        details: dict[str, JsonValue] = {}
        detail_sources: dict[str, tuple[str, ...]] = {}
        if urls and isinstance(identifier, str):
            details, detail_sources = _distribution_details(
                identifier, location, graph, unreadable
            )
            sources.extend(path for paths in detail_sources.values() for path in paths)
            if term == _DCAT + "distribution":
                for field, properties in {
                    "license": ("http://purl.org/dc/terms/license",),
                    "access_level": (
                        "http://purl.org/dc/terms/accessRights",
                        "http://purl.org/dc/terms/rights",
                    ),
                }.items():
                    if (
                        field in dataset_fields
                        or fallbacks[field]
                        or (field == "access_level" and "access_free" in dataset_fields)
                    ):
                        continue
                    fallbacks[field] = _readable(
                        _linked_values(identifier, location, graph, properties),
                        (field,),
                        unreadable,
                        strings=True,
                    )[:1]
        found.extend(({"url": url, **details}, paths) for url, paths in urls)
        types = details.get("type", [])
        formats.extend(
            ({"url": url, "type": mime}, (*paths, *detail_sources.get("type", ())))
            for url, paths in urls
            for mime in (types if isinstance(types, list) else [types])
            if isinstance(mime, str) and mime.strip()
        )
    return {
        "object_content_identifier": found,
        "file_formats": formats,
        **fallbacks,
    }, tuple(sources)


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


def prepare_metadata(dataset: SelectedResource) -> FujiMetadata:
    """Map selected metadata into F-UJI fields, retaining source locations."""
    graph = {
        cast("str", node["@id"]): (i, node) for i, node in enumerate(dataset.graph)
    }
    index, node = graph[cast("str", dataset.node["@id"])]
    fields: dict[str, JsonValue] = {}
    sources: dict[str, tuple[str, ...]] = {}
    unreadable: Unreadable = {}
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
            entry = (
                None if term == "@id" and cast("str", item).startswith("_:") else entry
            )
            for value, paths in _readable(
                _values(entry, path, graph, properties), (field,), unreadable
            ):
                normalized = value
                if field == "object_type" and isinstance(normalized, str):
                    for ns in _SCHEMA:
                        normalized = normalized.removeprefix(ns)
                cast("list[JsonValue]", fields.setdefault(field, [])).append(normalized)
                sources[field] = (*sources.get(field, ()), *paths)
    distributions, details = _distributions(
        node, index, graph, unreadable, dataset_fields=fields
    )
    if details:
        sources["distribution_details"] = details
    namespaces = _namespaces(node, graph)
    derived = {
        **distributions,
        "related_resources": _related_resources(node, index, graph, unreadable),
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
        sources={
            **sources,
            **{
                field: (
                    *sources.get(field, ()),
                    *(cast("str", note.location) for note in notes),
                )
                for field, notes in unreadable.items()
            },
        },
        invalid=invalid,
        unreadable=unreadable,
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
