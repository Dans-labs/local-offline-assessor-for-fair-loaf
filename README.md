# fair-offline-assessor

Check dataset metadata against FAIR requirements in Python, without network access.
Choose an assessor and a version to use its metadata mappings, checks and scoring
rules. F-UJI is currently the supported assessor.

## Install

Requires Python 3.12+. Add to a [uv](https://docs.astral.sh/uv/) project:

```sh
uv add git+ssh://git@github.com/akeldamas/fair-offline-assessor.git
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

`result.tests` contains the check results and scores. `result.diagnostics` explains
problems with the supplied metadata. A check is `indeterminate` when the library
cannot decide whether it passes; that check receives no score.

`result.raw` contains the assessor's original results from this run, unchanged.
For F-UJI, these are results for each group of checks, called a metric.

The version chooses the assessor's mappings and scoring rules, including the
lists it uses to recognise licences, identifiers and file formats. Omit `version`
to use the library's default.

## Other formats

JSON-LD is the default. Set `metadata_format` when supplying another format:

```python
from pathlib import Path

result = Assessor("FUJI", version="3.5.1").assess(
    metadata=Path("datacite.xml").read_text(encoding="utf-8"),
    metadata_format="xml",
)
```

See [metadata and results](docs/native-metadata.md) for supported formats and
examples of scoring requirements. See [maintaining the library](docs/maintaining.md)
for development, generating F-UJI mappings and adding versions.

[Issues](https://github.com/akeldamas/fair-offline-assessor/issues) · [License](LICENSE) · [Third-party notices](NOTICE)
