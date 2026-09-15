# SPDX-FileCopyrightText: 2020 PANGAEA (https://www.pangaea.de/)
#
# SPDX-License-Identifier: MIT

import enum


class MetadataOfferingMethods(enum.Enum):
    # HTML_EMBEDDING = {"label": "HTML Embedding", "acronym": "html_embedding"}
    META_TAGS = {"label": "HTML META Tags", "acronym": "meta_tag"}
    JSON_IN_HTML = {"label": "Embedded JSON-LD in HTML", "acronym": "json_in_html"}
    # MICRODATA_RDFA = {"label": "Microdata and RDFa", "acronym": "microdata_rdfa"}
    MICRODATA = {"label": "Microdata", "acronym": "microdata"}
    RDFA = {"label": "RDFa", "acronym": "rdfa"}
    TYPED_LINKS = {"label": "Typed Links", "acronym": "typed_links"}
    SIGNPOSTING = {"label": "Signposting Links", "acronym": "signposting"}
    CONTENT_NEGOTIATION = {"label": "Content Negotiation", "acronym": "content_negotiation"}

    def acronym(self):
        return self.value.get("acronym")

    def label(self):
        return self.value.get("label")
