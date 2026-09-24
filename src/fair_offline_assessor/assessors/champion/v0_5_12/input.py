import json
from collections.abc import Mapping
from dataclasses import dataclass

from fair_offline_assessor._input import digest_input, prepare_input
from fair_offline_assessor.models import AssessmentInput, ChampionInput, Diagnostic


@dataclass(frozen=True)
class PreparedChampionInput:
    request: ChampionInput
    digest: str
    invalid: dict[str, Diagnostic]


def prepare_champion_input(
    request: AssessmentInput | Mapping[str, object],
) -> PreparedChampionInput:
    """Retain usable evidence and hash the full request, including invalid fields."""
    supplied = (
        request.model_dump() if isinstance(request, AssessmentInput) else dict(request)
    )
    original = ChampionInput(metadata={}).model_dump() | supplied
    base = prepare_input(
        {key: value for key, value in original.items() if key != "target_identifier"}
    )
    invalid = dict(base.invalid)
    target = None
    try:
        target_input = ChampionInput.model_validate(
            {"metadata": {}, "target_identifier": original["target_identifier"]}
        )
        json.dumps(target_input.target_identifier, ensure_ascii=False).encode()
        target = target_input.target_identifier
    except ValueError:
        invalid["target_identifier"] = Diagnostic(
            code="invalid_target_identifier",
            message="Target identifier must be a valid Unicode string or null.",
            location="/target_identifier",
        )
    validated = ChampionInput(**base.request.model_dump(), target_identifier=target)
    return PreparedChampionInput(validated, digest_input(original), invalid)
