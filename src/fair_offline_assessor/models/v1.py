from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from packaging.specifiers import SpecifierSet
from packaging.version import Version
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

Points = Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Outcome = Literal["pass", "partial", "fail", "indeterminate", "not_applicable", "error"]
JsonObject = dict[str, JsonValue]


class InputError(ValueError):
    def __init__(self, code: str, message: str, location: str | None = None) -> None:
        """Record an input error code and optional location."""
        self.code, self.location = code, location
        super().__init__(message)


class ProfileError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        """Record a profile error code and message."""
        self.code = code
        super().__init__(message)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def relative_path(value: str) -> str:
    """Accept only normalized paths within a resource package."""
    path = PurePosixPath(value)
    if (
        not path.parts
        or path.is_absolute()
        or ".." in path.parts
        or str(path) != value
        or any(character in value for character in ("\\", ":", "\x00"))
    ):
        raise ValueError("Use a relative resource path without traversal")
    return value


ResourcePath = Annotated[str, AfterValidator(relative_path)]


class ResourceSelection(Model):
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)


class ResourceRef(ResourceSelection):
    kind: Literal["context", "mapping", "reference"]
    format: Literal["json", "xml", "yaml"] = "json"
    digest: Digest


class ResourceRecord(ResourceRef):
    path: ResourcePath
    license: str = Field(min_length=1)
    source: dict[str, str]
    aliases: tuple[str, ...] = ()


class ProfileIdentity(Model):
    id: str = Field(pattern=r"^(?:[a-z][a-z0-9._-]*:)?[a-z][a-z0-9._-]*$")
    version: str
    title: str
    adapter: str = Field(pattern=r"^[a-z][a-z0-9._-]*$")
    engine_requires: str = Field(min_length=1)
    adapter_version: str

    @field_validator("version", "adapter_version")
    @classmethod
    def valid_version(cls, value: str) -> str:
        """Require a normalized PEP 440 version."""
        if str(Version(value)) != value:
            raise ValueError("Use a normalized version, such as 1.0.0")
        return value

    @field_validator("engine_requires")
    @classmethod
    def valid_requirement(cls, value: str) -> str:
        """Check engine version requirement syntax."""
        SpecifierSet(value)
        return value


class Profile(ProfileIdentity):
    schema_version: Literal[1]
    resources: tuple[ResourceSelection, ...]
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def unique_resources(self) -> Self:
        """Reject duplicate resource identifiers."""
        identifiers = [resource.id for resource in self.resources]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Duplicate resource identifier")
        return self


class ProfileInfo(ProfileIdentity):
    digest: Digest


class AssessmentInput(Model):
    metadata: JsonObject | list[JsonObject]
    subject: str | None = None
    metadata_url: str | None = None
    local_contexts: dict[str, JsonObject] = Field(default_factory=dict)


class EvidenceRef(Model):
    resource: str
    digest: Digest
    location: str
    subject: str | None = None


class Score(Model):
    observed_earned: Points
    maximum: Points
    complete: bool
    percent: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)] | None = None

    @model_validator(mode="after")
    def consistent_score(self) -> Self:
        """Validate points and derive the percentage when the score is complete."""
        if self.observed_earned > self.maximum:
            raise ValueError("Earned points exceed the maximum")
        percent = (
            round(100 * self.observed_earned / self.maximum, 2)
            if self.complete and self.maximum
            else None
        )
        if "percent" in self.model_fields_set and self.percent != percent:
            raise ValueError("Percentage differs from the score")
        object.__setattr__(self, "percent", percent)
        return self


class MaturityLevel(Model):
    scheme: str = Field(min_length=1)
    value: int | str
    label: str | None = None


class Finding(Model):
    id: str = Field(min_length=1)
    outcome: Outcome
    score: Score | None = None
    level: MaturityLevel | None = None


class CheckResult(Finding):
    metric: str = Field(min_length=1)
    reason_code: str
    message: str
    evidence: tuple[EvidenceRef, ...] = ()

    @model_validator(mode="after")
    def unmeasured_score(self) -> Self:
        """Keep unmeasured checks distinct from zero-point failures."""
        if (
            self.outcome in {"indeterminate", "error", "not_applicable"}
            and self.score is not None
        ):
            raise ValueError("Unmeasured checks cannot have a score")
        return self


class MetricResult(Finding):
    principles: tuple[str, ...] = Field(min_length=1)


class Coverage(Model):
    evaluated: int = Field(default=0, ge=0)
    indeterminate: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)
    not_applicable: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def consistent_counts(self) -> Self:
        """Require coverage counts to add up to the total."""
        if (
            self.evaluated + self.indeterminate + self.errors + self.not_applicable
            != self.total
        ):
            raise ValueError("Coverage counts do not add up to total")
        return self


class Diagnostic(Model):
    code: str
    message: str
    location: str | None = None


class Provenance(Model):
    engine_version: str
    processor_version: str
    input_digest: Digest
    resources: tuple[ResourceRef, ...]


class AssessmentResult(Model):
    schema_version: Literal[1] = 1
    status: Literal["completed", "completed_with_errors"] = "completed"
    profile: ProfileInfo
    provenance: Provenance
    tests: tuple[CheckResult, ...]
    metrics: tuple[MetricResult, ...]
    principle_scores: dict[Literal["F", "A", "I", "R"], Score] = Field(
        default_factory=dict
    )
    overall_score: Score | None = None
    coverage: Coverage = Field(default_factory=Coverage)
    diagnostics: tuple[Diagnostic, ...] = ()

    @model_validator(mode="after")
    def consistent_findings(self) -> Self:
        """Validate relationships and derive coverage and execution status."""
        metrics = {metric.id for metric in self.metrics}
        if len(metrics) != len(self.metrics) or len(
            {test.id for test in self.tests}
        ) != len(self.tests):
            raise ValueError("Duplicate finding identifier")
        if any(test.metric not in metrics for test in self.tests):
            raise ValueError("Check refers to an unknown metric")
        if not self.metrics and (
            self.overall_score is not None or self.principle_scores
        ):
            raise ValueError("An empty assessment cannot have summary scores")
        coverage = Coverage(
            evaluated=sum(
                test.outcome in {"pass", "partial", "fail"} for test in self.tests
            ),
            indeterminate=sum(test.outcome == "indeterminate" for test in self.tests),
            errors=sum(test.outcome == "error" for test in self.tests),
            not_applicable=sum(test.outcome == "not_applicable" for test in self.tests),
            total=len(self.tests),
        )
        status = (
            "completed_with_errors"
            if coverage.errors
            or any(metric.outcome == "error" for metric in self.metrics)
            else "completed"
        )
        if "coverage" in self.model_fields_set and self.coverage != coverage:
            raise ValueError("Coverage differs from the reported checks")
        if "status" in self.model_fields_set and self.status != status:
            raise ValueError("Status differs from the reported errors")
        object.__setattr__(self, "coverage", coverage)
        object.__setattr__(self, "status", status)
        return self
