from pydantic import Field

from fair_offline_assessor.models.v1 import AssessmentInput


class ChampionInput(AssessmentInput):
    """Champion evidence; the target identifier is independent of metadata IDs."""

    target_identifier: str | None = Field(default=None, strict=True)
