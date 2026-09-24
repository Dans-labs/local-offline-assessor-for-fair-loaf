# fair-offline-assessor

Check dataset metadata against FAIR requirements in Python, without network access.
Choose an assessor and a version to use its metadata interpretation and checks.
F-UJI 3.5.1 and FAIR Champion (Core Tests 0.5.12) are supported.

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

`result.raw` contains the selected assessor's output from the offline run.

The version chooses the assessor's interpretation, check requirements and
reference data. Omit `version` to use the library's default.

## Use FAIR Champion

Champion accepts JSON-LD and a separate target identifier:

```python
result = Assessor("FAIR_CHAMPION", version="0.5.12").assess(
    metadata={
        "@context": "https://schema.org",
        "@type": "Dataset",
        "identifier": "10.1234/example",
        "license": "https://creativecommons.org/publicdomain/zero/1.0/",
    },
    target_identifier="10.1234/example",
    metadata_url="https://example.org/metadata",
)
```

This Python port returns 16 check outcomes grouped into 13 metrics, without numeric
scores. Thirteen checks use local evidence; two can decide some cases offline;
search indexing remains indeterminate. The selected version pins FAIR Core Tests,
not the Champion web application. See [Champion's inputs and limitations](docs/site/src/app/assessors/champion/page.mdx).

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
for development, preparing assessor code and data, and adding versions.

[Issues](https://github.com/akeldamas/fair-offline-assessor/issues) · [License](LICENSE) · [Third-party notices](NOTICE)
