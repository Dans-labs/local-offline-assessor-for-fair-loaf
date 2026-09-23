# Metadata and results

Choose an assessor and version to use its metadata mappings, checks and scoring
rules. A mapping connects a field in your metadata to information the assessor
checks. For example, F-UJI recognises Schema.org `name` as a dataset title.

## What F-UJI checks

`Assessor("FUJI", version="3.5.1")` uses F-UJI 3.5.1's own rules. It looks for
identifiers, descriptive information, licences, access conditions, links to data
and information about how the data was created.

Each check has specific requirements and points. Examples:

| Required information | Check ID | Points when met |
| --- | --- | --- |
| `metadata_url` with recognised identifier syntax, such as a URL or UUID | `FsF-F1-01MD-1` | 1 |
| Creator, title, identifier, publication date, publisher and dataset type | `FsF-F2-01M-2` | 1 |
| All of those descriptive fields, plus a summary and keywords | `FsF-F2-01M-3` | 1 |
| Licence information in an appropriate field | `FsF-R1.1-01M-1` | 1 |

See the [complete F-UJI check definitions](../src/fair_offline_assessor/resources/assessors/fuji/3.5.1/metrics_v0.8.yaml).
Field names depend on the metadata standard; F-UJI's mappings connect them to
these requirements.

## Supplying metadata

Pass document contents to `metadata` and choose their format with `metadata_format`.
The library does not open file paths or URLs for you.

| `metadata_format` | Accepted contents |
| --- | --- |
| omitted or `json-ld` | A JSON-LD dictionary, list of dictionaries or JSON text |
| `datacite-json` | DataCite JSON with `agency` and metadata fields such as `titles` at the top level |
| `xml` | DataCite, Dublin Core, DDI Codebook/Lifecycle, CMDI, DIF, MODS, EML, ISO metadata, EAD or TEI XML |
| `html` | HTML containing JSON-LD, Dublin Core, Microdata, RDFa, Highwire/Eprints or OpenGraph metadata |
| `turtle`, `n3`, `nt`, `nquads`, `trig`, `rdfxml` | Text in the selected RDF format |

DataCite JSON requires `agency`; metadata inside a `data.attributes` API response
is not supported. XML must contain its own information, without DOCTYPE or entity
declarations. For OAI-PMH XML with several records, F-UJI uses the first.
RSS/GeoRSS and OAI-ORE Atom are not supported.

Supply one intended dataset per document. F-UJI chooses which dataset to assess
using its own rules. For JSON-LD or other RDF formats, `subject` can verify that
it chose the identifier you expected. If the choice cannot be confirmed, affected
checks become `indeterminate` with `subject_not_selected`. Omit `subject` for
HTML, XML and DataCite JSON.

For Schema.org metadata, use `identifier` for the dataset identifier required by
the citation check; F-UJI does not use `@id` for that field. Describe creators as
`Person` or `Organization` objects, such as
`"creator": {"@type": "Person", "name": "Ada Example"}`. F-UJI 3.5.1 does not use
plain text creators or `isAccessibleForFree: false` in RDF input.

## JSON-LD and field names

A JSON-LD `@context` defines what field names mean. The library includes the
Schema.org context. Supply other context documents in `local_contexts`, or put
the definitions directly in `@context`. Referenced contexts are never downloaded.
Use absolute identifiers, or supply `metadata_url` as a starting URL for relative ones.

Schema.org, DCAT and Dublin Core are **vocabularies**: sets of named properties
with agreed meanings. DataCite defines a **metadata schema**: fields and rules for
a description. **RDF** describes things through statements such as “this dataset
has this title”. JSON-LD and Turtle are ways to write those statements.

The context gives names their meaning. The assessor determines which information
must be present to earn points.

## Reading results

The library returns common fields for check results, scores and messages. This
lets applications use the same code to read results while keeping the assessor's
own check IDs and scoring rules.

- `tests` contains individual check results.
- `metrics` contains results for groups of checks about one aspect of FAIR.
- `coverage` counts how many checks were decided, left undecided or encountered errors.
- `diagnostics` explains problems with the supplied metadata.
- `raw` contains the assessor's original results from this run, unchanged.

A check is `indeterminate` when the available information is insufficient to
decide whether it passes. It receives no score. Scores for groups of checks are
marked incomplete when not all necessary information is available.

For F-UJI, `raw` is a list with at most one original result per metric. It covers
only this offline run, not a full response from F-UJI's online service. Use `tests`
and `coverage` for offline decisions: a failure in `raw` can be `indeterminate`
in `tests` when the information needed to decide was unavailable.

`profile` and `provenance` record the selected version and the software and data
used. See [maintaining](maintaining.md) for generating F-UJI mappings and adding
assessor versions.
