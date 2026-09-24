import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Literal, cast
from urllib.parse import urljoin

from pyld import FrozenDocumentLoader, jsonld  # type: ignore[import-untyped]
from pyld.context_resolver import ContextResolver  # type: ignore[import-untyped]
from pyld.identifier_issuer import IdentifierIssuer  # type: ignore[import-untyped]

from fair_offline_assessor._metadata import expand_metadata
from fair_offline_assessor.models import ChampionInput, EvidenceRef, InputError
from fair_offline_assessor.models.v1 import JsonObject
from fair_offline_assessor.profiles import LoadedProfile

RdfKind = Literal["iri", "blank", "literal"]
RdfDataset = dict[str, list[dict[str, dict[str, str]]]]


@dataclass(frozen=True)
class RdfTerm:
    kind: RdfKind
    value: str
    datatype: str | None = None
    language: str | None = None


@dataclass(frozen=True)
class Statement:
    subject: RdfTerm
    predicate: str
    object: RdfTerm


@dataclass(frozen=True)
class ChampionGraph:
    statements: tuple[Statement, ...]
    digest: str
    evidence: tuple[EvidenceRef, ...]


def _document(
    metadata: JsonObject | list[JsonObject] | str,
) -> JsonObject | list[JsonObject]:
    """Parse document text locally so PyLD never treats it as a retrieval URL."""
    try:
        document = json.loads(metadata) if isinstance(metadata, str) else metadata
        json.dumps(document, ensure_ascii=False, allow_nan=False).encode()
    except (ValueError, TypeError) as exc:
        raise InputError(
            "invalid_json", "Supply valid JSON-LD metadata.", "/metadata"
        ) from exc
    if not isinstance(document, dict) and not (
        isinstance(document, list) and all(isinstance(item, dict) for item in document)
    ):
        raise InputError(
            "unsupported_input",
            "Supply a JSON-LD object or array of objects.",
            "/metadata",
        )
    return cast("JsonObject | list[JsonObject]", document)


def _term(node: dict[str, str]) -> RdfTerm:
    """Keep RDF resources, blank nodes and literal values distinct."""
    kinds: dict[str, RdfKind] = {
        "IRI": "iri",
        "blank node": "blank",
        "literal": "literal",
    }
    return RdfTerm(
        kinds[node["type"]], node["value"], node.get("datatype"), node.get("language")
    )


def _select_graph(
    dataset: RdfDataset, subject: str | None
) -> list[dict[str, dict[str, str]]]:
    """Choose one graph, retaining all its statements and keeping others separate."""
    if subject is not None:
        matches = [
            triples
            for triples in dataset.values()
            if any(triple["subject"]["value"] == subject for triple in triples)
        ]
        if not matches:
            raise InputError(
                "subject_not_found",
                "The selected subject has no statements in the supplied metadata.",
                "/subject",
            )
        if len(matches) != 1:
            raise InputError(
                "ambiguous_subject",
                "The selected subject occurs in more than one graph.",
                "/subject",
            )
        return matches[0]
    nonempty = [triples for triples in dataset.values() if triples]
    if len(nonempty) > 1:
        raise InputError(
            "ambiguous_graph",
            "Supply one nonempty graph or select a subject in one graph.",
            "/metadata",
        )
    return nonempty[0] if nonempty else []


def prepare_graph(request: ChampionInput, profile: LoadedProfile) -> ChampionGraph:
    """Prepare one RDF graph from supplied JSON-LD using local contexts only."""
    if request.metadata_format not in (None, "json-ld"):
        raise InputError(
            "unsupported_metadata_format",
            "Champion accepts JSON-LD metadata.",
            "/metadata_format",
        )
    document = _document(request.metadata)
    expanded = expand_metadata(
        request.model_copy(update={"metadata": document}), profile
    )
    loader = FrozenDocumentLoader(documents={})
    issuer = IdentifierIssuer("_:b")
    try:
        dataset = cast(
            "RdfDataset",
            jsonld.to_rdf(
                expanded,
                options={
                    "documentLoader": loader,
                    "contextResolver": ContextResolver({}, loader),
                    "identifierIssuer": issuer,
                    "base": request.metadata_url or "",
                },
            ),
        )
    except (jsonld.JsonLdError, ValueError) as exc:
        raise InputError(
            "invalid_jsonld", "Cannot convert the supplied JSON-LD to RDF.", "/metadata"
        ) from exc
    subject = request.subject
    if subject is not None:
        if subject.startswith("_:"):
            if not issuer.has_id(subject):
                raise InputError(
                    "subject_not_found",
                    "The selected blank node is absent from the supplied metadata.",
                    "/subject",
                )
            subject = issuer.get_id(subject)
        else:
            subject = urljoin(request.metadata_url or "", subject)
    triples = _select_graph(dataset, subject)
    # RDF graphs are sets, but candidate decisions use the pinned PyLD traversal.
    statements = tuple(
        dict.fromkeys(
            Statement(_term(t["subject"]), t["predicate"]["value"], _term(t["object"]))
            for t in triples
        )
    )
    content = json.dumps(
        [asdict(s) for s in statements],
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    digest = sha256(content).hexdigest()
    evidence = tuple(
        EvidenceRef(
            resource="prepared_metadata",
            digest=digest,
            location=f"/{index}",
            subject=s.subject.value,
        )
        for index, s in enumerate(statements)
    )
    return ChampionGraph(statements, digest, evidence)
