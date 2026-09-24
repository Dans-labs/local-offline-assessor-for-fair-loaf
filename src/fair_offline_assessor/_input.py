import json
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256

from pydantic import ValidationError
from pydantic_core import to_jsonable_python

from fair_offline_assessor.models import AssessmentInput, Diagnostic


@dataclass(frozen=True)
class PreparedInput:
    request: AssessmentInput
    digest: str
    invalid: dict[str, Diagnostic]


def digest_input(values: Mapping[str, object]) -> str:
    """Hash complete evidence using the existing canonical input representation."""
    content = json.dumps(
        to_jsonable_python(values),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8", errors="surrogatepass")
    return sha256(content).hexdigest()


def prepare_input(request: AssessmentInput | Mapping[str, object]) -> PreparedInput:
    """Validate each evidence field, retaining invalid input in the digest."""
    defaults: dict[str, object] = {
        "metadata": {},
        "metadata_format": None,
        "subject": None,
        "metadata_url": None,
        "local_contexts": {},
    }
    original = defaults | (
        request.model_dump() if isinstance(request, AssessmentInput) else dict(request)
    )
    digest = digest_input(original)
    invalid = {}
    values = dict(original)
    metadata = values["metadata"]
    try:
        json.dumps(metadata, allow_nan=False, ensure_ascii=False).encode()
    except (ValueError, TypeError):
        invalid["metadata"] = Diagnostic(
            code="invalid_json",
            message="Metadata must contain valid, finite JSON values.",
            location="/metadata",
        )
    else:
        if not isinstance(metadata, (dict, str)) and not (
            isinstance(metadata, list) and all(isinstance(n, dict) for n in metadata)
        ):
            invalid["metadata"] = Diagnostic(
                code="unsupported_input",
                message="Supply a metadata object, array of objects, or document text.",
                location="/metadata",
            )
    values["metadata"] = {} if "metadata" in invalid else metadata
    for name in ("metadata_format", "subject", "metadata_url", "local_contexts"):
        try:
            json.dumps(
                to_jsonable_python(values[name]), allow_nan=False, ensure_ascii=False
            ).encode()
        except (ValueError, TypeError):
            invalid[name] = Diagnostic(
                code=f"invalid_{name}",
                message="Evidence must contain valid, finite JSON values.",
                location=f"/{name}",
            )
            values[name] = defaults[name]
    try:
        validated = AssessmentInput.model_validate(values)
    except ValidationError as exc:
        for error in exc.errors(include_input=False, include_context=False):
            name = str(error["loc"][0])
            location = "/" + "/".join(
                str(part).replace("~", "~0").replace("/", "~1") for part in error["loc"]
            )
            invalid.setdefault(
                name,
                Diagnostic(
                    code=f"invalid_{name}", message=error["msg"], location=location
                ),
            )
            if name in defaults:
                values[name] = defaults[name]
            else:
                values.pop(name, None)
        validated = AssessmentInput.model_validate(values)
    return PreparedInput(validated, digest, invalid)
