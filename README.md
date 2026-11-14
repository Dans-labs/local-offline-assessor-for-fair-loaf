# fair-offline-assessor — single-engine F-UJI edition

An offline FAIR assessment library based on pinned, adapted upstream F-UJI 3.5.1
metric definitions and evaluators. This is a **source rebuild** of LOAF, not a
new independent implementation of FAIR metrics.

## Quick start

```bash
uv sync
uv run python - <<'PY'
from fair_offline_assessor import FairAssessor

assessor = FairAssessor()  # profile loaded and verified once per process
result = assessor.assess(metadata={
    "@context": "https://schema.org",
    "@type": "Dataset",
    "@id": "https://example.org/datasets/1",
    "name": "Example dataset",
    "license": "https://creativecommons.org/licenses/by/4.0/",
})
print(result.model_dump_json(indent=2))
PY
```

The legacy `Assessor("FUJI", version="3.5.1")` entry point remains available.
There is no Champion assessor, adapter registry, or runtime assessor selection.
`FairAssessor.assess_many(iterable)` yields results lazily.

## What is faster

- `yaml.CSafeLoader` parses pinned YAML reference catalogues.
- A process-wide LRU cache parses catalogues once for each verified resource bundle.
- A second cache constructs the expensive standards and linked-vocabulary indexes once.
- The profile is loaded and its resources hash-verified once per process.
- Each assessment creates its own runner and separate metric results. Static
  catalogues and derived lookup indexes are reused rather than deep-copied for
  every metric; top-level metric/test dictionaries stay evaluator-private.
- The access-rights evaluator gets its own licence list, because pinned F-UJI
  can mutate that list. Native result snapshots remain detached for callers.

**Cold-start vs warm-run:** Caches accelerate repeated assessments in the **same
process**, not individual invocations of `python` in separate processes.
Performance and output equivalence must be measured on representative metadata.

## Synchronising with upstream F-UJI

F-UJI is the authority for metrics and scoring. Do not edit generated vendor files.

The checked-in recipe is `scripts/fuji/3.5.1.json`, containing the complete pinned
upstream Git commit. The existing `scripts/fuji/prepare_fuji.py` is the
AST/source extractor and offline patch application pipeline; `sync_fuji.py`
coordinates it with the resource-index generator.

```bash
# No network access. Verify pinned version, resources and generated indexes.
uv run python scripts/sync_fuji.py --check

# Rebuild from an already available local upstream git clone/checkout.
uv run python scripts/sync_fuji.py --source /path/to/fuji
```

To advance to a **new F-UJI release**, update the extraction recipe and review
changes in evaluators, metadata readers, metric IDs, resource names, and offline
patches. The updater **does not claim to support arbitrary upstream versions**:
this is deliberate, since upstream F-UJI has no guaranteed stable Python API.
Update the library's version pin (`assessment.py`, integration imports, and
resource references), run conformance tests, and release the new bundle with its
updated commit/digests. Retain provenance of the upstream commit and offline
patch in version control.

## Tests and benchmarking

```bash
uv run pytest -q tests/test_fuji.py tests/test_fuji_metadata.py
uv run python scripts/benchmark.py
```

Compare the full results for the same dataset against the original LOAF code
before shipping. The offline results are not guaranteed to equal F-UJI **online**
results because network-only checks are indeterminate.

## Known limitations

- JSON-LD remote contexts are resolved exclusively through embedded/local maps.
- Native F-UJI readers and their transitive dependencies remain relatively heavy.
- The retained generic internal `profiles.py` is used for integrity checks, but
  only one profile is bundled and exposed. It can be replaced once the existing
  profiles' provenance and validation tests are ported.
- Upstream source and license notices are retained in `NOTICE` and `LICENSES/`.

Compatibility note: `load_profile`/`list_profiles` are retained for existing
integrity tests and callers, but the shipped catalogue contains just F-UJI.

## Compatibility and isolation regression fixes

This update restores the one-shot `assess(..., provider=...)` test extension point
and exports `BundledProfileProvider` for compatibility. Pinned reference and
adapter versions are checked before parsing untrusted assessment inputs.

`Runner.evaluate()` snapshots native evaluator output before returning it,
preventing mutation of a result's nested collections from modifying the
input metadata or another assessment. Large static reference catalogues are
still shared and are **not** deep-copied for each metric.

The catalogue-parsing regression test now measures the caching contract
(one parse per resource bundle, with current metadata-reader JSON reloads)
instead of expecting the old repeated YAML `safe_load` calls.

Run `uv sync --group dev && uv run pytest -q` on a fully provisioned host.
