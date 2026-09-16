import logging
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from types import SimpleNamespace
from typing import Literal, cast

import yaml
from pydantic import JsonValue

from fair_offline_assessor._vendor.fuji.v3_5_1.evaluators import (
    fair_evaluator_data_access_level as access_metadata,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.evaluators import (
    fair_evaluator_license as license_metadata,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.evaluators import (
    fair_evaluator_minimal_metadata as core_metadata,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.evaluators import (
    fair_evaluator_retrievable_metadata_data as retrieval,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.evaluators.fair_evaluator import (
    FAIREvaluator,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.helper.metadata_mapper import Mapper
from fair_offline_assessor.models import (
    CheckResult,
    MaturityLevel,
    MetricResult,
    ProfileError,
    ResourceRef,
    Score,
)

DEFINITION = ResourceRef(
    id="fuji:metrics",
    version="3.5.1",
    kind="reference",
    format="yaml",
    digest="99c65ad9202a1f1dc8178c3457347f1a533b78329d3b53814687382874fad18a",
)
LICENSES = ResourceRef(
    id="fuji:licenses",
    version="3.5.1",
    kind="reference",
    format="yaml",
    digest="38f58300a320075e072f2010e00d4db29cae1abe303c93695c2f13c9541edbb4",
)
CORE_FIELDS: tuple[str, ...] = tuple(Mapper.REQUIRED_CORE_METADATA.value)
ACCESS_RIGHTS = ResourceRef(
    id="fuji:access-rights",
    version="3.5.1",
    kind="reference",
    format="yaml",
    digest="2b6f32c7f0d04090f9df8766f9a175107e116fa1ce751defb4dcb007cad5cfab",
)


@dataclass(frozen=True)
class MetricEvaluation:
    metric: MetricResult
    tests: tuple[CheckResult, ...]
    native: dict[str, JsonValue]


def _context(
    definitions: bytes, identifier: str, **evidence: object
) -> SimpleNamespace:
    """Load the pinned metric into independent evaluation state."""
    if sha256(definitions).hexdigest() != DEFINITION.digest:
        raise ProfileError("unsupported_definitions", "Unsupported F-UJI definitions")
    metric = next(
        item
        for item in yaml.safe_load(definitions)["metrics"]
        if item["metric_identifier"] == identifier
    )
    metric["agnostic_identifier"] = metric["metric_identifier"]
    for test in metric["metric_tests"]:
        test["agnostic_test_identifier"] = test["metric_test_identifier"]
    return SimpleNamespace(
        isDebug=False,
        count=0,
        logger=logging.getLogger(__name__),
        LOG_SUCCESS=25,
        METRICS={identifier: metric},
        **deepcopy(evidence),
    )


def evaluate_core_metadata(
    metadata: Mapping[str, JsonValue], *, definitions: bytes
) -> MetricEvaluation:
    """Run pinned F2 checks on prepared F-UJI fields."""
    # Upstream checks field names, so empty values must not reach the evaluator.
    prepared = {
        key: value
        for key, value in metadata.items()
        if value is not None
        and (not isinstance(value, str) or value.strip())
        and value not in ([], {})
    }
    identifier = "FsF-F2-01M"
    context = _context(
        definitions,
        identifier,
        metadata_merged=prepared,
        metadata_sources=[],
        landing_url=None,
    )
    evaluator = core_metadata.FAIREvaluatorCoreMetadata(context)  # type: ignore[no-untyped-call]
    return _evaluate(evaluator, checks=context.METRICS[identifier]["metric_tests"])


def _license_catalogue(licenses: bytes) -> list[dict[str, JsonValue]]:
    """Load the pinned licence catalogue for licence and access checks."""
    if sha256(licenses).hexdigest() != LICENSES.digest:
        raise ProfileError("unsupported_definitions", "Unsupported F-UJI licences")
    return cast("list[dict[str, JsonValue]]", yaml.safe_load(licenses))


def evaluate_license(
    metadata: Mapping[str, JsonValue], *, definitions: bytes, licenses: bytes
) -> MetricEvaluation:
    """Run the pinned R1.1 check with F-UJI's bundled licence catalogue."""
    catalogue = _license_catalogue(licenses)
    identifier = "FsF-R1.1-01M"
    context = _context(
        definitions,
        identifier,
        metadata_merged=dict(metadata),
        SPDX_LICENSES=catalogue,
        SPDX_LICENSE_NAMES=[item["name"] for item in catalogue],
    )
    evaluator = license_metadata.FAIREvaluatorLicense(context)  # type: ignore[no-untyped-call]
    return _evaluate(evaluator, checks=context.METRICS[identifier]["metric_tests"])


def evaluate_access(
    metadata: Mapping[str, JsonValue],
    *,
    definitions: bytes,
    licenses: bytes,
    access_rights: bytes,
) -> MetricEvaluation:
    """Run A1 access-information checks against the pinned catalogues."""
    if sha256(access_rights).hexdigest() != ACCESS_RIGHTS.digest:
        raise ProfileError("unsupported_definitions", "Unsupported F-UJI access rights")
    catalogue = _license_catalogue(licenses)
    identifier = "FsF-A1-01M"
    context = _context(
        definitions,
        identifier,
        metadata_merged=dict(metadata),
        SPDX_LICENSES=catalogue,
        SPDX_LICENSE_NAMES=[item["name"] for item in catalogue],
        ACCESS_RIGHTS=yaml.safe_load(access_rights),
        # The verified definition pin selects metrics 0.8.
        metric_helper=SimpleNamespace(get_metric_version=lambda: 0.8),
    )
    evaluator = access_metadata.FAIREvaluatorDataAccessLevel(context)  # type: ignore[no-untyped-call]
    return _evaluate(evaluator, checks=context.METRICS[identifier]["metric_tests"])


def evaluate_retrievability(
    *,
    definitions: bytes,
    metadata: Sequence[Mapping[str, JsonValue]] | None = None,
    data: Mapping[str, Mapping[str, JsonValue]] | None = None,
) -> MetricEvaluation:
    """Run A1 on prepared retrieval evidence; None leaves that check indeterminate.

    The preparer must bind observations to the assessed resource. Empty collections
    mean a completed, unsuccessful observation, not missing or unresolved captures.
    Metadata entries require a successful GET with a parsed body for the subject.
    """
    identifier = "FsF-A1-02MD"
    context = _context(
        definitions,
        identifier,
        metadata_unmerged=metadata if metadata is not None else [],
        content_identifier=data if data is not None else {},
    )
    metric = context.METRICS[identifier]
    available = {
        identifier + suffix
        for suffix, evidence in (("-1", metadata), ("-2", data))
        if evidence is not None
    }
    checks = metric["metric_tests"]
    # Both upstream branches guard their work with isTestDefined().
    metric["metric_tests"] = [
        test for test in checks if test["metric_test_identifier"] in available
    ]
    evaluator = retrieval.FAIREvaluatorMetadataDataRetrievable(context)  # type: ignore[no-untyped-call]
    return _evaluate(evaluator, checks=checks)


def _evaluate(
    evaluator: FAIREvaluator, *, checks: Sequence[Mapping[str, JsonValue]]
) -> MetricEvaluation:
    """Run F-UJI and convert its checks and metric result."""
    native = cast("dict[str, JsonValue]", evaluator.getResult())  # type: ignore[no-untyped-call]
    identifier = cast("str", native["metric_identifier"])
    metric = evaluator.fuji.METRICS[identifier]
    results = []
    for test in checks:
        check_id = cast("str", test["metric_test_identifier"])
        if check_id not in evaluator.metric_tests:
            results.append(
                CheckResult(
                    id=check_id,
                    metric=identifier,
                    outcome="indeterminate",
                    reason_code="missing_evidence",
                    message="No conclusive evidence supplied.",
                )
            )
            continue
        criterion = evaluator.metric_tests[check_id]
        results.append(
            CheckResult(
                id=check_id,
                metric=identifier,
                outcome="pass" if criterion.metric_test_status == "pass" else "fail",
                score=Score(
                    observed_earned=criterion.metric_test_score.earned,
                    maximum=criterion.metric_test_score.total,
                    complete=True,
                ),
                level=MaturityLevel(
                    scheme="fuji", value=criterion.metric_test_maturity
                ),
                reason_code="fuji_result",
                message=criterion.metric_test_name,
            )
        )
    complete = len(evaluator.metric_tests) == len(checks)
    outcome: Literal["pass", "fail", "indeterminate"] = (
        "pass"
        if native["test_status"] == "pass"
        else "fail"
        if complete
        else "indeterminate"
    )
    return MetricEvaluation(
        metric=MetricResult(
            id=identifier,
            principles=(metric["fair_principle"],),
            outcome=outcome,
            score=Score(
                observed_earned=evaluator.score.earned,
                maximum=evaluator.score.total,
                complete=complete,
            ),
            level=MaturityLevel(scheme="fuji", value=evaluator.maturity)
            if complete
            else None,
        ),
        tests=tuple(results),
        native=native,
    )
