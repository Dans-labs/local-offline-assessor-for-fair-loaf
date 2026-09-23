# SPDX-FileCopyrightText: 2020 PANGAEA (https://www.pangaea.de/)
#
# SPDX-License-Identifier: MIT

import enum


class AcceptTypes(enum.Enum):
    # TODO: this seems to be quite error prone..
    datacite_json = "application/vnd.datacite.datacite+json"
    datacite_xml = "application/vnd.datacite.datacite+xml"
    schemaorg = "application/vnd.schemaorg.ld+json, application/ld+json"
    html = "text/html, application/xhtml+xml"
    html_xml = "text/html, application/xhtml+xml, application/xml;q=0.5, text/xml;q=0.5, application/rdf+xml;q=0.5"
    xml = "application/xml, text/xml;q=0.5"
    # linkset = 'application/linkset+json, application/json, application/linkset'  <-- causes bug #329
    linkset = "application/linkset+json, application/linkset"
    json = "application/json, text/json;q=0.5"
    jsonld = "application/ld+json"
    atom = "application/atom+xml"
    rdfjson = "application/rdf+json"
    nt = "text/n3, application/n-triples"
    rdfxml = "application/rdf+xml, text/rdf;q=0.5, application/xml;q=0.1, text/xml;q=0.1"
    turtle = "text/ttl, text/turtle, application/turtle, application/x-turtle;q=0.6, text/n3;q=0.3, text/rdf+n3;q=0.3, application/rdf+n3;q=0.3"
    rdf = "text/turtle, application/turtle, application/x-turtle;q=0.8, application/rdf+xml, text/n3;q=0.9, text/rdf+n3;q=0.9,application/ld+json"
    default = "text/html, */*"

    @staticmethod
    def list():
        al = list(map(lambda c: c.value.split(","), AcceptTypes))
        return list(set([item.strip().split(";", 1)[0] for sublist in al for item in sublist]))
