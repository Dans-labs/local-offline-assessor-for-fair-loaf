import re
from dataclasses import dataclass
from typing import Literal, cast

from fair_offline_assessor.assessors.champion.v0_5_12.definitions import (
    ChampionDefinitions,
)
from fair_offline_assessor.assessors.champion.v0_5_12.graph import ChampionGraph
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
