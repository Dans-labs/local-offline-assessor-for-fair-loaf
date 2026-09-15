# F-UJI source code

`prepare_fuji.py` copies the selected F-UJI evaluators and the models they need.
[3.5.1.json](3.5.1.json) records the repository, source commit and evaluator
names.

## Recreate the current copy

Requires Git. Run from the repository root:

```sh
uv run python scripts/fuji/prepare_fuji.py
```

The script fetches the exact commit into a temporary Git repository and writes
the output to `src/fair_offline_assessor/_vendor/fuji/v3_5_1/`.
Evaluator and model code is copied with its imports changed to our package.
The two helper files contain only the upstream constants we use.
`upstream.json` records the source files and checksums; `imports.patch` shows the
import changes already made. All of these files are generated.

Add `--check` to fetch and compare without changing the generated files.
For offline preparation, pass `--source` followed by the path to a local F-UJI Git
repository containing the selected commit. An unexpected import stops preparation;
review the dependency before allowing it in `prepare_fuji.py`.

## Add a F-UJI version

1. Copy `3.5.1.json` to a new JSON file named after the release version.
   Set `version` and `commit` to that release and its full Git commit.
2. Set `evaluators` to the module names to copy, without `.py`.
3. Run the preparation command with
   `--recipe scripts/fuji/<version>.json`. This creates a separate version
   directory. Keep the old recipe and generated files for existing profiles.
4. Copy the release's metric YAML into a new [resource bundle](../resources/README.md).
   For 3.5.1, use [metrics_v0.8.yaml](https://raw.githubusercontent.com/pangaea-data-publisher/fuji/9227fabb7f047475714f2e7622798b855c883f72/fuji_server/yaml/metrics_v0.8.yaml).
5. Update `src/fair_offline_assessor/_fuji.py` to use the new code, input fields
   and metric definitions. Check the scoring and output against upstream.
   Keep the old implementation available for existing profiles.
6. Add a new profile selecting the new adapter version and resources, then generate
   the indexes using the resource guide. Test changed checks against the same F-UJI
   release and run the [project checks](../../README.md#development).

Missing evidence must stay indeterminate. Incomplete scores must have no percentage.
