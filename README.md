# fair-offline-assessor

A Python library for assessing FAIR principles using metadata you provide.
The library does not resolve URLs or fetch missing evidence.

The current profile is `fusji-offline@3.5.1`. It uses F-UJI 3.5.1 and metrics 0.8.
A profile specifies which assessor and resource versions to use.

## Usage

```python
from fair_offline_assessor import AssessmentInput, assess

request = AssessmentInput(
    metadata={
        "@context": "https://schema.org",
        "@id": "https://example.org/dataset",
        "@type": "Dataset",
        "name": "Soil measurements",
        "description": "Soil measurements collected during a field survey.",
        "creator": "Alice Example",
        "publisher": "Example Archive",
        "datePublished": "2026-01-01",
        "keywords": ["soil"],
    }
)
result = assess(request, profile="fusji-offline@3.5.1")
print(result.model_dump_json(indent=2))
```

Currently, only the two F2 core-metadata checks run. The other 29 checks are
returned as `indeterminate`. Scores are available for F2; there is no overall score.
`result.coverage` reports how many checks ran. HTTP captures are not assessed yet.

A single Schema.org Dataset is selected automatically. Set `subject` to its
expanded identifier when there are several. Supply additional context documents
through `local_contexts`, keyed by URL. Use absolute URLs for `@import` entries.

Invalid input raises `InputError`; unavailable or incompatible profiles raise
`ProfileError`. Evaluator failures appear as `error` findings. Evidence locations
are JSON pointers into the prepared JSON-LD graph.

## Development

Use Python 3.12+ and uv. Run these commands from the repository root:

```sh
uv sync
uv run pytest
uv run ruff check .
uv run mypy src scripts
uv run python scripts/resources/prepare_resources.py --check
```

Update instructions are kept with the tools:

- [F-UJI source code](scripts/fuji/README.md)
- [Profiles, reference files and JSON Schemas](scripts/resources/README.md)
