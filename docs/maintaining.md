# Maintaining the library

Run commands from the repository root unless stated otherwise.

## Development checks

```sh
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy src scripts
uv run pytest
uv build
uv run --group release twine check dist/*
```

Tests block network connections. For documentation changes, follow the
[documentation site instructions](site/README.md).

Keep tests focused on distinct behaviour or regressions. Before adding or removing
a case, check what existing tests already cover. Test an interpretation through
the library rather than repeating a dependency's own tests. Invalid-input tests
must check the intended error; an unrelated validation failure can hide a broken
test. Preserve coverage for offline execution, version pins and result compatibility.

## Where to make changes

`Assessor(name, version=...)` chooses the code and data used for an assessment.
The selected assessor supplies the metadata mappings, check requirements and
scoring rules. The library controls offline execution and the common response format.

The Python code is in `src/fair_offline_assessor/`:

| File | Responsibility |
| --- | --- |
| `assessment.py` | Available assessors, versions and defaults |
| `assessors/fuji/metadata.py`, `assessors/fuji/html.py` | Apply F-UJI's mappings to supplied documents without fetching more information |
| `assessors/fuji/checks.py` | Run F-UJI checks and keep their original results |
| `assessors/fuji/assessment.py` | Convert F-UJI results into the common response and report input problems |
| `_metadata.py` | Interpret JSON-LD field names using locally available context definitions |
| `models/v1.py` | Fields and allowed values for the library's input configuration and response |

Code we maintain for each assessor belongs in `assessors/<name>/`. F-UJI's
generated code stays in `_vendor/fuji/<version>/`, and its data files stay in
`resources/assessors/fuji/<version>/`. The public API and common result definitions
are shared by all assessors.

A configuration file under `resources/profiles/` chooses an assessor implementation
and its data files. The code calls this a **profile**. A `manifest.json` lists the
included data files, their sources and licences.

## Generate F-UJI mappings and checks

The settings in [scripts/fuji/3.5.1.json](../scripts/fuji/3.5.1.json) specify the
F-UJI version, exact Git commit and code to include. The preparation script copies
F-UJI's mappings and assessment code from that commit. It changes the code where
needed to use local files and prevent network access.

```sh
uv run python scripts/fuji/prepare_fuji.py --recipe scripts/fuji/3.5.1.json
uv run python scripts/resources/prepare_resources.py
```

The first command writes:

- `_vendor/fuji/v3_5_1/`: F-UJI's mappings, code for choosing and interpreting
  metadata, checks and result definitions.
- `resources/assessors/fuji/3.5.1/`: scoring requirements and lists such as
  recognised licences, identifiers and file formats.

Both paths are relative to `src/fair_offline_assessor/`. The second command writes
`resources/resources.json` and `resources/profiles.json`, listing available files
and configurations with checksums to detect changes.

The first command downloads the chosen F-UJI source by default. Add
`--source /path/to/fuji` to use a local Git repository containing the required
commit. Only committed files are used. Add `--check` to either command to compare
generated files without changing them.

Do not edit files in `_vendor/`. Make changes in
[prepare_fuji.py](../scripts/fuji/prepare_fuji.py), then regenerate.
The generated `upstream.json` records the original commit and file checksums;
`source.patch` records the changes made to F-UJI's code.

## Prepare Champion definitions

Champion is under development and cannot yet be selected for assessment.
The settings in [scripts/champion/0.5.12.json](../scripts/champion/0.5.12.json)
pin FAIR-Core-Tests 0.5.12, Harvester 0.1.17, source checksums and offline limitations.
Preparation extracts 16 check definitions, their 13 metric identifiers, ordered
identifier patterns and predicates. It does not translate or run Ruby checks.

```sh
uv run python scripts/champion/prepare_champion.py
uv run python scripts/resources/prepare_resources.py
```

The first command downloads the pinned sources unless local inputs are supplied.
It writes `resources/assessors/champion/0.5.12/` and the fixed resource checksums in
`assessors/champion/v0_5_12/bindings.py`, both under `src/fair_offline_assessor/`.
It also copies the upstream licence notices into `LICENSES/`.

To verify generated files without downloads or writes, supply both local inputs:

```sh
uv run python scripts/champion/prepare_champion.py --source /path/to/FAIR-Core-Tests --harvester-gem /path/to/fair_champion_harvester-0.1.17.gem --check
uv run python scripts/resources/prepare_resources.py --check
```

`--source` must contain the pinned Git commit; checkout edits are ignored.
Change the settings or extraction script, then regenerate and review the diff.
Keep other versions intact. Future Python checks belong beside `definitions.py`
in `assessors/champion/v0_5_12/`; public registration waits until they are ready.

## Add a F-UJI version

1. Copy the settings file to `scripts/fuji/<version>.json` and the data-file list to
   `src/fair_offline_assessor/resources/assessors/fuji/<version>/manifest.json`.
   Set the version and full Git commit in both. Review the selected code and files.
2. Review the preparation script's changes for that version. Check which functions
   access the network and which additional Python packages are needed.
3. Run the generation commands with the new settings file. Review all generated
   changes, including mappings and scoring rules. Update `NOTICE` and `LICENSES/`
   if the source's attribution or licence changed.
4. Add a Python class under `assessors/fuji/` for the new version using its
   generated code and data.
   Use the checksums in `resources.json`. Register the class in `assessment.py`
   and add its configuration under `resources/profiles/`. Regenerate the indexes
   with `prepare_resources.py`.
5. Compare mapped fields, the chosen dataset and results with that F-UJI version.
   Test supported formats, missing or invalid input, and blocked network access.
   Run the development checks and both generation commands with `--check`.
6. Commit the settings, Python changes and generated files together. Test old
   versions before changing the default in `assessment.py`.

## Add checks or assessors

`EVALUATORS` in `assessors/fuji/checks.py` connects groups of checks to F-UJI classes
and lists checks unavailable offline. Update these entries and the generation settings when
enabling checks. Regenerate, compare outcomes and points with F-UJI, and update
the expected check counts in `tests/test_assessment.py`.
Keep metadata mappings and scoring rules in the generated F-UJI code.

When versions or supported checks change, update the tables on the documentation
overview and assessor page. Count a metric as having offline checks if at least
one is supported, and distinguish full from partial support. "Latest supported"
means a version available in this library, not the latest upstream release.

For another assessor, create `assessors/<name>/` and implement the Python interface
`AssessorAdapter` from `adapters.py`. This class connects the assessor to the library.
It must interpret the supplied metadata using that assessor's rules and return `AssessmentResult`.
Preserve the assessor's original output in `raw` before converting results, so an
error during conversion does not lose that output.

Add the assessor's data files and configuration. Register its name, default
version and class in `assessment.py` for both `Assessor(...)` and `assess(...)`.
Checks that need information unavailable offline must remain `indeterminate`
without a score.

## Update the Schema.org context

The context defines the meaning of JSON-LD field names. Its
[manifest](../src/fair_offline_assessor/resources/metadata/schemaorg/30.0/manifest.json)
records the source repository, commit, path and licence.

For a new version, create a directory under `resources/metadata/schemaorg/`.
Copy the context unchanged, add its `manifest.json`, choose it in an assessment
configuration and run `prepare_resources.py`.

## Keep versions reproducible

The package version is in `pyproject.toml`. Assessor versions and source commits are in
`scripts/<assessor>/`. Each assessment configuration records its code and data versions;
`engine_requires` states which library versions can use it. The public `version`
argument selects this configuration version.

After a release, keep its configurations, data files and response definitions
unchanged. Add new versions alongside them and keep the old implementations
available.

After changing Python models, update the JSON Schema files that describe their
allowed fields and values:

```sh
uv run python scripts/resources/generate_schemas.py
```

Public responses use `schema_version` to identify their format. A new response
format needs its own model and schema file; retain the released ones.

To check that released files are unchanged, extract a previous wheel and use its
`fair_offline_assessor/resources` directory:

```sh
uv run python scripts/resources/prepare_resources.py --check --released /path/to/extracted/fair_offline_assessor/resources
```
