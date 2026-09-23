import json
import logging

import pytest
from pyRdfa import pyRdfa
from rdflib import Graph

from fair_offline_assessor import AssessmentInput, InputError, load_profile
from fair_offline_assessor._metadata import expand_metadata
from fair_offline_assessor._vendor.fuji.v3_5_1.helper.metadata_collector import (
    MetadataFormats,
    MetadataSources,
)
from fair_offline_assessor._vendor.fuji.v3_5_1.helper.metadata_collector_rdf import (
    MetaDataCollectorRdf,
)
from fair_offline_assessor.assessors.fuji.html import collect_html


@pytest.fixture(scope="module")
def profile():
    return load_profile("fusji-offline@3.5.1")


@pytest.fixture
def read_rdf(profile):
    types = json.loads(profile.resources["fuji:creativeworks"])["creativeworks"]

    class NoRemote:
        def get(self, *_args, **_kwargs):
            raise OSError("Remote metadata is not supplied")

    def read(document):
        if isinstance(document, Graph):
            graph = document
        else:
            expanded = expand_metadata(AssessmentInput(metadata=document), profile)
            graph = Graph().parse(data=json.dumps(expanded), format="json-ld")
        collector = MetaDataCollectorRdf(
            logging.getLogger(__name__),
            request_helper=NoRemote(),
            schema_org_creativeworks=types,
        )
        return (
            collector,
            collector.get_metadata_from_graph(graph),
            MetadataSources.RDF_NEGOTIATED,
        )

    return read


def test_html_returns_native_sources_in_upstream_order(profile, read_rdf):
    html = """<!doctype html><html
      prefix="schema: https://schema.org/ og: http://ogp.me/ns#">
      <head>
      <script type="application/ld+json">
      {"@context":"https://schema.org", "@type":"Dataset",
       "@id":"urn:jsonld", "name":"JSON-LD title"}
      </script>
      <meta name="DC.title" content="DC title">
      <meta name="citation_title" content="Highwire title">
      <meta property="og:title" content="OpenGraph title">
      </head><body>
      <div itemscope itemtype="https://schema.org/Dataset">
        <span itemprop="name">Microdata title</span>
      </div>
      <section about="urn:rdfa" typeof="schema:Dataset">
        <span property="schema:name">RDFa title</span>
      </section>
      </body></html>"""
    results = collect_html(
        AssessmentInput(metadata=html, metadata_format="html"),
        profile,
        read_rdf,
        linked_vocab_index={},
    )
    assert [(source, fields["title"]) for _, fields, source in results] == [
        (MetadataSources.SCHEMAORG_EMBEDDED, "JSON-LD title"),
        (MetadataSources.DUBLINCORE_EMBEDDED, "DC title"),
        (MetadataSources.MICRODATA_EMBEDDED, "Microdata title"),
        (MetadataSources.RDFA_EMBEDDED, "RDFa title"),
        (MetadataSources.HIGHWIRE_EPRINTS_EMBEDDED, "Highwire title"),
        (MetadataSources.OPENGRAPH_EMBEDDED, "OpenGraph title"),
    ]
    assert results[0][0].metadata_format == MetadataFormats.JSONLD
    assert results[3][0].metadata_format == MetadataFormats.RDFA


def test_unavailable_jsonld_context_keeps_other_sources_and_diagnostic(
    profile, read_rdf
):
    diagnostics = []
    html = """<html><head>
      <script type="application/ld+json">
      {"@context":"https://example.invalid/context", "@type":"Dataset"}
      </script><meta name="DC.title" content="Local title">
      </head></html>"""
    results = collect_html(
        AssessmentInput(metadata=html, metadata_format="html"),
        profile,
        read_rdf,
        linked_vocab_index={},
        diagnostics=diagnostics,
    )
    assert [(source, fields["title"]) for _, fields, source in results] == [
        (MetadataSources.DUBLINCORE_EMBEDDED, "Local title")
    ]
    assert [diagnostic.code for diagnostic in diagnostics] == ["unknown_context"]


def test_rdfa_retains_local_triples_without_fetching_remote_vocabulary(
    profile, read_rdf, monkeypatch
):
    def unexpected_fetch(*_args, **_kwargs):
        pytest.fail("RDFa attempted to retrieve an external vocabulary")

    def offline_parser(**kwargs):
        assert kwargs["options"].vocab_expansion is False
        assert kwargs["options"].vocab_cache is False
        assert kwargs["media_type"] == "text/html"
        return pyRdfa(**kwargs)

    monkeypatch.setattr("requests.get", unexpected_fetch)
    monkeypatch.setattr(
        "fair_offline_assessor.assessors.fuji.html.pyRdfa", offline_parser
    )
    html = """<html><body>
      <section about="urn:rdfa" typeof="https://schema.org/Dataset"
        vocab="https://example.invalid/vocabulary/">
        <span property="https://schema.org/name">Local RDFa</span>
        <a property="http://www.w3.org/2000/01/rdf-schema#seeAlso"
          href="https://example.invalid/ontology">Ontology</a>
      </section></body></html>"""
    results = collect_html(
        AssessmentInput(metadata=html, metadata_format="html"),
        profile,
        read_rdf,
        linked_vocab_index={},
    )
    rdfa = next(
        fields
        for _, fields, source in results
        if source == MetadataSources.RDFA_EMBEDDED
    )
    assert rdfa["title"] == "Local RDFa"


def test_html_never_parses_embedded_rdfxml_or_external_entities(
    profile, read_rdf, monkeypatch, tmp_path
):
    def unexpected_xml(*_args, **_kwargs):
        pytest.fail("HTML invoked an XML document parser")

    monkeypatch.setattr("xml.dom.minidom.parse", unexpected_xml)
    monkeypatch.setattr(
        "rdflib.plugins.parsers.rdfxml.RDFXMLParser.parse", unexpected_xml
    )
    secret = tmp_path / "secret.txt"
    secret.write_text("Must not be read")
    html = f'''<!DOCTYPE html [<!ENTITY external SYSTEM "{secret.as_uri()}">]>
      <html prefix="s: https://schema.org/"><head>
      <script type="application/rdf+xml">
        <!DOCTYPE rdf:RDF [<!ENTITY external SYSTEM "{secret.as_uri()}">]>
        <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
          xmlns:s="https://schema.org/">
          <s:Dataset rdf:about="urn:external"><s:name>&external;</s:name>
          </s:Dataset></rdf:RDF>
      </script></head><body>
      <div about="urn:local" typeof="s:Dataset">
      <span property="s:name">Local title</span></div>
      </body></html>'''
    results = collect_html(
        AssessmentInput(metadata=html, metadata_format="html"),
        profile,
        read_rdf,
        linked_vocab_index={},
    )
    assert [(source, fields["title"]) for _, fields, source in results] == [
        (MetadataSources.RDFA_EMBEDDED, "Local title")
    ]


def test_rdfa_reader_failure_keeps_later_native_sources(profile):
    def unreadable(_document):
        raise InputError("unsupported_metadata", "No readable RDF subject")

    diagnostics = []
    html = """<html prefix="s: https://schema.org/"><head>
      <meta name="citation_title" content="Highwire title"></head><body>
      <div about="urn:rdfa" typeof="s:Dataset">
      <span property="s:name">RDFa title</span></div></body></html>"""
    results = collect_html(
        AssessmentInput(metadata=html, metadata_format="html"),
        profile,
        unreadable,
        linked_vocab_index={},
        diagnostics=diagnostics,
    )
    assert [(source, fields["title"]) for _, fields, source in results] == [
        (MetadataSources.HIGHWIRE_EPRINTS_EMBEDDED, "Highwire title")
    ]
    assert [diagnostic.code for diagnostic in diagnostics] == ["unsupported_metadata"]


def test_rdfa_uses_native_image_subject_filter(profile, read_rdf):
    html = """<html prefix="s: https://schema.org/"><body>
      <section about="https://example.org/image.jpg" typeof="s:Dataset">
        <span property="s:name">Image title</span>
        <span property="s:description">Many image properties</span>
        <span property="s:keywords">Image</span>
      </section>
      <section about="urn:dataset" typeof="s:Dataset">
        <span property="s:name">Dataset title</span>
      </section></body></html>"""
    results = collect_html(
        AssessmentInput(metadata=html, metadata_format="html"),
        profile,
        read_rdf,
        linked_vocab_index={},
    )
    assert [(source, fields["title"]) for _, fields, source in results] == [
        (MetadataSources.RDFA_EMBEDDED, "Dataset title")
    ]


def test_rdfa_applies_native_invalid_language_repair(profile, read_rdf):
    html = """<html lang="invalid language" prefix="s: https://schema.org/">
      <body><div about="urn:data" typeof="s:Dataset">
      <span property="s:name">Language example</span></div></body></html>"""
    results = collect_html(
        AssessmentInput(metadata=html, metadata_format="html"),
        profile,
        read_rdf,
        linked_vocab_index={},
    )
    assert [(source, fields["title"]) for _, fields, source in results] == [
        (MetadataSources.RDFA_EMBEDDED, "Language example")
    ]


def test_html_without_embedded_metadata_has_no_sources(profile, read_rdf):
    assert not collect_html(
        AssessmentInput(metadata="<html><body>Only prose</body></html>"),
        profile,
        read_rdf,
        linked_vocab_index={},
    )


def test_html_requires_document_text(profile, read_rdf):
    with pytest.raises(InputError) as error:
        collect_html(
            AssessmentInput(metadata={"title": "Not HTML text"}),
            profile,
            read_rdf,
            linked_vocab_index={},
        )
    assert error.value.code == "unsupported_input"
