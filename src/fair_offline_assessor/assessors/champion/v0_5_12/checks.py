import re
from dataclasses import dataclass
from typing import Literal, cast
from urllib.parse import urlsplit

from fair_offline_assessor.assessors.champion.v0_5_12.definitions import (
    ChampionDefinitions,
)
from fair_offline_assessor.assessors.champion.v0_5_12.graph import (
    ChampionGraph,
    RdfTerm,
)
from fair_offline_assessor.assessors.champion.v0_5_12.identifiers import (
    classify_identifier,
    data_identifier,
    doi_equivalent_forms,
    matches_ruby_pattern,
    self_identifiers,
)
from fair_offline_assessor.assessors.champion.v0_5_12.input import PreparedChampionInput
from fair_offline_assessor.models import EvidenceRef, InputError, ProfileError


@dataclass(frozen=True)
class CheckContext:
    input: PreparedChampionInput
    graph: ChampionGraph | None
    definitions: ChampionDefinitions


@dataclass(frozen=True)
class CheckDecision:
    outcome: Literal["pass", "fail", "indeterminate"]
    reason_code: str
    message: str
    evidence: tuple[EvidenceRef, ...] = ()


def _input_evidence(context: CheckContext, field: str) -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef(
            resource="assessment_input",
            digest=context.input.digest,
            location=f"/{field}",
        ),
    )


def _target(context: CheckContext) -> str:
    if diagnostic := context.input.invalid.get("target_identifier"):
        raise InputError(diagnostic.code, diagnostic.message, diagnostic.location)
    target = context.input.request.target_identifier
    if target is None:
        raise InputError(
            "missing_evidence", "Supply the target identifier.", "/target_identifier"
        )
    return target


def _graph(context: CheckContext) -> ChampionGraph:
    for field in ("metadata", "subject", "local_contexts", "metadata_format"):
        if diagnostic := context.input.invalid.get(field):
            raise InputError(diagnostic.code, diagnostic.message, diagnostic.location)
    if context.graph is None:
        if diagnostic := context.input.invalid.get("metadata_url"):
            raise InputError(diagnostic.code, diagnostic.message, diagnostic.location)
        raise InputError(
            "missing_evidence", "Usable RDF metadata is required.", "/metadata"
        )
    return context.graph


def _graph_evidence(
    context: CheckContext, graph: ChampionGraph
) -> tuple[EvidenceRef, ...]:
    return graph.evidence or _input_evidence(context, "metadata")


def _recognized_target(context: CheckContext) -> CheckDecision:
    kind = classify_identifier(_target(context), context.definitions)
    evidence = _input_evidence(context, "target_identifier")
    if kind is None:
        return CheckDecision(
            "indeterminate",
            "upstream_indeterminate",
            "The target does not match a known identifier system.",
            evidence,
        )
    return CheckDecision(
        "pass",
        "passed",
        f"The target matches Champion's {kind} identifier pattern.",
        evidence,
    )


def _persistent(context: CheckContext) -> CheckDecision:
    target = _target(context)
    decision = _recognized_target(context)
    if (
        decision.outcome != "pass"
        or classify_identifier(target, context.definitions) != "uri"
    ):
        return decision
    patterns = cast(
        "list[str]", context.definitions.references["persistent_url_patterns"]
    )
    if any(matches_ruby_pattern(p, target) for p in patterns):
        return CheckDecision(
            "pass",
            "passed",
            "The target matches a known persistent-URL pattern.",
            decision.evidence,
        )
    return CheckDecision(
        "indeterminate",
        "upstream_indeterminate",
        "The target URL does not match a known persistence system.",
        decision.evidence,
    )


def _metadata_identifier(context: CheckContext) -> CheckDecision:
    target = _target(context)
    recognized = _recognized_target(context)
    if recognized.outcome != "pass":
        return recognized
    graph = _graph(context)
    evidence = recognized.evidence + _graph_evidence(context, graph)
    if not graph.statements:
        return CheckDecision(
            "indeterminate",
            "upstream_indeterminate",
            "No linked-data statements are available to locate a self-identifier.",
            evidence,
        )
    found = self_identifiers(graph, context.definitions)
    if not found or not re.search(r"\w", found[0], re.ASCII):
        return CheckDecision(
            "fail",
            "failed",
            "No usable self-identifier was found in the metadata.",
            evidence,
        )
    if any(
        value in doi_equivalent_forms(target, context.definitions) for value in found
    ):
        return CheckDecision(
            "pass", "passed", "The target identifier occurs in the metadata.", evidence
        )
    return CheckDecision(
        "fail", "failed", "Metadata self-identifiers do not match the target.", evidence
    )


def _data_identifier(context: CheckContext) -> CheckDecision:
    graph = _graph(context)
    found = data_identifier(graph, context.definitions)
    evidence = _graph_evidence(context, graph)
    if found is not None and re.search(r"\w", found, re.ASCII):
        return CheckDecision(
            "pass", "passed", "A data identifier occurs in the metadata.", evidence
        )
    return CheckDecision(
        "fail", "failed", "No data identifier was found in the metadata.", evidence
    )


def _recognized_data(
    context: CheckContext, *, require_word: bool = False
) -> CheckDecision:
    graph = _graph(context)
    found = data_identifier(graph, context.definitions)
    evidence = _graph_evidence(context, graph)
    if require_word and found is not None and not re.search(r"\w", found, re.ASCII):
        found = None
    kind = (
        classify_identifier(found, context.definitions) if found is not None else None
    )
    if kind is not None:
        return CheckDecision(
            "pass",
            "passed",
            f"The data identifier matches Champion's {kind} pattern.",
            evidence,
        )
    return CheckDecision(
        "indeterminate",
        "upstream_indeterminate",
        "No recognized data identifier was found in the metadata.",
        evidence,
    )


def _data_protocol(context: CheckContext) -> CheckDecision:
    # Unlike DataAuth, OpenProt_Data checks for a word character before typeit.
    return _recognized_data(context, require_word=True)


def _rdf_presence(context: CheckContext) -> CheckDecision:
    graph = _graph(context)
    present = bool(graph.statements)
    return CheckDecision(
        "pass" if present else "fail",
        "passed" if present else "failed",
        "RDF statements were found." if present else "No RDF statements were found.",
        _graph_evidence(context, graph),
    )


def _license(context: CheckContext, *, strong: bool = False) -> CheckDecision:
    graph = _graph(context)
    predicates = cast(
        "dict[str, list[str]]", context.definitions.references["license_predicates"]
    )["strong" if strong else "weak"]
    # Only the first value of each predicate is inspected; later predicates
    # can still pass. Weak licensing accepts literals and blank nodes too.
    first: dict[str, RdfTerm] = {}
    for statement in graph.statements:
        first.setdefault(statement.predicate, statement.object)
    found = any(
        predicate in first and (not strong or first[predicate].kind == "iri")
        for predicate in predicates
    )
    return CheckDecision(
        "pass" if found else "fail",
        "passed" if found else "failed",
        "A qualifying licence statement was found."
        if found
        else "No qualifying licence statement was found.",
        _graph_evidence(context, graph),
    )


def _strong_license(context: CheckContext) -> CheckDecision:
    return _license(context, strong=True)


def _uri_host(value: str) -> str | None:
    """Extract the host, preserving its spelling as Ruby URI#host does."""
    authority = urlsplit(value).netloc.rsplit("@", 1)[-1]
    if authority.startswith("["):
        return authority.partition("]")[0] + "]"
    return authority.partition(":")[0] or None


def _outward_references(context: CheckContext) -> CheckDecision:
    graph = _graph(context)
    evidence = _graph_evidence(context, graph)
    exclusion = cast("str", context.definitions.references["outward_link_exclusion"])
    objects = [
        s.object.value
        for s in graph.statements
        if s.object.kind == "iri" and not matches_ruby_pattern(exclusion, s.predicate)
    ]
    found = False
    if objects:
        if diagnostic := context.input.invalid.get("metadata_url"):
            raise InputError(diagnostic.code, diagnostic.message, diagnostic.location)
        origin = context.input.request.metadata_url
        if origin is None:
            raise InputError(
                "missing_evidence", "Supply the metadata origin URL.", "/metadata_url"
            )
        try:
            host = (
                _uri_host(origin)
                if urlsplit(origin).scheme in ("http", "https")
                else None
            )
        except ValueError:
            host = None
        if host is None:
            raise InputError(
                "invalid_metadata_url",
                "Supply an HTTP or HTTPS metadata origin URL with a host.",
                "/metadata_url",
            )
        found = any(_uri_host(value) != host for value in objects)
        evidence += _input_evidence(context, "metadata_url")
    return CheckDecision(
        "pass" if found else "fail",
        "passed" if found else "failed",
        "An RDF resource points outside the metadata host."
        if found
        else "No RDF resource points outside the metadata host.",
        evidence,
    )


def _metadata_persistence(context: CheckContext) -> CheckDecision:
    target = context.input.request.target_identifier
    if target is not None and classify_identifier(target, context.definitions) == "doi":
        return CheckDecision(
            "pass",
            "passed",
            "Champion assumes persistent metadata for a bare DOI.",
            _input_evidence(context, "target_identifier"),
        )
    graph = _graph(context)
    evidence = _graph_evidence(context, graph)
    predicate = context.definitions.references["persistence_policy_predicate"]
    policy = next(
        (s.object.value for s in graph.statements if s.predicate == predicate), None
    )
    if policy is None:
        return CheckDecision(
            "indeterminate",
            "upstream_indeterminate",
            "No metadata persistence policy was found.",
            evidence,
        )
    if not re.search(r"://\w+\.\w+", policy, re.ASCII):
        return CheckDecision(
            "fail",
            "failed",
            "The first persistence policy does not match Champion's URL pattern.",
            evidence,
        )
    return CheckDecision(
        "indeterminate",
        "missing_evidence",
        "The persistence policy needs retrieval evidence unavailable offline.",
        evidence,
    )


def _fair_vocabularies(context: CheckContext) -> CheckDecision:
    graph = _graph(context)
    evidence = _graph_evidence(context, graph)
    by_host: dict[str | None, set[str]] = {}
    for statement in graph.statements:
        predicate = statement.predicate
        if "1999/xhtml/" in predicate or "rdf-syntax-ns" in predicate:
            continue
        # RDF 3.3.4 accepts Unicode IRI hosts without URL normalization and
        # splits at the first colon, even for bracketed IPv6 hosts.
        match = re.match(r"^(?:[^:/?#]+:)?//([^/?#]*)", predicate)
        authority = match[1] if match else ""
        host = authority.split("@", 1)[-1].split(":", 1)[0] or None
        by_host.setdefault(host, set()).add(predicate)
    count = sum(len(predicates) for predicates in by_host.values())
    if count == 0:
        return CheckDecision(
            "fail", "failed", "No eligible vocabulary predicates were found.", evidence
        )
    patterns = cast(
        "list[str]", context.definitions.references["accepted_vocabulary_patterns"]
    )
    # Upstream tests the lexical first predicate for each host and weights
    # its decision by the number of distinct predicates on that host.
    accepted = sum(
        len(predicates)
        for predicates in by_host.values()
        if any(matches_ruby_pattern(p, min(predicates)) for p in patterns)
    )
    threshold = cast("float", context.definitions.references["vocabulary_threshold"])
    if accepted >= count * threshold:
        return CheckDecision(
            "pass",
            "passed",
            f"Champion accepts {accepted} of {count} predicates; its threshold is met.",
            evidence,
        )
    return CheckDecision(
        "indeterminate",
        "missing_evidence",
        "Vocabulary resolution evidence is needed to settle the remaining predicates.",
        evidence,
    )


def _search_indexing(_context: CheckContext) -> CheckDecision:
    return CheckDecision(
        "indeterminate",
        "unsupported_check",
        "This offline profile does not accept search-index evidence.",
    )


def evaluate_check(test_id: str, context: CheckContext) -> CheckDecision:
    """Evaluate a supported check with only its own evidence requirements."""
    evaluators = {
        "test_FM_F1_M_IdentUnique": _recognized_target,
        "test_FM_F1_M_IdentPersistent": _persistent,
        "test_FM_F3_M_MetaIdent": _metadata_identifier,
        "test_FM_F3_M_DataIdent": _data_identifier,
        "test_FM_A1_1_M_OpenProt": _recognized_target,
        "test_FM_A1_1_M_OpenProt_Data": _data_protocol,
        "test_FM_A1_2_M_Auth": _recognized_target,
        "test_FM_A1_2_M_DataAuth": _recognized_data,
        "test_FM_I1_M_FormalLangSyntax": _rdf_presence,
        "test_FM_I1_M_FormLangSemantic_Data": _rdf_presence,
        "test_FM_R1_1_M_StdLic": _license,
        "test_FM_R1_1_M_StdLic_strong": _strong_license,
        "test_FM_I3_M_QualRef": _outward_references,
        "test_FM_A2_M_MetaLong": _metadata_persistence,
        "test_FM_I2_M_FAIRVocabSyntax": _fair_vocabularies,
        "test_FM_F4_M_MetaIndexed": _search_indexing,
    }
    if test_id not in evaluators:
        raise ProfileError(
            "unsupported_definitions", f"Unsupported Champion check: {test_id}"
        )
    try:
        return evaluators[test_id](context)
    except InputError as exc:
        evidence = (
            EvidenceRef(
                resource="assessment_input",
                digest=context.input.digest,
                location=exc.location or "/metadata",
            ),
        )
        return CheckDecision("indeterminate", exc.code, str(exc), evidence)
