# ruff: noqa: INP001
import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import BaseModel
    from pydantic.json_schema import JsonSchemaMode

from fair_offline_assessor.models.v1 import AssessmentResult, Profile


def main() -> None:
    """Export profile input and result output schemas from the models."""
    root = Path(__file__).resolve().parents[2]
    target = root / "src/fair_offline_assessor/resources/schemas"
    target.mkdir(parents=True, exist_ok=True)
    definitions: tuple[tuple[str, type[BaseModel], JsonSchemaMode], ...] = (
        ("profile", Profile, "validation"),
        ("result", AssessmentResult, "serialization"),
    )
    for name, model, mode in definitions:
        schema = model.model_json_schema(mode=mode)
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        version = schema["properties"]["schema_version"]["const"]
        (target / f"{name}-v{version}.json").write_text(
            json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
