from datetime import UTC, datetime
from uuid import uuid4

from fair_offline_assessor.assessors.champion.v0_5_12.checks import CheckDecision
from fair_offline_assessor.assessors.champion.v0_5_12.definitions import TestDefinition
from fair_offline_assessor.models.v1 import JsonObject


def _english(value: str) -> JsonObject:
    """Represent FTR's English-language literals explicitly."""
    return {"@value": value, "@language": "en"}


def test_output(
    definition: TestDefinition,
    decision: CheckDecision,
    target_identifier: str | None,
    *,
    adapter_version: str,
) -> JsonObject:
    """Emit the offline port's result in ftr_ruby 0.1.12's FTR graph structure.

    Identify the Python implementation, with local logs and no service endpoints.
    This is not a response captured from the Ruby service.
    """
    result_id = f"urn:fairtestoutput:{uuid4()}"
    execution_id = f"urn:ostrails:testexecutionactivity:{uuid4()}"
    target_id = f"urn:ostrails:testedidentifiernode:{uuid4()}"
    software_id = (
        f"urn:fair-offline-assessor:champion:0.5.12:{adapter_version}:{definition.id}"
    )
    description = f"Offline Python implementation of {definition.name}."
    target: JsonObject = {"@id": target_id, "@type": "prov:Entity"}
    if target_identifier is not None:
        target["dct:identifier"] = target_identifier
    return {
        "@context": {
            "xsd": "http://www.w3.org/2001/XMLSchema#",
            "prov": "http://www.w3.org/ns/prov#",
            "dct": "http://purl.org/dc/terms/",
            "dcat": "http://www.w3.org/ns/dcat#",
            "ftr": "https://w3id.org/ftr#",
            "sio": "http://semanticscience.org/resource/",
            "schema": "http://schema.org/",
        },
        "@graph": [
            {
                "@id": execution_id,
                "@type": "ftr:TestExecutionActivity",
                "prov:wasAssociatedWith": {"@id": software_id},
                "prov:used": {"@id": target_id},
            },
            {
                "@id": result_id,
                "@type": "ftr:TestResult",
                "prov:wasGeneratedBy": {"@id": execution_id},
                "dct:identifier": result_id,
                "dct:title": _english(f"{definition.name} OUTPUT"),
                "dct:description": _english(f"OUTPUT OF {description}"),
                "prov:value": _english(decision.outcome),
                "prov:generatedAtTime": {
                    "@value": datetime.now(UTC).isoformat(timespec="seconds"),
                    "@type": "xsd:dateTime",
                },
                "ftr:log": _english(f"Offline Python assessment.\n{decision.message}"),
                "ftr:completion": {"@value": "100", "@type": "xsd:integer"},
                "ftr:outputFromTest": {"@id": software_id},
                "ftr:assessmentTarget": {"@id": target_id},
            },
            {
                "@id": software_id,
                "@type": ["ftr:Test", "schema:SoftwareApplication"],
                "dct:identifier": software_id,
                "dct:title": _english(definition.name),
                "dct:description": _english(description),
                "dcat:version": _english(
                    f"{definition.test_version} OutputVersion:1.1.1 "
                    f"PythonAdapter:{adapter_version}"
                ),
                "sio:SIO_000233": {"@id": definition.metric},
            },
            target,
        ],
    }
