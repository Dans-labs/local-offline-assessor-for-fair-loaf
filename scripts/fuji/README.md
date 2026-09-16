# F-UJI preparation

`prepare_fuji.py` copies the selected F-UJI evaluators, models and reference files.
[3.5.1.json](3.5.1.json) records the repository, source commit and evaluator
names.

## Recreate the current copy

Requires Git. Run from the repository root:

```sh
uv run python scripts/fuji/prepare_fuji.py
```

The script fetches the exact commit into a temporary Git repository and writes
the code to `src/fair_offline_assessor/_vendor/fuji/v3_5_1/`.
Evaluator and model code is copied with its imports changed to our package.
The two helper files contain only the upstream constants we use.
`upstream.json` records the source files and checksums; `imports.patch` shows the
import changes already made. All of these files are generated.

The [resource manifest](../../src/fair_offline_assessor/resources/assessors/fuji/3.5.1/manifest.json)
lists the metric YAML and catalogues to copy into that manifest's directory.
Its version and source pin must match the recipe. Files are copied unchanged;
the manifest stays manually maintained.

Add `--check` to fetch and compare without changing the generated files.
For offline preparation, pass `--source` followed by the path to a local F-UJI Git
repository containing the selected commit. An unexpected import stops preparation;
review the dependency before allowing it in `prepare_fuji.py`.

## Add a F-UJI version

1. Copy `3.5.1.json` to a new JSON file named after the release version.
   Set `version` and `commit` to that release and its full Git commit.
2. Set `evaluators` to the module names to copy, without `.py`.
3. Copy the resource manifest to
   `src/fair_offline_assessor/resources/assessors/fuji/<version>/manifest.json`.
   Match its version, repository and commit to the recipe. List the files needed
   by the selected evaluators, with their upstream paths.
4. Run the preparation command with
   `--recipe scripts/fuji/<version>.json`. This creates a separate version
   directory. Keep the old recipe and generated files for existing profiles.
5. Update `src/fair_offline_assessor/_fuji.py` to use the new code, input fields
   and metric definitions. Check the scoring and output against upstream.
   Keep the old implementation available for existing profiles.
6. Add a new profile selecting the new adapter version and resources, then generate
   the indexes with `uv run python scripts/resources/prepare_resources.py`.
   See the [resource guide](../resources/README.md) for the profile format.
   Test changed checks against the same F-UJI release and run the
   [project checks](../../README.md#development).

Missing evidence must stay indeterminate. Incomplete scores must have no percentage.

Register supported metrics in `_fuji.EVALUATORS` with their generated evaluator,
evidence fields and required resources. The runner loads resources once per
assessment and gives each evaluator a separate working copy.

## Metadata mapping

[_fuji_metadata.py](../../src/fair_offline_assessor/_fuji_metadata.py) maps supplied
JSON-LD into F-UJI fields. The supported terms follow the
[F-UJI 3.5.1 RDF collector](https://github.com/pangaea-data-publisher/fuji/blob/9227fabb7f047475714f2e7622798b855c883f72/fuji_server/helper/metadata_collector_rdf.py#L480),
while keeping multiple values and their source locations. This mapper is maintained
manually; source preparation does not generate it. Extend it when new checks need
additional fields.
