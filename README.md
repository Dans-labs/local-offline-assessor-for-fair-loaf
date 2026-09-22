# fair-offline-assessor

Assess JSON-LD dataset metadata against F-UJI checks without network access.

## Installation

Requires Python 3.12+. Add to a [uv](https://docs.astral.sh/uv/) project:

```sh
uv add git+ssh://git@github.com/akeldamas/fair-offline-assessor.git
```

## Usage

```python
from fair_offline_assessor import Assessor

result = Assessor("FUJI").assess(
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

Results include check outcomes, scores and diagnostics. Checks requiring HTTP or
HTML evidence are marked `indeterminate`.

[Issues](https://github.com/akeldamas/fair-offline-assessor/issues) · [License](LICENSE) · [Third-party notices](NOTICE)
