"""Run F-UJI's embedded readers in their native order on supplied HTML."""

from __future__ import annotations

import json
import logging
from io import StringIO
from typing import TYPE_CHECKING

from pyRdfa import pyRdfa  # type: ignore[import-untyped]
from pyRdfa.options import Options  # type: ignore[import-untyped]
from rdflib import Graph

from fair_offline_assessor._vendor.fuji.v3_5_1.harvester.metadata_harvester import (
    MetadataHarvester,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.helper.metadata_collector import (
    MetaDataCollector,
    MetadataFormats,
    MetadataSources,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.helper.metadata_collector_dublincore import (  # noqa: E501
    MetaDataCollectorDublinCore,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.helper.metadata_collector_highwire_eprints import (  # noqa: E501
    MetaDataCollectorHighwireEprints,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.helper.metadata_collector_microdata import (  # noqa: E501
    MetaDataCollectorMicroData,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.helper.metadata_collector_opengraph import (  # noqa: E501
    MetaDataCollectorOpenGraph,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.helper.metadata_mapper import Mapper
from fair_offline_assessor.models import Diagnostic, InputError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from pydantic import JsonValue

    from fair_offline_assessor.models import AssessmentInput
    from fair_offline_assessor.profiles import LoadedProfile

type CollectedMetadata = tuple[MetaDataCollector, dict[str, JsonValue], MetadataSources]

_LOGGER = logging.getLogger(__name__)


class _HtmlHarvester(MetadataHarvester):
    def __init__(self, html: str, url: str | None) -> None:
        """Provide the document state used by the native pure HTML methods."""
        self.landing_html = html
        self.landing_url = url or "supplied HTML"
        self.extraction_failed = False
        self.logger = _LOGGER
        self.logger_target = {
            "metadata_properties": "FsF-F2-01M",
            "pid": "FsF-F1-02D",
        }


def _rdfa_graph(harvester: _HtmlHarvester) -> Graph:
    """Extract local RDFa without vocabulary expansion or vocabulary caching."""
    html = harvester.clean_html_language_tag(harvester.landing_html)  # type: ignore[no-untyped-call]
    graph = pyRdfa(
        options=Options(vocab_expansion=False, vocab_cache=False, transformers=[]),
        media_type="text/html",
    ).graph_from_source(StringIO(html))
    # Upstream F-UJI 3.5.1 metadata_harvester.py:1059-1062, commit
    # 9227fabb7f047475714f2e7622798b855c883f72 (MIT): retain its subject filter.
    clean_rdfa_graph = Graph()
    image_suffix = [".jpg", ".jpeg", ".png", ".tif", ".gif", ".svg", ".png"]
    for s, o, p in list(graph):
        if not any(x in s for x in image_suffix):
            clean_rdfa_graph.add((s, o, p))
    return clean_rdfa_graph


def _report(error: InputError, diagnostics: list[Diagnostic] | None) -> None:
    """Keep other embedded sources available after an unreadable source."""
    if diagnostics is None:
        raise error
    diagnostics.append(
        Diagnostic(
            code=error.code,
            message=str(error),
            location=error.location or "/metadata",
        )
    )


def _read_embedded(
    document: JsonValue | Graph,
    read_rdf: Callable[[JsonValue | Graph], CollectedMetadata],
    source: MetadataSources,
    metadata_format: MetadataFormats,
    diagnostics: list[Diagnostic] | None,
) -> CollectedMetadata | None:
    """Delegate RDF decoding and native selection to the shared reader."""
    try:
        collector, fields, _ = read_rdf(document)
    except InputError as error:
        _report(error, diagnostics)
        return None
    # Native base attributes have None-only annotations; RDF collectors set them.
    collector.metadata_format = metadata_format  # type: ignore[assignment]
    content_type = (
        "application/ld+json" if metadata_format == MetadataFormats.JSONLD else None
    )
    collector.content_type = content_type  # type: ignore[assignment]
    return collector, fields, source


def _extract_embedded(
    harvester: _HtmlHarvester, diagnostics: list[Diagnostic] | None
) -> dict[str, JsonValue]:
    """Observe native extraction failures without changing its source selection."""
    extracted: dict[str, JsonValue] = harvester.retrieve_metadata_embedded_extruct()  # type: ignore[no-untyped-call]
    if harvester.extraction_failed:
        _report(
            InputError(
                "invalid_embedded_metadata",
                "F-UJI could not parse embedded metadata.",
                "/metadata",
            ),
            diagnostics,
        )
    return extracted


def collect_html(  # noqa: PLR0913 - Share the parent's per-assessment config.
    request: AssessmentInput,
    profile: LoadedProfile,
    read_rdf: Callable[[JsonValue | Graph], CollectedMetadata],
    *,
    linked_vocab_index: dict[str, object],
    schema_org_creativeworks: Sequence[str] | None = None,
    diagnostics: list[Diagnostic] | None = None,
) -> list[CollectedMetadata]:
    """Return native collector results in F-UJI's embedded-source order."""
    if not isinstance(request.metadata, str):
        raise InputError(
            "unsupported_input", "HTML metadata must be supplied as text", "/metadata"
        )
    harvester = _HtmlHarvester(request.metadata, request.metadata_url)
    extracted = _extract_embedded(harvester, diagnostics)
    creativeworks = schema_org_creativeworks
    if creativeworks is None:
        creativeworks = json.loads(profile.resources["fuji:creativeworks"])[
            "creativeworks"
        ]
    results: list[CollectedMetadata] = []

    def append(result: CollectedMetadata | None) -> None:
        """Apply native empty-value handling before parent-side merging."""
        if result is None:
            return
        collector, fields, source = result
        fields = harvester.exclude_null(fields)  # type: ignore[no-untyped-call]
        if fields:
            results.append((collector, fields, source))

    if extracted.get("json-ld"):
        append(
            _read_embedded(
                extracted["json-ld"],
                read_rdf,
                MetadataSources.SCHEMAORG_EMBEDDED,
                MetadataFormats.JSONLD,
                diagnostics,
            )
        )

    dc = MetaDataCollectorDublinCore(  # type: ignore[no-untyped-call]
        request.metadata,
        Mapper.DC_MAPPING,
        _LOGGER,
        linked_vocab_index=linked_vocab_index,
    )
    source, fields = dc.parse_metadata()  # type: ignore[no-untyped-call]
    append((dc, fields, source))

    microdata = MetaDataCollectorMicroData(  # type: ignore[no-untyped-call]
        extracted.get("microdata"),
        Mapper.MICRODATA_MAPPING,
        _LOGGER,
        schema_org_creativeworks=creativeworks,
        linked_vocab_index=linked_vocab_index,
    )
    source, fields = microdata.parse_metadata()  # type: ignore[no-untyped-call]
    append((microdata, fields, source))

    try:
        graph = _rdfa_graph(harvester)
    except Exception as error:  # noqa: BLE001 - Preserve other native sources.
        _report(
            InputError("invalid_rdfa", f"Cannot parse supplied RDFa: {error}"),
            diagnostics,
        )
    else:
        if graph:
            append(
                _read_embedded(
                    graph,
                    read_rdf,
                    MetadataSources.RDFA_EMBEDDED,
                    MetadataFormats.RDFA,
                    diagnostics,
                )
            )

    highwire = MetaDataCollectorHighwireEprints(  # type: ignore[no-untyped-call]
        request.metadata, _LOGGER, linked_vocab_index=linked_vocab_index
    )
    source, fields = highwire.parse_metadata()  # type: ignore[no-untyped-call]
    append((highwire, fields, source))

    opengraph = MetaDataCollectorOpenGraph(  # type: ignore[no-untyped-call]
        extracted.get("opengraph"),
        Mapper.OG_MAPPING,
        _LOGGER,
        linked_vocab_index=linked_vocab_index,
    )
    source, fields = opengraph.parse_metadata()  # type: ignore[no-untyped-call]
    append((opengraph, fields, source))
    return results
