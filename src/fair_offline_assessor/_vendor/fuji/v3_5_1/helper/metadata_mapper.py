# SPDX-FileCopyrightText: 2020 PANGAEA (https://www.pangaea.de/)
#
# SPDX-License-Identifier: MIT

import enum


class Mapper(enum.Enum):
    MATURITY_LEVELS = {0: "incomplete", 1: "initial", 2: "moderate", 3: "advanced"}

    REFERENCE_METADATA_LIST = {
        "object_identifier": {"label": "Object Identifier", "sameAs": "http://purl.org/dc/terms/identifier"},
        "creator": {"label": "Creator", "sameAs": "http://purl.org/dc/terms/creator"},
        "title": {"label": "Title", "sameAs": "http://purl.org/dc/terms/title"},
        "publisher": {"label": "Publisher", "sameAs": "http://purl.org/dc/terms/publisher"},
        "publication_date": {"label": "Publication Date", "sameAs": "http://purl.org/dc/terms/date"},
        "summary": {"label": "Summary", "sameAs": "http://purl.org/dc/terms/abstract"},
        "keywords": {"label": "Keywords", "sameAs": "http://purl.org/dc/terms/subject"},
        # object_content_identifier (list) subproperties: 'url', 'type', 'size'
        "object_content_identifier": {"label": "Content (Data) Identifier", "sameAs": "https://schema.org/contentUrl"},
        "access_level": {"label": "Access Level", "sameAs": "http://purl.org/dc/terms/accessRights"},
        "access_free": {"label": "Free Access", "sameAs": "https://schema.org/isAccessibleForFree"},
        # related_resources (list) subproperties: 'relation_type', 'related_resource'
        "related_resources": {"label": "Related resources", "sameAs": "http://purl.org/dc/terms/related"},
        "provenance_general": {"label": "Provenance", "sameAs": "http://purl.org/dc/terms/provenance"},
        "measured_variable": {"label": "Measured Variable", "sameAs": "https://schema.org/variableMeasured"},
        "contributor": {"label": "Contributor", "sameAs": "http://purl.org/dc/terms/contributor"},
        "license": {"label": "License", "sameAs": "http://purl.org/dc/terms/license"},
        #'file_format_only':{'label':'File Format','sameAs':'http://purl.org/dc/terms/format'},
        "object_type": {"label": "Object Type", "sameAs": "http://purl.org/dc/terms/type"},
        "datacite_client": {"label": "DataCite Client ID", "sameAs": None},
        "modified_date": {"label": "Date Modified", "sameAs": "http://purl.org/dc/terms/modified"},
        "created_date": {"label": "Date Created", "sameAs": "http://purl.org/dc/terms/created"},
        "right_holder": {"label": "License", "sameAs": "http://purl.org/dc/terms/rightsHolder"},
        "object_size": {
            "label": "Object Size",
            "sameAs": "http://purl.org/dc/terms/extent",
        },  # in case metadata describes a single file e.g. zip file => for DC and DataCite
        "object_format": {"label": "Object Format", "sameAs": "http://purl.org/dc/terms/format"},
        "language": {"label": "Language", "sameAs": "http://purl.org/dc/terms/language"},
        # required for Github etc. software FAIR assessment
        "license_path": {"label": "License Path", "sameAs": None},
        "metadata_service": {"label": "Metadata Service", "sameAs": None},
        # spatial coverage (list of text or dict): potential subproperties: 'name' (string or URI), 'coordinates' (list), 'reference' (string or URI). Either name or coordinates MUST be there
        "coverage_spatial": {"label": "Geographical Coverage", "sameAs": "http://purl.org/dc/terms/Location"},
        # temporal coverage (list of text or dict): potential subproperties: 'name', 'date'
        "coverage_temporal": {"label": "Temporal Coverage", "sameAs": None},
    }

    REQUIRED_CORE_METADATA = [
        "creator",
        "title",
        "publisher",
        "publication_date",
        "summary",
        "keywords",
        "object_identifier",
        "object_type",
    ]

    PROVENANCE_MAPPING = {
        "contributor": "prov:wasAttributedTo",
        "creator": "prov:wasAttributedTo",
        "publisher": "prov:wasAttributedTo",
        "right_holder": "prov:wasAttributedTo",
        "created_date": "prov:generatedAtTime",
        "publication_date": "prov:generatedAtTime",
        "accepted_date": "prov:generatedAtTime",
        "submitted_date": "prov:generatedAtTime",
        "modified_date": "prov:generatedAtTime",
        "hasFormat": "prov:alternateOf",
        "isFormatOf": "prov:alternateOf",
        "isVersionOf": "prov:wasRevisionOf",
        "isNewVersionOf": "prov:wasRevisionOf",
        "isReferencedBy": "prov:hadDerivation",
        "isReplacedBy": "prov:wasRevisionOf",
        "References": "prov:wasDerivedFrom",
        "IsDerivedFrom": "prov:wasDerivedFrom",
        "isBasedOn": "prov:hadPrimarySource",
        "hasVersion": "prov:hadRevision",
        "Obsoletes": "prov:wasRevisionOf",
        "Replaces": "prov:wasDerivedFrom",
    }
