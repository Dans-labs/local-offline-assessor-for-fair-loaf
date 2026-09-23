import logging
from collections.abc import Mapping
from importlib.metadata import version
from typing import Literal

from fair_offline_assessor._input import PreparedInput, prepare_input
from fair_offline_assessor.assessors.fuji import checks as fuji_checks
from fair_offline_assessor.assessors.fuji.metadata import (
    FujiMetadata,
    prepare_metadata,
)
from fair_offline_assessor.models import (
    AssessmentInput,
    AssessmentResult,
    CheckResult,
    Diagnostic,
    EvidenceRef,
    InputError,
    MetricResult,
    ProfileError,
    Provenance,
    ResourceRef,
)
from fair_offline_assessor.profiles import LoadedProfile


def _evidence(
    supplied: PreparedInput, sources: dict[str, tuple[str, ...]]
) -> dict[str, tuple[EvidenceRef, ...]]:
    """Cite supplied evidence; native readers do not emit field-level locations."""
    return {
        field: tuple(
            EvidenceRef(
                resource="assessment_input",
                digest=supplied.digest,
                location=path,
            )
            for path in dict.fromkeys(paths)
        )
        for field, paths in sources.items()
    }


def _unmeasured(
    definition: fuji_checks.MetricDefinition,
    *,
    outcome: Literal["indeterminate", "error"] = "indeterminate",
    issues: Mapping[str, Diagnostic] | None = None,
) -> tuple[MetricResult, tuple[CheckResult, ...]]:
    """Keep unavailable checks and execution errors visible without assigning points."""
    identifier = definition["metric_identifier"]
    # F-UJI metrics 0.8 omits fair_principle on its F4 metric.
    principle = definition.get("fair_principle", identifier.split("-")[1])
    reason = "evaluator_error" if outcome == "error" else "unsupported_check"
    message = (
        "F-UJI could not complete this check."
        if outcome == "error"
        else "This check requires evidence unavailable to the offline evaluator."
    )
    return (
        MetricResult(id=identifier, principles=(principle,), outcome=outcome),
        tuple(
            CheckResult(
                id=check["metric_test_identifier"],
                metric=identifier,
                outcome=outcome,
                reason_code=issues[check["metric_test_identifier"]].code
                if issues
                else reason,
                message=issues[check["metric_test_identifier"]].message
                if issues
                else message,
            )
            for check in definition["metric_tests"]
        ),
    )


def _run_metric(
    definition: fuji_checks.MetricDefinition,
    runner: fuji_checks.Runner,
    supplied: PreparedInput,
    metadata: FujiMetadata,
    blocked: dict[str, Diagnostic],
) -> tuple[MetricResult, tuple[CheckResult, ...]]:
    """Run available checks with F-UJI's scoring."""
    if len(blocked) == len(definition["metric_tests"]):
        return _unmeasured(definition, issues=blocked)
    result = runner.evaluate(
        definition["metric_identifier"],
        metadata.fields,
        metadata_url=supplied.request.metadata_url,
        blocked=blocked,
    )
    return result.metric, result.tests


def _assess_metric(
    definition: fuji_checks.MetricDefinition,
    runner: fuji_checks.Runner,
    metadata: FujiMetadata,
    evidence: dict[str, tuple[EvidenceRef, ...]],
    *,
    supplied: PreparedInput,
) -> tuple[MetricResult, tuple[CheckResult, ...]]:
    """Run supported F-UJI checks, isolating evaluator failures from input errors."""
    identifier = definition["metric_identifier"]
    registration = fuji_checks.EVALUATORS.get(identifier)
    if registration is None:
        return _unmeasured(definition)
    fields_by_check = {}
    blocked = {}
    partial: dict[str, Diagnostic] = {}
    for check_definition in definition["metric_tests"]:
        check_id = check_definition["metric_test_identifier"]
        fields = registration.check_evidence.get(
            check_id,
            (registration.check_fields[check_id],)
            if check_id in registration.check_fields
            else registration.fields,
        )
        fields_by_check[check_id] = fields
        if check_id in registration.unsupported_checks:
            continue
        issue = (
            supplied.invalid.get("metadata_url")
            if fields == ("metadata_url",)
            else supplied.invalid.get("metadata")
            or supplied.invalid.get("subject")
            or supplied.invalid.get("metadata_format")
        )
        if issue is not None:
            blocked[check_id] = issue
        elif metadata.diagnostics and fields != ("metadata_url",):
            # A skipped source may contain missing evidence. Preserve conclusive
            # passes, but do not treat an incomplete harvest as proof of absence.
            partial[check_id] = metadata.diagnostics[0]
    try:
        metric, results = _run_metric(definition, runner, supplied, metadata, blocked)
        inconclusive = {
            check.id: partial[check.id]
            for check in results
            if check.id in partial and check.outcome != "pass"
        }
        if inconclusive:
            metric, results = _run_metric(
                definition, runner, supplied, metadata, {**blocked, **inconclusive}
            )
    except (InputError, ProfileError):
        raise
    except Exception:
        logging.getLogger(__name__).debug("F-UJI evaluation failed", exc_info=True)
        return _unmeasured(definition, outcome="error")
    checks = []
    for check in results:
        fields = fields_by_check[check.id]
        refs = dict.fromkeys(ref for field in fields for ref in evidence.get(field, ()))
        checks.append(check.model_copy(update={"evidence": tuple(refs)}))
    return metric, tuple(checks)


class FujiAdapter:
    id = "fuji"
    version = "1.0.0"
    definitions: tuple[ResourceRef, ...] = (
        *fuji_checks.REFERENCES,
        ResourceRef(
            id="fuji:creativeworks",
            version="3.5.1",
            kind="reference",
            format="json",
            digest="13a7713c5f401c08b0296eadb771d4d5925ce01093aa90d15eedc44c125cc2f0",
        ),
    )

    def assess(
        self, request: AssessmentInput | Mapping[str, object], profile: LoadedProfile
    ) -> AssessmentResult:
        """Use pinned native readers and run the supported F-UJI metrics."""
        supplied = prepare_input(request)
        request = supplied.request
        input_digest = supplied.digest
        metadata = FujiMetadata({})
        evidence = {}
        if not supplied.invalid.keys() & {"metadata", "subject", "metadata_format"}:
            try:
                metadata = prepare_metadata(request, profile)
                evidence = _evidence(supplied, metadata.sources)
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
                    "F-UJI metadata reader failed", exc_info=True
                )
                supplied.invalid["metadata"] = Diagnostic(
                    code="metadata_reader_error",
                    message="F-UJI could not interpret the supplied metadata.",
                    location="/metadata",
                )
        if request.metadata_url:
            evidence["metadata_url"] = (
                EvidenceRef(
                    resource="assessment_input",
                    digest=input_digest,
                    location="/metadata_url",
                ),
            )
        runner = fuji_checks.Runner(profile.resources)
        metrics = []
        tests: list[CheckResult] = []
        for definition in runner.metrics.values():
            metric, checks = _assess_metric(
                definition,
                runner,
                metadata,
                evidence,
                supplied=supplied,
            )
            metrics.append(metric)
            tests.extend(checks)
        diagnostics = [*supplied.invalid.values(), *metadata.diagnostics]
        return AssessmentResult(
            profile=profile.info,
            provenance=Provenance(
                engine_version=version("fair-offline-assessor"),
                processor_version=version("PyLD"),
                input_digest=input_digest,
                resources=tuple(
                    ResourceRef.model_validate(
                        ref.model_dump(include=set(ResourceRef.model_fields))
                    )
                    for ref in profile.references
                ),
            ),
            metrics=tuple(metrics),
            tests=tuple(tests),
            diagnostics=tuple(diagnostics),
            raw=runner.native_results,
        )
