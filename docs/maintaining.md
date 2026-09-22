# Maintaining

Run commands from the repository root.

## Development

```sh
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy src scripts
uv run pytest
uv build
uv run --group release twine check dist/*
```

Tests run with sockets disabled.

## Code and generated files

Assessment code lives in `src/fair_offline_assessor/`. `_input.py` and
`_metadata.py` prepare JSON-LD. `_fuji_metadata.py` maps it to F-UJI fields,
`_fuji.py` runs the evaluators, and `_fuji_assessment.py` builds the shared result.

Profiles select adapter and resource versions. Resource manifests record upstream
sources, files, aliases and licences.

| Maintained inputs | Generated files |
| --- | --- |
| [F-UJI recipe](../scripts/fuji/3.5.1.json), [resource manifest](../src/fair_offline_assessor/resources/assessors/fuji/3.5.1/manifest.json), [preparation script](../scripts/fuji/prepare_fuji.py) | `_vendor/fuji/v3_5_1/` and F-UJI resource files |
| Resource manifests, bundled files and profiles | `resources/resources.json`, `resources/profiles.json` |
| [Python models](../src/fair_offline_assessor/models/v1.py) | `resources/schemas/profile-v1.json`, `resources/schemas/result-v1.json` |

Generated paths above are relative to `src/fair_offline_assessor/`.
Everything in `_vendor/` is generated. Its `source.patch` records source edits;
`upstream.json` records the source commit and file hashes. Make changes in the
preparation script, then regenerate.

## Updating F-UJI and resources

To regenerate the bundled F-UJI version:

```sh
uv run python scripts/fuji/prepare_fuji.py --recipe scripts/fuji/3.5.1.json
uv run python scripts/resources/prepare_resources.py
```

The first command fetches the pinned Git commit and prepares the selected code
and resources. Add `--source /path/to/fuji` to use a local Git repository containing
that commit. The second command validates local bundles and generates indexes
and SHA-256 hashes.

For a new upstream version:

1. Copy the recipe to `scripts/fuji/<version>.json` and the manifest to
   `src/fair_offline_assessor/resources/assessors/fuji/<version>/manifest.json`.
   Set the version and full upstream commit in both; review evaluator names and
   resource paths.
2. Review the preparation script's version-specific source edits, removed network
   methods and allowed dependencies. Add the adaptations needed for that version.
3. Run the commands above with the new recipe. Review the generated diff and
   update `NOTICE` and `LICENSES/` if attribution or licence terms changed.
4. Add an adapter version using the new vendor imports and resource versions.
   Take its resource hashes from the generated `resources.json`. Add a profile
   selecting that adapter and its resources, then regenerate the indexes.
5. Compare checks and scores with upstream, review coverage changes, and run the
   development checks. Commit the declarations, integration changes and generated
   files together.

For Schema.org, copy the context unchanged from the repository, commit and path
recorded in its [manifest](../src/fair_offline_assessor/resources/metadata/schemaorg/30.0/manifest.json).
For an update, create a new bundle under `src/fair_offline_assessor/resources/metadata/`
with its source and licence in `manifest.json`, select it in a profile, and run
`prepare_resources.py`.

Check that generated F-UJI files and indexes are current:

```sh
uv run python scripts/fuji/prepare_fuji.py --check
uv run python scripts/resources/prepare_resources.py --check
```

Use `--recipe` when checking an additional F-UJI version.

## Changing assessments

For F-UJI, register the evaluator in `_fuji.py`'s `EVALUATORS` and map any additional
evidence in `_fuji_metadata.py`. Include new upstream modules in the recipe and
regenerate. Check outcomes and scores against the pinned upstream evaluator;
cover missing and invalid evidence as well as valid input. Keep coverage assertions
in `tests/test_assessment.py` aligned with the supported checks.

An additional assessor needs an `AssessorAdapter` implementation returning
`AssessmentResult`, its resource declarations and a profile. Register its name,
default profile and adapter in `assessment.py` for both public entry points.

Assessments must stay offline. Checks needing HTTP or HTML evidence remain
`indeterminate` without a score.

## Versioning and compatibility

Package versions live in `pyproject.toml`; upstream versions live in recipes.
Profiles pin adapter and resource versions; `engine_requires` sets compatible
library versions. `Assessor(..., version=...)` selects the profile version, which
for F-UJI follows the pinned upstream F-UJI release.
Public JSON formats use `schema_version`.

Keep released profiles, resource bundles and schemas unchanged. Add new versions
alongside them and keep their adapters available. Test old and new selections
before changing the default in `assessment.py`.

After changing Python models, regenerate their JSON schemas:

```sh
uv run python scripts/resources/generate_schemas.py
```

A new JSON format needs a versioned model and an update to the schema generator.
Retain the released models and schema files.

To check released resources, extract a previous wheel and pass its
`fair_offline_assessor/resources` directory:

```sh
uv run python scripts/resources/prepare_resources.py --check --released /path/to/extracted/fair_offline_assessor/resources
```
