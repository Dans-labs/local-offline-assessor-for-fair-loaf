import logging
from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace
from typing import cast

import yaml
from pydantic import JsonValue

from fair_offline_assessor._vendor.fuji.v3_5_1.evaluators import (
    fair_evaluator_minimal_metadata as core_metadata,
)
from fair_offline_assessor.models import ProfileError

_METRICS_DIGEST = "99c65ad9202a1f1dc8178c3457347f1a533b78329d3b53814687382874fad18a"


def evaluate_core_metadata(
    metadata: Mapping[str, JsonValue], *, definitions: bytes
) -> dict[str, JsonValue]:
    """Run pinned F2 checks on prepared F-UJI fields and return native output."""
    if sha256(definitions).hexdigest() != _METRICS_DIGEST:
        raise ProfileError("unsupported_definitions", "Unsupported F-UJI definitions")
    metric = next(
        item
        for item in yaml.safe_load(definitions)["metrics"]
        if item["metric_identifier"] == "FsF-F2-01M"
    )
    metric["agnostic_identifier"] = metric["metric_identifier"]
    for test in metric["metric_tests"]:
        test["agnostic_test_identifier"] = test["metric_test_identifier"]

    # Upstream checks field names, so empty values must not reach the evaluator.
    prepared = {
        key: deepcopy(value)
        for key, value in metadata.items()
        if value is not None
        and (not isinstance(value, str) or value.strip())
        and value not in ([], {})
    }
    context = SimpleNamespace(
        isDebug=False,
        count=0,
        logger=logging.getLogger(__name__),
        LOG_SUCCESS=25,
        METRICS={metric["metric_identifier"]: metric},
        metadata_merged=prepared,
        metadata_sources=[],
        landing_url=None,
    )
    evaluator = core_metadata.FAIREvaluatorCoreMetadata(context)  # type: ignore[no-untyped-call]
    return cast("dict[str, JsonValue]", evaluator.getResult())  # type: ignore[no-untyped-call]
