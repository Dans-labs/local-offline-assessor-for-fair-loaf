import json
from copy import deepcopy
from dataclasses import dataclass
from typing import cast

from pydantic import JsonValue
from pyld import FrozenDocumentLoader, jsonld  # type: ignore[import-untyped]
from pyld.context_resolver import ContextResolver  # type: ignore[import-untyped]

from fair_offline_assessor.models import (
    AssessmentInput,
    InputError,
    ProfileError,
)
from fair_offline_assessor.profiles import LoadedProfile


@dataclass(frozen=True)
class SelectedDataset:
    node: dict[str, JsonValue]
    graph: list[dict[str, JsonValue]]


def _context_loader(
    request: AssessmentInput, profile: LoadedProfile
) -> FrozenDocumentLoader:
    """Load only the selected profile's contexts and caller-supplied documents."""
    documents: dict[str, dict[str, JsonValue]] = {}
    for reference in profile.references:
        if reference.kind != "context":
            continue
        try:
            document = json.loads(profile.resources[reference.id])
        except ValueError as exc:
            raise ProfileError(
                "invalid_context", f"Invalid context: {reference.id}"
            ) from exc
        if (
            reference.format != "json"
            or not isinstance(document, dict)
            or "@context" not in document
        ):
            raise ProfileError("invalid_context", f"Invalid context: {reference.id}")
        for alias in reference.aliases:
            if alias in documents and documents[alias] != document:
                raise ProfileError(
                    "context_conflict", f"Conflicting bundled contexts: {alias}"
                )
            documents[alias] = deepcopy(document)
    for url, document in request.local_contexts.items():
        if "@context" not in document:
            raise InputError(
                "invalid_context", f"Context document must contain @context: {url}"
            )
        if url in documents and documents[url] != document:
            raise InputError(
                "context_conflict", f"Cannot replace bundled context: {url}"
            )
        documents[url] = deepcopy(document)
    return FrozenDocumentLoader(documents=documents)


def expand_metadata(
    request: AssessmentInput, profile: LoadedProfile
) -> list[dict[str, JsonValue]]:
    """Expand JSON-LD using local contexts and a separate cache for each call.

    Use absolute @import URLs; PyLD resolves relative imports against the input base.
    """
    loader = _context_loader(request, profile)
    try:
        return cast(
            "list[dict[str, JsonValue]]",
            jsonld.expand(
                request.metadata,
                options={
                    "documentLoader": loader,
                    # PyLD otherwise consults a process-wide cache before its loader.
                    "contextResolver": ContextResolver({}, loader),
                    "base": request.metadata_url or "",
                },
            ),
        )
    except jsonld.JsonLdError as exc:
        cause: BaseException | None = exc
        while cause is not None:
            if (
                isinstance(cause, jsonld.JsonLdError)
                and cause.code == "loading document failed"
            ):
                raise InputError(
                    "unknown_context",
                    f"Context unavailable locally: {cause.details['url']}",
                ) from exc
            cause = cause.__cause__
        raise InputError(
            "invalid_jsonld", f"Invalid JSON-LD metadata: {exc.code}"
        ) from exc
    except ValueError as exc:
        raise InputError("invalid_jsonld", "Cannot interpret JSON-LD metadata") from exc


def select_dataset(request: AssessmentInput, profile: LoadedProfile) -> SelectedDataset:
    """Select the requested subject or the sole Schema.org Dataset and its graph."""
    expanded = expand_metadata(request, profile)
    loader = FrozenDocumentLoader(documents={})
    issuer = jsonld.IdentifierIssuer("_:b")
    try:
        nodes = cast(
            "list[dict[str, JsonValue]]",
            jsonld.flatten(
                expanded,
                options={
                    "documentLoader": loader,
                    "contextResolver": ContextResolver({}, loader),
                    "identifierIssuer": issuer,
                },
            ),
        )
    except jsonld.JsonLdError as exc:
        raise InputError("invalid_jsonld", "Cannot combine JSON-LD records") from exc

    subject = request.subject
    if subject is not None and subject.startswith("_:"):
        # Flattening renames blank nodes; match the caller's original label.
        subject = issuer.existing.get(subject, "")
    graphs = [
        nodes,
        *(
            cast("list[dict[str, JsonValue]]", n["@graph"])
            for n in nodes
            if "@graph" in n
        ),
    ]
    matches = [
        SelectedDataset(node, graph)
        for graph in graphs
        for node in graph
        if (
            node.get("@id") == subject
            if subject is not None
            else any(
                kind in ("http://schema.org/Dataset", "https://schema.org/Dataset")
                for kind in cast("list[str]", node.get("@type", []))
            )
        )
    ]
    if not matches:
        if subject is not None:
            raise InputError(
                "subject_not_found", f"Subject not found: {request.subject}"
            )
        raise InputError(
            "dataset_not_found", "No Schema.org Dataset found; supply subject"
        )
    if len(matches) > 1:
        if subject is not None:
            raise InputError("ambiguous_subject", "Subject occurs in multiple graphs")
        raise InputError("ambiguous_dataset", "Multiple datasets found; supply subject")
    return matches[0]
