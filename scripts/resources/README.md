# Profiles and resources

Profiles specify the assessor implementation and reference files to use.
Those files live in `src/fair_offline_assessor/resources/`. Paths below are relative
to that directory; run commands from the repository root.

## Add or update a profile

Using F-UJI as the example:

1. Add `assessors/fuji/<version>/manifest.json`. Record the file names, source commit or
   URL, source paths, version and licence. The [F-UJI manifest](../../src/fair_offline_assessor/resources/assessors/fuji/3.5.1/manifest.json)
   shows the format. Keep the required licences and attribution in `LICENSES/` and `NOTICE`
   at the repository root. Keep relative paths between files, such as XSD includes.
2. Run the [F-UJI preparation command](../fuji/README.md) to copy the declared files.
   For other reference bundles, copy the upstream files unchanged beside their
   manifest. Shared references such as Schema.org and DCAT go under `metadata/`.
3. Add `profiles/fusji-offline/<profile-version>.json`. Set `adapter` and
   `adapter_version` to the implementation to run, and `resources` to the exact
   resource IDs and versions it needs. Set `engine_requires` to the compatible
   library versions.
4. Run `uv run python scripts/resources/prepare_resources.py`. It checks the files
   and writes `profiles.json` and `resources.json`, including their checksums.
   Add `--check` to check the indexes without rewriting them.

For the current bundle, `fuji:metrics@3.5.1` contains metrics **0.8** from F-UJI
**3.5.1**. The software release and metric definitions have separate version numbers.

Keep published profiles and resources unchanged. Before a release, run the
preparation command with `--released` followed by the path to
`fair_offline_assessor/resources/` extracted from the previous release's wheel.
It rejects changes to existing profiles, resources and JSON Schemas.

## Update the model schemas

The profile and result models live in `src/fair_offline_assessor/models/v1.py`.
After changing them, run:

```sh
uv run python scripts/resources/generate_schemas.py
```

This writes `schemas/profile-v1.json` and `schemas/result-v1.json` from the Python
models. Adding a profile does not require running this command. When adding V2,
keep the V1 Python models as well as their generated schemas for existing callers.
