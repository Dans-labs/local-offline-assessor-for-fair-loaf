import json
from pathlib import Path

from fair_offline_assessor.models.v1 import Profile, AssessmentResult

schema_dir = Path("src/fair_offline_assessor/resources/schemas")

for name, model, mode in [
    ("profile", Profile, "validation"),
    ("result", AssessmentResult, "serialization"),
]:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **model.model_json_schema(mode=mode),
    }

    path = schema_dir / f"{name}-v1.json"
    path.write_text(json.dumps(schema, indent=2) + "\n")
    print(f"Updated {path}")
