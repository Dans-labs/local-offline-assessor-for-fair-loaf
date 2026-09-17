import json
import logging
from hashlib import sha256
from importlib.metadata import version
from typing import Literal, cast

from fair_offline_assessor import _fuji
from fair_offline_assessor._fuji_metadata import FujiMetadata, prepare_metadata
from fair_offline_assessor._metadata import SelectedDataset, select_dataset
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


def _digest(value: object) -> str:
    """Hash deterministic JSON, rejecting non-finite numbers and invalid text."""
    try:
        content = json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    except ValueError as exc:
        raise InputError(
            "invalid_json", "Evidence must contain valid, finite JSON values"
        ) from exc
    return sha256(content).hexdigest()


def _evidence(
    dataset: SelectedDataset, sources: dict[str, tuple[str, ...]]
) -> dict[str, tuple[EvidenceRef, ...]]:
    """Locate mapped values in the prepared graph, including linked records."""
    digest = _digest(dataset.graph)
    return {
        field: tuple(
            EvidenceRef(
                resource="prepared_metadata",
                digest=digest,
                location=path,
                subject=cast("str", dataset.graph[int(path.split("/")[1])]["@id"]),
            )
            for path in dict.fromkeys(paths)
        )
        for field, paths in sources.items()
    }


def _unmeasured(
    definition: _fuji.MetricDefinition,
    *,
    outcome: Literal["indeterminate", "error"] = "indeterminate",
) -> tuple[MetricResult, tuple[CheckResult, ...]]:
    """Keep unavailable checks and execution errors visible without assigning points."""
    identifier = definition["metric_identifier"]
    # F-UJI metrics 0.8 omits fair_principle on its F4 metric.
    principle = definition.get("fair_principle", identifier.split("-")[1])
    reason = "evaluator_error" if outcome == "error" else "not_implemented"
    message = (
        "F-UJI could not complete this check."
        if outcome == "error"
        else "This check is not implemented yet."
    )
    return (
        MetricResult(id=identifier, principles=(principle,), outcome=outcome),
        tuple(
            CheckResult(
                id=check["metric_test_identifier"],
                metric=identifier,
                outcome=outcome,
                reason_code=reason,
                message=message,
            )
            for check in definition["metric_tests"]
        ),
    )


def _assess_metric(
    definition: _fuji.MetricDefinition,
    runner: _fuji.Runner,
    metadata: FujiMetadata,
    evidence: dict[str, tuple[EvidenceRef, ...]],
    *,
    metadata_url: str | None,
) -> tuple[MetricResult, tuple[CheckResult, ...]]:
    """Run supported F-UJI checks, isolating evaluator failures from input errors."""
    identifier = definition["metric_identifier"]
    registration = _fuji.EVALUATORS.get(identifier)
    if registration is None:
        return _unmeasured(definition)
    try:
        evaluation = runner.evaluate(
            identifier, metadata.fields, metadata_url=metadata_url
        )
    except (InputError, ProfileError):
        raise
    except Exception:
        logging.getLogger(__name__).debug("F-UJI evaluation failed", exc_info=True)
        return _unmeasured(definition, outcome="error")
    checks = []
    for check in evaluation.tests:
        fields = registration.fields
        if check.id in registration.check_fields:
            fields = (registration.check_fields[check.id],)
        refs = dict.fromkeys(ref for field in fields for ref in evidence.get(field, ()))
        checks.append(check.model_copy(update={"evidence": tuple(refs)}))
    return evaluation.metric, tuple(checks)


class FujiAdapter:
    id = "fuji"
    version = "1.0.0"
    definitions: tuple[ResourceRef, ...] = _fuji.REFERENCES

    def assess(
        self, request: AssessmentInput, profile: LoadedProfile
    ) -> AssessmentResult:
        """Prepare supplied JSON-LD and run the supported F-UJI metrics."""
        input_digest = _digest(request.model_dump(mode="json"))
        dataset = select_dataset(request, profile)
        metadata = prepare_metadata(dataset)
        evidence = _evidence(dataset, metadata.sources)
        if request.metadata_url:
            evidence["metadata_url"] = (
                EvidenceRef(
                    resource="assessment_input",
                    digest=input_digest,
                    location="/metadata_url",
                ),
            )
        runner = _fuji.Runner(profile.resources)
        metrics = []
        tests: list[CheckResult] = []
        for definition in runner.metrics.values():
            metric, checks = _assess_metric(
                definition,
                runner,
                metadata,
                evidence,
                metadata_url=request.metadata_url,
            )
            metrics.append(metric)
            tests.extend(checks)
        diagnostics = [
            Diagnostic(
                code="unmapped_term", message=f"No F-UJI field mapping for {term}."
            )
            for term in metadata.unmapped
        ]
        if request.captures:
            diagnostics.append(
                Diagnostic(
                    code="captures_not_supported",
                    message="Captured HTTP evidence is not assessed yet.",
                )
            )
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
        )
