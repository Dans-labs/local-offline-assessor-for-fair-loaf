import json
import logging
from hashlib import sha256
from importlib.metadata import version
from typing import Literal, NotRequired, TypedDict, cast

import yaml

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


class _Check(TypedDict):
    metric_test_identifier: str
    metric_test_name: str


class _Metric(TypedDict):
    metric_identifier: str
    fair_principle: NotRequired[str]
    metric_tests: list[_Check]


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
) -> tuple[EvidenceRef, ...]:
    """Locate mapped values in the prepared graph, including linked records."""
    digest = _digest(dataset.graph)
    paths = dict.fromkeys(path for paths in sources.values() for path in paths)
    return tuple(
        EvidenceRef(
            resource="prepared_metadata",
            digest=digest,
            location=path,
            subject=cast("str", dataset.graph[int(path.split("/")[1])]["@id"]),
        )
        for path in paths
    )


def _unmeasured(
    definition: _Metric, *, outcome: Literal["indeterminate", "error"] = "indeterminate"
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
    definition: _Metric,
    profile: LoadedProfile,
    dataset: SelectedDataset,
    metadata: FujiMetadata,
) -> tuple[MetricResult, tuple[CheckResult, ...]]:
    """Run supported F-UJI checks, isolating evaluator failures from input errors."""
    identifier = definition["metric_identifier"]
    if identifier not in {"FsF-F2-01M", "FsF-R1.1-01M"}:
        return _unmeasured(definition)
    definitions = profile.resources[_fuji.DEFINITION.id]
    fields = ("license",) if identifier == "FsF-R1.1-01M" else _fuji.CORE_FIELDS
    sources = {
        field: paths for field, paths in metadata.sources.items() if field in fields
    }
    evidence = _evidence(dataset, sources)
    try:
        if identifier == "FsF-F2-01M":
            evaluation = _fuji.evaluate_core_metadata(
                metadata.fields, definitions=definitions
            )
        else:
            evaluation = _fuji.evaluate_license(
                metadata.fields,
                definitions=definitions,
                licenses=profile.resources[_fuji.LICENSES.id],
            )
    except (InputError, ProfileError):
        raise
    except Exception:
        logging.getLogger(__name__).debug("F-UJI evaluation failed", exc_info=True)
        return _unmeasured(definition, outcome="error")
    return evaluation.metric, tuple(
        check.model_copy(update={"evidence": evidence}) for check in evaluation.tests
    )


class FujiAdapter:
    id = "fuji"
    version = "1.0.0"
    definitions: tuple[ResourceRef, ...] = (_fuji.DEFINITION, _fuji.LICENSES)

    def assess(
        self, request: AssessmentInput, profile: LoadedProfile
    ) -> AssessmentResult:
        """Prepare supplied JSON-LD and run the supported F-UJI metrics."""
        input_digest = _digest(request.model_dump(mode="json"))
        dataset = select_dataset(request, profile)
        metadata = prepare_metadata(dataset)
        definitions = profile.resources[_fuji.DEFINITION.id]
        inventory = cast("list[_Metric]", yaml.safe_load(definitions)["metrics"])
        metrics = []
        tests: list[CheckResult] = []
        for definition in inventory:
            metric, checks = _assess_metric(definition, profile, dataset, metadata)
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
