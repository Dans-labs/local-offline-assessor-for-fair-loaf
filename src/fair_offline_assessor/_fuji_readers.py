"""Supply documents to F-UJI's pinned readers; keep their mapping and selection."""

import json
import logging
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import cast

from pydantic import JsonValue
from pyld import jsonld  # type: ignore[import-untyped]
from rdflib import Dataset, Graph
from rdflib.compare import to_canonical_graph

from fair_offline_assessor._metadata import expand_metadata
from fair_offline_assessor._vendor.fuji.v3_5_1.controllers.fair_check import FAIRCheck
from fair_offline_assessor._vendor.fuji.v3_5_1.harvester.metadata_harvester import (
    MetadataHarvester,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.helper.linked_vocab_helper import (
    LinkedVocabHelper,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.helper.metadata_collector import (
    MetaDataCollector,
    MetadataFormats,
    MetadataSources,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.helper.metadata_collector_datacite import (  # noqa: E501
    MetaDataCollectorDatacite,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.helper.metadata_collector_rdf import (
    MetaDataCollectorRdf,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.helper.metadata_collector_xml import (
    MetaDataCollectorXML,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.helper.metadata_mapper import Mapper
from fair_offline_assessor.models import AssessmentInput, Diagnostic, InputError
from fair_offline_assessor.profiles import LoadedProfile

_LOGGER = logging.getLogger(__name__)
_RDF_FORMATS = {"turtle", "n3", "nt", "nquads", "trig", "rdfxml"}


@dataclass(frozen=True)
class FujiMetadata:
    fields: dict[str, JsonValue]
    sources: dict[str, tuple[str, ...]] = field(default_factory=dict)
    diagnostics: tuple[Diagnostic, ...] = ()


class _LocalDocument:
    """Supply the small transport interface used by native document readers."""

    checked_content_hash = None
    checked_content: dict[str, object]

    def __init__(
        self, content: bytes | dict[str, JsonValue], format_: MetadataFormats
    ) -> None:
        self.content = content
        self.format = format_
        self.content_type = (
            "application/xml" if format_ == MetadataFormats.XML else "application/json"
        )
        self.response_content = content
        self.checked_content = {}
        self.blocked_urls: list[str] = []

    def __call__(self, _url: str, _logger: logging.Logger) -> "_LocalDocument":
        return self

    def setAcceptType(self, _accept_type: object) -> None:  # noqa: N802
        """Use the supplied format without negotiating remotely."""

    def setAuthToken(self, _token: object, _type: object) -> None:  # noqa: N802
        """No authentication is needed for supplied evidence."""

    def addAcceptType(self, _accept_type: object) -> None:  # noqa: N802
        """Keep the supplied document's declared format."""

    def content_negotiate(
        self, _metric: str
    ) -> tuple[MetadataFormats, bytes | dict[str, JsonValue]]:
        """Return only the supplied content."""
        return self.format, self.content

    def get(self, url: str, **_kwargs: object) -> None:
        """Refuse attempts to dereference distributions."""
        self.blocked_urls.append(str(url))
        raise OSError("External metadata is unavailable offline")


class _RdfReader(MetaDataCollectorRdf):
    """Observe native selection without changing its fields or priorities."""

    selected: set[str]

    def get_core_metadata(
        self,
        g: Graph,
        item: object,
        type: object = "Dataset",  # noqa: A002
    ) -> dict[str, JsonValue]:
        """Remember which subjects F-UJI actually chose."""
        self.selected.add(str(item))
        return cast("dict[str, JsonValue]", super().get_core_metadata(g, item, type))  # type: ignore[no-untyped-call]


def _json_document(request: AssessmentInput) -> AssessmentInput:
    """Decode JSON text; never interpret a string as a location to fetch."""
    metadata = request.metadata
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
            json.dumps(metadata, allow_nan=False, ensure_ascii=False).encode()
        except ValueError as exc:
            raise InputError(
                "invalid_json", "Supply valid JSON document text."
            ) from exc
    if not isinstance(metadata, dict) and not (
        isinstance(metadata, list) and all(isinstance(item, dict) for item in metadata)
    ):
        raise InputError(
            "unsupported_input", "Supply a JSON object or array of objects."
        )
    return request.model_copy(update={"metadata": metadata})


def _text_document(request: AssessmentInput) -> str:
    """Require document contents and reject external XML entity declarations."""
    if not isinstance(request.metadata, str):
        raise InputError(
            "unsupported_input", "This metadata format requires document text."
        )
    if request.metadata_format in {"xml", "rdfxml"} and re.search(
        r"<!\s*(?:DOCTYPE|ENTITY)\b", request.metadata, re.IGNORECASE
    ):
        raise InputError(
            "unsafe_xml",
            "XML DOCTYPE and entity declarations are not supported offline.",
        )
    return request.metadata


def _rdf_document(request: AssessmentInput, profile: LoadedProfile) -> Graph:
    """Decode RDF locally, with bundled and explicitly supplied JSON-LD contexts."""
    graph = Dataset(default_union=True)
    try:
        if request.metadata_format in (None, "json-ld"):
            expanded = expand_metadata(_json_document(request), profile)
            data = jsonld.to_rdf(expanded, options={"format": "application/n-quads"})
            graph.parse(data=data, format="nquads", publicID=request.metadata_url)
        else:
            graph.parse(
                data=_text_document(request),
                format="xml"
                if request.metadata_format == "rdfxml"
                else request.metadata_format,
                publicID=request.metadata_url,
            )
    except InputError:
        raise
    except Exception as exc:
        raise InputError(
            "invalid_rdf", "Cannot parse the supplied RDF document."
        ) from exc
    if not graph:
        raise InputError(
            "metadata_not_found", "The supplied document contains no RDF statements."
        )
    # Stable labels prevent random blank IDs leaking into native results.
    # Named graphs follow the upstream reader's union semantics.
    union = Graph()
    for triple in graph.triples((None, None, None)):
        union.add(triple)
    return to_canonical_graph(union)


def _merge(
    collector: MetaDataCollector,
    fields: dict[str, JsonValue],
    source: MetadataSources,
    request: AssessmentInput,
    previous: dict[str, JsonValue] | None = None,
) -> dict[str, JsonValue]:
    """Apply the native field whitelist, list normalization and merge rules."""
    state = SimpleNamespace(
        metadata_merged=previous if previous is not None else {},
        reference_elements=Mapper.REFERENCE_METADATA_LIST.value,
        metadata_unmerged=[],
        related_resources=[],
        allowed_metadata_standards=[],
        logger=_LOGGER,
        logger_target={"metadata_properties": "FsF-F2-01M"},
        # This lookup annotates the harvest log; evaluation uses its own pinned
        # catalogue. The supplied document is not filtered by standard.
        get_metadata_standard_by_uris=lambda _uris: None,
    )
    fields = MetadataHarvester().exclude_null(fields)  # type: ignore[no-untyped-call]
    MetadataHarvester.merge_metadata(  # type: ignore[no-untyped-call]
        cast("MetadataHarvester", state),
        fields,
        request.metadata_url,
        source,
        collector.metadata_format,
        collector.content_type,
        namespaces=list(collector.namespaces),
    )
    return cast("dict[str, JsonValue]", state.metadata_merged)


def _evaluation_context(
    fields: dict[str, JsonValue], collectors: list[MetaDataCollector]
) -> None:
    """Pass native declarations to offline checks without mapping RDF terms."""
    namespaces = sorted({str(ns) for c in collectors for ns in c.namespaces})
    fields["namespaces"] = cast("JsonValue", namespaces)
    fields["provenance_namespaces"] = cast("JsonValue", namespaces)
    fields["linked_uris"] = sorted(
        {ns for c in collectors for ns in c.linked_namespaces}
    )
    distributions = fields.get("object_content_identifier")
    if isinstance(distributions, list):
        fields["file_formats"] = [
            item
            for item in distributions
            if isinstance(item, dict) and item.get("type")
        ]


def _read_rdf(
    request: AssessmentInput,
    graph: Graph,
    transport: _LocalDocument,
    creativeworks: list[str],
    linked_vocab_index: dict[str, object],
) -> tuple[MetaDataCollector, dict[str, JsonValue], MetadataSources]:
    """Run the native RDF reader and check an optional subject assertion."""
    rdf = _RdfReader(  # type: ignore[no-untyped-call]
        _LOGGER,
        target_url=request.metadata_url,
        request_helper=transport,
        schema_org_creativeworks=creativeworks,
        linked_vocab_index=linked_vocab_index,
    )
    rdf.selected = set()
    rdf.setLinkedNamespaces(rdf.getAllURIS(graph))  # type: ignore[no-untyped-call]
    fields = rdf.get_metadata_from_graph(graph)  # type: ignore[no-untyped-call]
    if request.subject is not None and rdf.selected != {request.subject}:
        raise InputError(
            "subject_not_selected",
            "F-UJI selected a different or ambiguous subject; "
            "supply a document describing the intended resource.",
            "/subject",
        )
    return rdf, fields, MetadataSources.RDF_NEGOTIATED


def _read_document(
    request: AssessmentInput, linked_vocab_index: dict[str, object]
) -> tuple[MetaDataCollector, dict[str, JsonValue], MetadataSources]:
    """Provide one XML or DataCite document to its native collector."""
    format_ = request.metadata_format
    collector: MetaDataCollectorXML | MetaDataCollectorDatacite
    if request.subject is not None:
        raise InputError(
            "unsupported_subject",
            "Subject selection is only available as an RDF selection check.",
            "/subject",
        )
    if format_ == "xml":
        transport = _LocalDocument(
            _text_document(request).encode(), MetadataFormats.XML
        )
        collector = MetaDataCollectorXML(  # type: ignore[no-untyped-call]
            _LOGGER,
            target_url=request.metadata_url,
            request_helper=transport,
            linked_vocab_index=linked_vocab_index,
        )
    else:
        metadata = _json_document(request).metadata
        if not isinstance(metadata, dict) or not metadata.get("agency"):
            raise InputError(
                "unsupported_datacite_shape",
                "F-UJI expects flat negotiated DataCite JSON containing agency; "
                "REST API data.attributes envelopes are not supported.",
            )
        transport = _LocalDocument(metadata, MetadataFormats.JSON)
        collector = MetaDataCollectorDatacite(  # type: ignore[no-untyped-call]
            Mapper.DATACITE_JSON_MAPPING,
            pid_url=request.metadata_url or "urn:supplied:metadata",
            loggerinst=_LOGGER,
            request_helper=transport,
            linked_vocab_index=linked_vocab_index,
        )
    source, fields = collector.parse_metadata()  # type: ignore[no-untyped-call]
    if not fields:
        raise InputError(
            "metadata_not_found",
            "F-UJI could not extract metadata from this document.",
        )
    return collector, fields, source


def prepare_metadata(request: AssessmentInput, profile: LoadedProfile) -> FujiMetadata:
    """Read one supplied document with the pinned F-UJI reader and merger."""
    format_ = request.metadata_format or "json-ld"
    creativeworks = json.loads(profile.resources["fuji:creativeworks"])["creativeworks"]
    vocabulary_helper = LinkedVocabHelper({})  # type: ignore[no-untyped-call]
    vocabulary_helper.linked_vocab_dict = json.loads(
        profile.resources["fuji:vocabularies"]
    )["vocabularies"]
    vocabulary_helper.set_linked_vocab_index()  # type: ignore[no-untyped-call]
    linked_vocab_index = vocabulary_helper.linked_vocab_index
    transport = _LocalDocument(b"", MetadataFormats.RDF)
    diagnostics: list[Diagnostic] = []
    collector: MetaDataCollector
    if format_ == "html":
        from fair_offline_assessor._fuji_html import collect_html  # noqa: PLC0415

        if request.subject is not None:
            raise InputError(
                "unsupported_subject",
                "HTML uses F-UJI's embedded-source selection.",
                "/subject",
            )

        def read_embedded(
            metadata: JsonValue | Graph,
        ) -> tuple[MetaDataCollector, dict[str, JsonValue], MetadataSources]:
            """Apply the same reader to embedded JSON-LD and already parsed RDFa."""
            graph = (
                to_canonical_graph(metadata)
                if isinstance(metadata, Graph)
                else _rdf_document(
                    request.model_copy(
                        update={"metadata": metadata, "metadata_format": "json-ld"}
                    ),
                    profile,
                )
            )
            return _read_rdf(
                request, graph, transport, creativeworks, linked_vocab_index
            )

        entries = collect_html(
            request,
            profile,
            read_embedded,
            schema_org_creativeworks=creativeworks,
            linked_vocab_index=linked_vocab_index,
            diagnostics=diagnostics,
        )
    elif format_ == "json-ld" or format_ in _RDF_FORMATS:
        entries = [
            _read_rdf(
                request,
                _rdf_document(request, profile),
                transport,
                creativeworks,
                linked_vocab_index,
            )
        ]
    elif format_ in {"xml", "datacite-json"}:
        entries = [_read_document(request, linked_vocab_index)]
    else:
        raise InputError(
            "unsupported_metadata_format",
            f"F-UJI does not support supplied format: {format_}",
            "/metadata_format",
        )
    if not entries:
        if diagnostics:
            note = diagnostics[0]
            raise InputError(note.code, note.message, note.location)
        raise InputError(
            "metadata_not_found",
            "F-UJI found no supported metadata in the supplied document.",
        )
    fields: dict[str, JsonValue] = {}
    for collector, values, source in entries:
        fields = _merge(collector, values, source, request, fields)
    cleanup = SimpleNamespace(metadata_merged=fields, logger=_LOGGER)
    FAIRCheck.clean_metadata(cast("FAIRCheck", cleanup))  # type: ignore[no-untyped-call]
    fields = cleanup.metadata_merged
    _evaluation_context(fields, [entry[0] for entry in entries])
    diagnostics.extend(
        Diagnostic(
            code="offline_reference",
            message=f"F-UJI could not retrieve referenced metadata offline: {url}",
            location="/metadata",
        )
        for url in dict.fromkeys(transport.blocked_urls)
    )
    return FujiMetadata(
        fields=fields,
        sources={
            name: ("/metadata",)
            for name, value in fields.items()
            if value not in (None, [], {}, "")
        },
        diagnostics=tuple(diagnostics),
    )
