import logging
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
from types import SimpleNamespace
from typing import Literal, NotRequired, TypedDict, cast

import yaml
from pydantic import JsonValue

from fair_offline_assessor._vendor.fuji.v3_5_1.evaluators import (
    fair_evaluator_data_access_level as access_metadata,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.evaluators import (
    fair_evaluator_data_content_metadata as data_content,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.evaluators import (
    fair_evaluator_data_identifier_included as data_links,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.evaluators import (
    fair_evaluator_data_provenance as provenance,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.evaluators import (
    fair_evaluator_file_format as file_formats,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.evaluators import (
    fair_evaluator_license as license_metadata,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.evaluators import (
    fair_evaluator_minimal_metadata as core_metadata,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.evaluators import (
    fair_evaluator_related_resources as related_resources,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.evaluators import (
    fair_evaluator_retrievable_metadata_data as retrieval,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.evaluators import (
    fair_evaluator_standardised_protocol_auth_metadata_data as authentication,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.evaluators import (
    fair_evaluator_standardised_protocol_metadata_data as protocols,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.evaluators import (
    fair_evaluator_unique_identifier_metadata as identifiers,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.evaluators.fair_evaluator import (
    FAIREvaluator,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.helper.identifier_helper import (
    IdentifierHelper,
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
PROTOCOLS = ResourceRef(
    id="fuji:protocols",
    version="3.5.1",
    kind="reference",
    format="yaml",
    digest="8e7a8250868b2818f14f523d07438ce0b751d4e1af797a4f3f0550148aab1e4e",
)
IDENTIFIERS = ResourceRef(
    id="fuji:identifiers",
    version="3.5.1",
    kind="reference",
    format="yaml",
    digest="2625067ce4fef9fab00ad7d5a7568938a2b2e1573d60a3fd5657a2d60d1b068b",
)
FILE_FORMATS = ResourceRef(
    id="fuji:file-formats",
    version="3.5.1",
    kind="reference",
    format="yaml",
    digest="f60f8c8faf96318e9782a0d098610a2c399d7c07d32e23c089c0d3996790b925",
)


@dataclass(frozen=True)
class MetricEvaluation:
    metric: MetricResult
    tests: tuple[CheckResult, ...]
    native: dict[str, JsonValue]


class CheckDefinition(TypedDict):
    metric_test_identifier: str
    metric_test_name: str
    agnostic_test_identifier: NotRequired[str]


class MetricDefinition(TypedDict):
    metric_identifier: str
    fair_principle: NotRequired[str]
    metric_tests: list[CheckDefinition]
    agnostic_identifier: NotRequired[str]


@dataclass(frozen=True)
class Evaluator:
    implementation: type[FAIREvaluator]
    fields: tuple[str, ...]
    resources: tuple[ResourceRef, ...] = ()
    # Per-check fields must be supplied and provide that check's evidence.
    check_fields: Mapping[str, str] = field(default_factory=dict)
    check_evidence: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


EVALUATORS = {
    "FsF-R1.3-02D": Evaluator(
        file_formats.FAIREvaluatorFileFormat,
        (),
        (FILE_FORMATS,),
        {"FsF-R1.3-02D-1": "file_formats"},
    ),
    "FsF-R1-01M": Evaluator(
        data_content.FAIREvaluatorDataContentMetadata,
        (),
        check_evidence={
            "FsF-R1-01M-1": ("object_type",),
            "FsF-R1-01M-2": (
                "object_content_identifier",
                "distribution_details",
                "object_size",
                "object_format",
            ),
            "FsF-R1-01M-3": ("measured_variable", "object_content_identifier"),
        },
    ),
    "FsF-R1.2-01M": Evaluator(
        provenance.FAIREvaluatorDataProvenance,
        (*Mapper.PROVENANCE_MAPPING.value, "related_resources"),
        check_evidence={"FsF-R1.2-01M-2": ("provenance_namespaces",)},
    ),
    "FsF-I3-01M": Evaluator(
        related_resources.FAIREvaluatorRelatedResources,
        ("related_resources",),
        (IDENTIFIERS,),
    ),
    "FsF-F1-01MD": Evaluator(
        identifiers.FAIREvaluatorUniqueIdentifierMetadata,
        (),
        (IDENTIFIERS,),
        {
            "FsF-F1-01MD-1": "metadata_url",
            "FsF-F1-01MD-2": "object_content_identifier",
        },
    ),
    "FsF-F2-01M": Evaluator(core_metadata.FAIREvaluatorCoreMetadata, CORE_FIELDS),
    "FsF-F3-01M": Evaluator(
        data_links.FAIREvaluatorDataIdentifierIncluded, ("object_content_identifier",)
    ),
    "FsF-R1.1-01M": Evaluator(
        license_metadata.FAIREvaluatorLicense, ("license",), (LICENSES,)
    ),
    "FsF-A1-01M": Evaluator(
        access_metadata.FAIREvaluatorDataAccessLevel,
        ("access_level", "access_free"),
        (LICENSES, ACCESS_RIGHTS),
    ),
    "FsF-A1.1-01MD": Evaluator(
        protocols.FAIREvaluatorStandardisedProtocolMetadata,
        (),
        (PROTOCOLS,),
        {
            "FsF-A1.1-01MD-1": "metadata_url",
            "FsF-A1.1-01MD-2": "object_content_identifier",
        },
    ),
    "FsF-A1.2-01MD": Evaluator(
        authentication.FAIREvaluatorStandardisedProtocolAuthentication,
        (),
        (PROTOCOLS,),
        {
            "FsF-A1.2-01MD-1": "metadata_url",
            "FsF-A1.2-01MD-2": "object_content_identifier",
        },
    ),
}
REFERENCES = (
    DEFINITION,
    *{
        ref.id: ref for evaluator in EVALUATORS.values() for ref in evaluator.resources
    }.values(),
)


class Runner:
    def __init__(self, resources: Mapping[str, bytes]) -> None:
        """Load the pinned definitions and catalogues once for this assessment."""
        loaded = {}
        for reference in REFERENCES:
            content = resources.get(reference.id)
            if content is None or sha256(content).hexdigest() != reference.digest:
                raise ProfileError(
                    "unsupported_definitions",
                    f"Unsupported F-UJI resource: {reference.id}",
                )
            loaded[reference.id] = yaml.safe_load(content)
        self.metrics = {
            metric["metric_identifier"]: metric
            for metric in cast(
                "list[MetricDefinition]", loaded[DEFINITION.id]["metrics"]
            )
        }
        licences = loaded[LICENSES.id]
        self._resources = {
            LICENSES.id: {
                "SPDX_LICENSES": licences,
                "SPDX_LICENSE_NAMES": [item["name"] for item in licences],
            },
            ACCESS_RIGHTS.id: {"ACCESS_RIGHTS": loaded[ACCESS_RIGHTS.id]},
            PROTOCOLS.id: {"STANDARD_PROTOCOLS": loaded[PROTOCOLS.id]},
            FILE_FORMATS.id: {
                name: {
                    mime: entry["domain"][0] if entry.get("domain") else None
                    for entry in loaded[FILE_FORMATS.id].values()
                    if reason in entry["reason"]
                    for mime in entry["mime"]
                }
                for name, reason in (
                    ("SCIENCE_FILE_FORMATS", "scientific format"),
                    ("LONG_TERM_FILE_FORMATS", "long term format"),
                    ("OPEN_FILE_FORMATS", "open format"),
                )
            },
            IDENTIFIERS.id: {
                "IDENTIFIERS_ORG_DATA": {
                    item["prefix"]: {
                        "pattern": item["pattern"],
                        "url_pattern": item["resources"][0]["urlPattern"],
                    }
                    for item in loaded[IDENTIFIERS.id]["payload"]["namespaces"]
                }
            },
        }

    def _context(self, identifier: str, **evidence: object) -> SimpleNamespace:
        """Give each evaluator private definitions, metadata and catalogues."""
        metric = deepcopy(self.metrics[identifier])
        metric["agnostic_identifier"] = identifier
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

    def evaluate(
        self,
        identifier: str,
        metadata: Mapping[str, JsonValue],
        *,
        metadata_url: str | None = None,
    ) -> MetricEvaluation:
        """Run a registered metadata evaluator with its required resources."""
        registration = EVALUATORS[identifier]
        # Empty values must not satisfy upstream checks that only inspect field names.
        prepared = {
            key: value
            for key, value in metadata.items()
            if value is not None
            and (not isinstance(value, str) or value.strip())
            and value not in ([], {})
        }
        state: dict[str, object] = {
            "metadata_merged": prepared,
            "related_resources": prepared.get("related_resources", []),
            "namespace_uri": prepared.get("provenance_namespaces", []),
            "metadata_sources": [],
            "landing_url": None,
            "origin_url": metadata_url,
            "id": metadata_url,
            "pid_url": None,
            "content_identifier": {
                item["url"]: {
                    **item,
                    "claimed_type": item.get("type"),
                    "claimed_size": item.get("size"),
                    "claimed_service": item.get("service"),
                }
                for item in cast(
                    "list[dict[str, JsonValue]]",
                    prepared.get("object_content_identifier", []),
                )
            },
            # The verified definition pin selects metrics 0.8.
            "metric_helper": SimpleNamespace(get_metric_version=lambda: 0.8),
            # Metrics 0.8 checks type presence, not the legacy type whitelist.
            "VALID_RESOURCE_TYPES": (),
        }
        for resource in registration.resources:
            state.update(self._resources[resource.id])
        context = self._context(identifier, **state)
        if identifier == "FsF-R1.3-02D":
            # Only declared formats are available without captured content.
            context.content_identifier = {}
            context.metadata_merged["object_content_identifier"] = (
                context.metadata_merged.get("file_formats", [])
            )
        if identifier == "FsF-F1-01MD":
            for item in context.content_identifier.values():
                helper = IdentifierHelper(  # type: ignore[no-untyped-call]
                    item["url"], identifiers_org_data=context.IDENTIFIERS_ORG_DATA
                )
                item["scheme"] = helper.preferred_schema
        checks = context.METRICS[identifier]["metric_tests"]
        available = {**prepared, "metadata_url": metadata_url}
        missing = {
            check
            for check, required in registration.check_fields.items()
            if not available.get(required)
        }
        context.METRICS[identifier]["metric_tests"] = [
            check for check in checks if check["metric_test_identifier"] not in missing
        ]
        evaluator = registration.implementation(context)
        return _evaluate(evaluator, checks=checks)

    def evaluate_retrievability(
        self,
        *,
        metadata: Sequence[Mapping[str, JsonValue]] | None = None,
        data: Mapping[str, Mapping[str, JsonValue]] | None = None,
    ) -> MetricEvaluation:
        """Run retrieval checks on bound observations; None means missing evidence.

        Empty collections mean an observed failure. Metadata needs a successful GET
        with a parsed body describing the subject.
        """
        identifier = "FsF-A1-02MD"
        context = self._context(
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
    evaluator: FAIREvaluator, *, checks: Sequence[CheckDefinition]
) -> MetricEvaluation:
    """Run F-UJI and convert its checks and metric result."""
    native = cast("dict[str, JsonValue]", evaluator.getResult())  # type: ignore[no-untyped-call]
    identifier = cast("str", native["metric_identifier"])
    metric = evaluator.fuji.METRICS[identifier]
    results = []
    for test in checks:
        check_id = test["metric_test_identifier"]
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
