# SPDX-FileCopyrightText: 2020 PANGAEA (https://www.pangaea.de/)
# SPDX-License-Identifier: MIT

from dataclasses import asdict, dataclass
from typing import cast

from pydantic import JsonValue


@dataclass
class FAIRResultCommonScore:
    earned: float = 0
    total: float = 0


@dataclass
class FAIRResultEvaluationCriterium:
    metric_test_name: str | None = None
    metric_test_requirements: list[dict[str, JsonValue]] | None = None
    metric_test_score: FAIRResultCommonScore | None = None
    metric_test_maturity: int = 0
    metric_test_status: str = "fail"


@dataclass
class CoreMetadataOutput:
    core_metadata_status: str | None = None
    core_metadata_found: dict[str, JsonValue] | None = None
    core_metadata_source: list[tuple[str, str]] | None = None


@dataclass
class CoreMetadata:
    id: int | None = None
    metric_identifier: str | None = None
    metric_name: str | None = None
    metric_tests: dict[str, FAIRResultEvaluationCriterium] | None = None
    test_status: str = "fail"
    score: FAIRResultCommonScore | None = None
    maturity: int = 0
    output: CoreMetadataOutput | None = None
    test_debug: None = None

    def to_dict(self) -> dict[str, JsonValue]:
        """Export native result fields, excluding internal scoring configuration."""
        return cast("dict[str, JsonValue]", asdict(self))
