# Maintaining pinned F-UJI

This fork supports a **single** F-UJI revision: 3.5.1, commit
`9227fabb7f047475714f2e7622798b855c883f72`.

Verification, without network access:

```bash
uv run python scripts/sync_fuji.py --check
```

Rebuild vendored sources from the **pinned** upstream commit available in a
local Git clone:

```bash
uv run python scripts/sync_fuji.py --source /path/to/fuji
```

`sync_fuji.py` invokes `scripts/fuji/prepare_fuji.py`, the pre-existing
source extraction/patching mechanism, and regenerates the index and resource
digests. The resulting adapted code and `source.patch` are versioned together.

Do not point the 3.5.1 recipe at a newer upstream tag. For a new version,
make a new recipe and vendor directory, review upstream evaluator API and
metric differences, update single-engine imports and version pins, then compare
full assessment outputs on the fixtures and run profile-integrity checks.

The upstream source hashes in `upstream.json` reflect **unpatched** source,
while `source.patch` records necessary offline adaptations. Keep their original
licence notices with the shipped files.

Do not claim online/offline conformance for checks requiring network evidence.

## Evaluator state and copying policy

`assessors/fuji/checks.py` deliberately **does not recursively copy** the
pinned licence/identifier/vocabulary/format/protocol catalogues on every metric.
The 3.5.1 evaluator implementations read their nested reference dictionaries.
There is one cheap shallow copy of the outer `SPDX_LICENSES` list to preserve
legacy isolation when a native evaluator clears or rearranges that list.

Each metric gets a fresh top-level metric definition and a fresh dictionary per
metric test (the nested requirements are read-only). Each call constructs a new
`metadata_merged` mapping. Only the access-rights metric makes a private shallow
copy of the metadata `license` list: the upstream `excludeLicences()` method
appends to that list. The generated `content_identifier` and `pid_collector`
objects are private per evaluation already.

Two snapshots of native output are **intentional**: storing the native result
separates it from `MetricEvaluation.native`, and the `native_results` property
returns a detached snapshot so caller edits cannot corrupt stored results.
Likewise, local JSON-LD context copies in `_metadata.py` protect caller-owned
context documents from downstream context-resolution mutation. Vendored F-UJI
code is kept unmodified for upstream syncing.

**When running `scripts/sync_fuji.py` against a new F-UJI release, re-audit
mutation of context metadata and lookup resources before reusing this policy.**
The regression tests in `tests/test_fuji.py` and `tests/test_native_results.py`
check mutable-state isolation. Changes to upstream evaluators may require
selectively copying additional fields.
