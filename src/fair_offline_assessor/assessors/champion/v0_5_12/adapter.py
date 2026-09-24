import logging
from collections.abc import Mapping
from importlib.metadata import version
from typing import TYPE_CHECKING

from fair_offline_assessor.assessors.champion.v0_5_12 import checks
from fair_offline_assessor.assessors.champion.v0_5_12.bindings import DEFINITIONS
from fair_offline_assessor.assessors.champion.v0_5_12.definitions import (
    ChampionDefinitions,
    load_definitions,
)
from fair_offline_assessor.assessors.champion.v0_5_12.graph import prepare_graph
from fair_offline_assessor.assessors.champion.v0_5_12.input import (
    prepare_champion_input,
)
from fair_offline_assessor.assessors.champion.v0_5_12.raw import test_output
from fair_offline_assessor.models import (
    AssessmentInput,
    AssessmentResult,
    CheckResult,
    Diagnostic,
    InputError,
    MetricResult,
    ProfileError,
    Provenance,
    ResourceRef,
)
from fair_offline_assessor.profiles import LoadedProfile

if TYPE_CHECKING:
    from pydantic import JsonValue

    from fair_offline_assessor.models.v1 import Outcome


def _metrics(
    definitions: ChampionDefinitions, tests: list[CheckResult]
) -> tuple[MetricResult, ...]:
    """Summarize check outcomes without inventing Champion scores or levels."""
    groups: dict[str, list[CheckResult]] = {}
    principles: dict[str, list[str]] = {}
    for definition, test in zip(definitions.tests, tests, strict=True):
        groups.setdefault(test.metric, []).append(test)
        principles.setdefault(test.metric, []).extend(definition.principles)
    metrics = []
    for identifier, group in groups.items():
        outcomes = {test.outcome for test in group}
        outcome: Outcome
        if "error" in outcomes:
            outcome = "error"
        elif "indeterminate" in outcomes:
            outcome = "indeterminate"
        elif len(outcomes) == 1:
            outcome = group[0].outcome
        else:
            outcome = "partial"
        metrics.append(
            MetricResult(
                id=identifier,
                principles=tuple(dict.fromkeys(principles[identifier])),
                outcome=outcome,
            )
        )
    return tuple(metrics)


class ChampionAdapter:
    id = "champion"
    version = "1.0.0"
    definitions = DEFINITIONS

    def assess(
        self, request: AssessmentInput | Mapping[str, object], profile: LoadedProfile
    ) -> AssessmentResult:
        """Run pinned Python decisions on supplied evidence and retain FTR output."""
        definitions = load_definitions(profile)
        supplied = prepare_champion_input(request)
        graph = None
        if not supplied.invalid.keys() & {
            "metadata",
            "subject",
            "metadata_format",
            "local_contexts",
        }:
            try:
                graph = prepare_graph(supplied.request, profile)
            except InputError as exc:
                supplied.invalid["metadata"] = Diagnostic(
                    code=exc.code,
                    message=str(exc),
                    location=exc.location or "/metadata",
                )
            except ProfileError:
                raise
            except Exception:
                logging.getLogger(__name__).debug(
                    "Champion graph preparation failed", exc_info=True
                )
                supplied.invalid["metadata"] = Diagnostic(
                    code="evaluator_error",
                    message="Champion could not prepare the supplied metadata.",
                    location="/metadata",
                )
        context = checks.CheckContext(supplied, graph, definitions)
        tests = []
        raw: list[JsonValue] = []
        for definition in definitions.tests:
            try:
                decision = checks.evaluate_check(definition.id, context)
                # A preparation exception is an execution error only for checks
                # that actually needed the graph. Target-only checks still run.
                outcome = (
                    "error"
                    if decision.reason_code == "evaluator_error"
                    else decision.outcome
                )
                result = CheckResult(
                    id=definition.id,
                    metric=definition.metric,
                    outcome=outcome,
                    reason_code=decision.reason_code,
                    message=decision.message,
                    evidence=decision.evidence,
                )
                if outcome != "error":
                    raw.append(
                        test_output(
                            definition,
                            decision,
                            supplied.request.target_identifier,
                            adapter_version=self.version,
                        )
                    )
            except ProfileError:
                raise
            except Exception:
                logging.getLogger(__name__).debug(
                    "Champion check %s failed", definition.id, exc_info=True
                )
                result = CheckResult(
                    id=definition.id,
                    metric=definition.metric,
                    outcome="error",
                    reason_code="evaluator_error",
                    message="Champion could not complete this check.",
                )
            tests.append(result)
        return AssessmentResult(
            profile=profile.info,
            provenance=Provenance(
                engine_version=version("fair-offline-assessor"),
                processor_version=version("PyLD"),
                input_digest=supplied.digest,
                resources=tuple(
                    ResourceRef.model_validate(
                        ref.model_dump(include=set(ResourceRef.model_fields))
                    )
                    for ref in profile.references
                ),
            ),
            tests=tuple(tests),
            metrics=_metrics(definitions, tests),
            diagnostics=tuple(supplied.invalid.values()),
            raw=raw,
        )
