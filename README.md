# Local Offline Assessor for FAIR (LOAF)

Assess dataset metadata in Python without network access. Supports F-UJI 3.5.1
and FAIR Champion (Core Tests 0.5.12).

[User documentation](https://dans-labs.github.io/local-offline-assessor-for-fair-loaf/) · [Maintainer guide](docs/maintaining.md)

## Install

Requires Python 3.12+. Add to a [uv](https://docs.astral.sh/uv/) project:

```sh
uv add git+https://github.com/Dans-labs/local-offline-assessor-for-fair-loaf.git
```

## Assess a dataset

```python
from fair_offline_assessor import Assessor

result = Assessor("FUJI", version="3.5.1").assess(
    metadata={
        "@context": "https://schema.org",
        "@type": "Dataset",
        "@id": "https://example.org/datasets/1",
        "name": "Example dataset",
        "license": "https://creativecommons.org/licenses/by/4.0/",
    }
)

print(result.model_dump_json(indent=2))
```

Pin `version` for reproducible checks, or omit it to use the assessor's default.
`result.tests` contains outcomes and any scores; `result.diagnostics` reports input
problems; `result.raw` contains the assessor's output. Checks that cannot be decided
offline are `indeterminate`.

[Issues](https://github.com/Dans-labs/local-offline-assessor-for-fair-loaf/issues) · [License](LICENSE) · [Third-party notices](NOTICE)
