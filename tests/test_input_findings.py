import json

import pytest

from fair_offline_assessor import Assessor

METADATA = {
    "@context": "https://schema.org",
    "@id": "urn:data",
    "@type": "Dataset",
    "name": "Example",
    "license": "MIT",
}
IDENTIFIER = "https://doi.org/10.5072/example"


@pytest.mark.parametrize(
    ("metadata", "code"),
    [
        ("{", "invalid_json"),
        ("https://example.invalid/metadata", "invalid_json"),
        (None, "unsupported_input"),
        ({"name": "Example"}, "dataset_not_found"),
    ],
)
def test_unusable_metadata_keeps_identifier_checks_and_input_provenance(metadata, code):
    assessor = Assessor("FUJI")
    result = assessor.assess(metadata=metadata, metadata_url=IDENTIFIER)
    assert any(n.code == code and n.location == "/metadata" for n in result.diagnostics)
    checks = {check.id: check for check in result.tests}
    assert checks["FsF-F1-02MD-1"].outcome == "pass"
    assert checks["FsF-R1.1-01M-1"].outcome == "indeterminate"
    assert checks["FsF-R1.1-01M-1"].reason_code == code
    assert checks["FsF-R1.1-01M-1"].score is None
    assert sum(c.reason_code == "unsupported_check" for c in result.tests) == 7
    assert result.coverage.evaluated == 4
    assert result.coverage.errors == 0
    assert all(m.score is None or not m.score.complete for m in result.metrics)
    assert assessor.assess(metadata=metadata, metadata_url=IDENTIFIER) == result
    different = assessor.assess(metadata="{ ", metadata_url=IDENTIFIER)
    assert result.provenance.input_digest != different.provenance.input_digest
    assert checks["FsF-F1-02MD-1"].evidence[0].digest == result.provenance.input_digest


@pytest.mark.parametrize(
    ("field", "value", "metadata_usable"),
    [
        ("local_contexts", {"urn:unused": 1}, True),
        ("metadata_url", 42, True),
        ("metadata_url", "\ud800", True),
        ("local_contexts", {"urn:unused": {"@context": {}, "bad": float("nan")}}, True),
        ("subject", 42, False),
    ],
)
def test_invalid_optional_evidence_does_not_discard_independent_input(
    field, value, metadata_usable
):
    arguments = {"metadata": METADATA, "metadata_url": IDENTIFIER, field: value}
    result = Assessor("FUJI").assess(**arguments)
    note = next(n for n in result.diagnostics if n.code == f"invalid_{field}")
    assert note.location.startswith(f"/{field}")
    checks = {check.id: check for check in result.tests}
    license_check = checks["FsF-R1.1-01M-1"]
    assert license_check.outcome == ("pass" if metadata_usable else "indeterminate")
    identifier = checks["FsF-F1-02MD-1"]
    assert identifier.outcome == (
        "indeterminate" if field == "metadata_url" else "pass"
    )
    if field == "metadata_url":
        assert identifier.reason_code == "invalid_metadata_url"
        assert identifier.score is None
    assert result.coverage.errors == 0
    assert arguments[field] == value


@pytest.mark.parametrize(
    "metadata",
    [
        METADATA,
        [{"@id": "urn:data", "@type": ["https://schema.org/Dataset"]}],
    ],
)
def test_jsonld_text_preserves_results_and_the_original_input_digest(metadata):
    assessor = Assessor("FUJI")
    parsed = assessor.assess(metadata=metadata)
    text = json.dumps(metadata)
    result = assessor.assess(metadata=text)
    assert result.tests == parsed.tests
    assert result.metrics == parsed.metrics
    assert not result.diagnostics
    assert result.provenance.resources == parsed.provenance.resources
    assert result.provenance.input_digest != parsed.provenance.input_digest
    assert result == assessor.assess(metadata=text)
    missing = assessor.assess(
        metadata={k: v for k, v in METADATA.items() if k != "license"}
    )
    assert next(c for c in missing.tests if c.id == "FsF-R1.1-01M-1").outcome == "fail"


def test_unusable_jsonld_base_is_reported_without_hiding_identifier_results():
    result = Assessor("FUJI").assess(metadata=METADATA, metadata_url="not a uri")
    assert "invalid_jsonld" in {note.code for note in result.diagnostics}
    assert (
        next(c for c in result.tests if c.id == "FsF-R1.1-01M-1").outcome
        == "indeterminate"
    )
    assert next(c for c in result.tests if c.id == "FsF-F1-01MD-1").outcome == "fail"
    assert result.coverage.errors == 0


def test_typed_boolean_keeps_native_assessment_results():
    assessor = Assessor("FUJI")
    native = assessor.assess(metadata={**METADATA, "isAccessibleForFree": False})
    typed = assessor.assess(
        metadata={
            **METADATA,
            "isAccessibleForFree": {
                "@value": "false",
                "@type": "http://www.w3.org/2001/XMLSchema#boolean",
            },
        }
    )
    assert [(c.id, c.outcome, c.score) for c in typed.tests] == [
        (c.id, c.outcome, c.score) for c in native.tests
    ]
    assert typed.metrics == native.metrics
    assert not typed.diagnostics


@pytest.mark.parametrize("readable", [False, True])
def test_unreadable_licence_reports_its_source_without_hiding_usable_evidence(readable):
    licence = [{"@type": "CreativeWork", "name": "Reuse terms"}]
    if readable:
        licence.append("MIT")
    result = Assessor("FUJI").assess(
        metadata={**METADATA, "license": licence}, metadata_url=IDENTIFIER
    )
    note = next(n for n in result.diagnostics if n.code == "unsupported_structure")
    checks = {c.id: c for c in result.tests}
    check = checks["FsF-R1.1-01M-1"]
    assert check.outcome == ("pass" if readable else "indeterminate")
    assert any(
        ref.resource == "prepared_metadata" and ref.location == note.location
        for ref in check.evidence
    )
    if not readable:
        assert check.score is None
        assert check.reason_code == note.code
        assert next(m for m in result.metrics if m.id == check.metric).score is None
    assert checks["FsF-F1-02MD-1"].outcome == "pass"
    assert result.coverage.errors == 0


def test_unreadable_keywords_leave_citation_and_licence_checks_available():
    result = Assessor("FUJI").assess(
        metadata={
            **METADATA,
            "creator": "Alice",
            "publisher": "Archive",
            "datePublished": "2026-01-01",
            "description": "Example data",
            "keywords": {"name": "Soil"},
            "https://example.org/unrelated": {"name": "Ignored"},
        }
    )
    checks = {c.id: c for c in result.tests}
    assert checks["FsF-F2-01M-2"].outcome == "pass"
    assert checks["FsF-F2-01M-3"].reason_code == "unsupported_structure"
    assert checks["FsF-F2-01M-3"].score is None
    assert checks["FsF-R1.1-01M-1"].outcome == "pass"
    metric = next(m for m in result.metrics if m.id == "FsF-F2-01M")
    assert metric.score.observed_earned == 1
    assert not metric.score.complete
    assert {n.code for n in result.diagnostics} == {
        "unsupported_structure",
        "unmapped_term",
    }


@pytest.mark.parametrize("url", [None, "https://example.org/data.csv", "urn:opaque"])
def test_service_only_distribution_keeps_conclusive_results_and_reports_gaps(url):
    distributions = [
        {
            "http://www.w3.org/ns/dcat#accessService": {
                "http://www.w3.org/ns/dcat#endpointURL": {
                    "@id": "https://example.org/api"
                }
            }
        }
    ]
    if url:
        distributions.append({"http://www.w3.org/ns/dcat#downloadURL": {"@id": url}})
    result = Assessor("FUJI").assess(
        metadata={**METADATA, "http://www.w3.org/ns/dcat#distribution": distributions},
        metadata_url=IDENTIFIER,
    )
    checks = {c.id: c for c in result.tests}
    check = checks["FsF-A1.1-01MD-2"]
    assert check.outcome == (
        "pass" if url and url.startswith("https:") else "indeterminate"
    )
    if check.outcome == "indeterminate":
        assert check.reason_code == "unsupported_structure"
        assert check.score is None
    assert checks["FsF-F3-01M-2"].outcome == ("pass" if url else "indeterminate")
    assert checks["FsF-R1.1-01M-1"].outcome == "pass"
    assert checks["FsF-A1.1-01MD-1"].outcome == "pass"
    assert any(n.code == "unsupported_structure" for n in result.diagnostics)
    assert result.coverage.errors == 0
