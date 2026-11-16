from lxml import etree
from fair_offline_assessor.models import InputError


OAI_NS = "http://www.openarchives.org/OAI/2.0/"
DATACITE_NS = "http://datacite.org/schema/kernel-4"


def unwrap_oai_datacite(xml: str) -> str:
    """Extract DataCite XML from an OAI-PMH record."""
    if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
        raise InputError("unsafe_xml", "XML entities are not permitted")

    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        recover=False,
    )

    try:
        root = etree.fromstring(xml.encode("utf-8"), parser)
    except etree.XMLSyntaxError as exc:
        raise InputError("invalid_xml", "Malformed XML") from exc

    # Already a standalone DataCite document or another XML format.
    if root.tag != f"{{{OAI_NS}}}record":
        return xml

    metadata = root.find(f"{{{OAI_NS}}}metadata")

    if metadata is None:
        raise InputError(
            "metadata_not_found",
            "OAI-PMH record contains no metadata",
        )

    children = [child for child in metadata if isinstance(child.tag, str)]

    if len(children) != 1:
        raise InputError(
            "invalid_oai_record",
            "Expected exactly one metadata payload",
        )

    resource = children[0]

    if resource.tag != f"{{{DATACITE_NS}}}resource":
        raise InputError(
            "unsupported_xml",
            "Expected DataCite Kernel 4 metadata",
        )

    return etree.tostring(resource, encoding="unicode")
