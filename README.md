# fair-offline-assessor

A Python library for assessing FAIR principles using metadata you provide.
The library does not resolve URLs or fetch missing evidence.

The assessment API is still being built. You can already list and load profiles,
but assessments from JSON-LD input are not available yet.

The current profile is `fusji-offline@3.5.1`. It uses F-UJI 3.5.1 and metrics 0.8.
A profile specifies which assessor and resource versions to use.

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

- [Profiles, reference files and JSON Schemas](scripts/resources/README.md)
