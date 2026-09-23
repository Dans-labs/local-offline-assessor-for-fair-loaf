# SPDX-FileCopyrightText: 2020 PANGAEA (https://www.pangaea.de/)
#
# SPDX-License-Identifier: MIT

import copy
import enum
import re
import extruct
from rapidfuzz import fuzz, process
from tldextract import TLDExtract

extract = TLDExtract(suffix_list_urls=(), cache_dir=None)


class MetadataHarvester:
    def merge_metadata(self, metadict, url, method, format, mimetype, schema="", namespaces=[]):
        try:
            offering_method = None
            if not isinstance(namespaces, list):
                namespaces = [namespaces]
            test_uris = namespaces
            if schema != "":
                test_uris.insert(0, schema)
            metadata_standard = self.get_metadata_standard_by_uris(test_uris)
            allow_merge = True
            if self.allowed_metadata_standards:
                if metadata_standard in self.allowed_metadata_standards:
                    allow_merge = True
                else:
                    allow_merge = False
                    self.logger.warning(
                        self.logger_target.get("metadata_properties")
                        + " : Harvesting of this metadata is explicitely disabled in the metric configuration-:"
                        + str(metadata_standard)
                    )
            if isinstance(metadict, dict) and allow_merge is True:
                # self.metadata_sources.append((method_source, 'negotiated'))
                for r in metadict.keys():
                    if r in self.reference_elements or r == "datacite_client":
                        # enforce lists
                        if r in ["keywords", "access_level", "license", "object_type"]:
                            if isinstance(metadict[r], str):
                                if r == "keywords":
                                    metadict[r] = metadict[r].split(",")
                                else:
                                    metadict[r] = [metadict[r]]

                        if self.metadata_merged.get(r):
                            msimilarity = 0
                            if isinstance(self.metadata_merged[r], str) and self.metadata_merged[r] != metadict[r]:
                                # property value similarity
                                msimilarity = fuzz.token_sort_ratio(self.metadata_merged[r], str(metadict[r]))
                                if msimilarity <= 50:
                                    self.logger.info(
                                        self.logger_target.get("metadata_properties")
                                        + " : Metadata property differs from metadata previously offered in a different formats -: "
                                        + str(r)
                                        + ": "
                                        + str(self.metadata_merged[r])[:50]
                                        + " vs. "
                                        + str(metadict[r])[:50]
                                    )

                            if isinstance(self.metadata_merged[r], list):
                                metaprop = metadict[r]
                                if isinstance(metaprop, list):
                                    self.metadata_merged[r].extend(metaprop)
                                else:
                                    self.metadata_merged[r].append(metaprop)
                                # make list unique
                                unique_merged = []
                                for e in self.metadata_merged[r]:
                                    if e not in unique_merged:
                                        unique_merged.append(e)
                                self.metadata_merged[r] = unique_merged
                            # overwrite old property value in case new one is longer but similar to the old one, otherwise keep the old one
                            elif isinstance(self.metadata_merged[r], str) and isinstance(metadict[r], str):
                                if len(self.metadata_merged[r]) < len(metadict[r]):
                                    if msimilarity > 80:
                                        self.metadata_merged[r] = metadict[r]
                        else:
                            self.metadata_merged[r] = metadict[r]
                        # self.reference_elements.pop(r)
                        # self.reference_elements.remove(r)
                if metadict.get("related_resources"):
                    self.related_resources.extend(metadict.get("related_resources"))
                # uniquify

                empty_related = [v for v in self.related_resources if not v.get("related_resource")]
                if empty_related:
                    self.logger.warning(
                        "FsF-I3-01M : Found missing link(s) to related resource(s) -: " + str(empty_related)
                    )
                try:
                    self.related_resources = list(
                        {v["related_resource"]: v for v in self.related_resources if v.get("related_resource")}.values()
                    )
                except Exception as e:
                    print("Relation uniquifiy ERROR: ", e, format, mimetype, schema, metadict.get("related_resources"))
                    pass
                if metadict.get("object_content_identifier"):
                    self.logger.info(
                        "FsF-F3-01M : Found data links in "
                        + str(format)
                        + " metadata -: "
                        + str(len(metadict.get("object_content_identifier")))
                    )
                ## add: mechanism ('content negotiation', 'typed links', 'embedded')
                ## add: format namespace
                if isinstance(method, enum.Enum):
                    if isinstance(method.value, dict):
                        offering_method = method.value.get("method").acronym()
                    method = method.name
                metadict2 = copy.deepcopy(metadict)
                mdict = dict(
                    {
                        "method": method,
                        "offering_method": offering_method,
                        "url": url,
                        "format": format.acronym(),
                        "metadata_standard": metadata_standard,
                        "mime": mimetype,
                        "schema": schema,
                        "metadata": metadict2,
                        "namespaces": namespaces,
                    }
                )
                if mdict not in self.metadata_unmerged:
                    self.metadata_unmerged.append(mdict)
        except Exception as e:
            print("Metadata Merge Error: " + str(e), format, mimetype, schema)

    def exclude_null(self, dt):
        if isinstance(dt, dict):
            return dict((k, self.exclude_null(v)) for k, v in dt.items() if v and self.exclude_null(v))
        elif isinstance(dt, list):
            try:
                return list(set([self.exclude_null(v) for v in dt if v and self.exclude_null(v)]))
            except Exception:
                return [self.exclude_null(v) for v in dt if v and self.exclude_null(v)]
        elif isinstance(dt, str):
            return dt.strip()
        else:
            return dt

    def clean_html_language_tag(self, response_content):
        # avoid RDFa errors
        try:
            langregex = r"<html\s.*lang\s*=\s*\"([^\"]+)\""
            lm = re.search(langregex, response_content)
            if lm:
                lang = lm[1]
                if not re.match(r"^[a-zA-Z]+(?:-[a-zA-Z0-9]+)*$", lang):
                    self.logger.warning(
                        self.logger_target.get("pid")
                        + " : Trying to fix invalid language tag detected in HTML -: "
                        + str(lang)
                    )
                    response_content = response_content.replace(lang, "en")
        except Exception:
            pass
        return response_content

    def retrieve_metadata_embedded_extruct(self):
        # extract contents from the landing page using extruct, which returns a dict with
        # keys 'json-ld', 'microdata', 'microformat','opengraph','rdfa'
        syntaxes = ["microdata", "opengraph", "json-ld"]
        extracted = {}
        if self.landing_html:
            try:
                extruct_target = self.landing_html.encode("utf-8")
            except Exception:
                extruct_target = self.landing_html
                pass

            try:
                self.logger.info(
                    "{} : Trying to identify EMBEDDED  Microdata, OpenGraph or Schema.org -: {}".format(
                        self.logger_target.get("metadata_properties"), self.landing_url
                    )
                )
                # remove html comments which sometimes fails in extruct...
                try:
                    extruct_target = re.sub("(<!--.*?-->)", "", extruct_target.decode("utf-8")).encode("utf-8")
                except Exception:
                    pass

                extracted = extruct.extract(extruct_target, syntaxes=syntaxes, encoding="utf-8")

            except Exception as e:
                extracted = {}
                self.extraction_failed = True
                self.logger.warning(
                    "{} : Failed to parse HTML embedded Microdata, OpenGraph or Schema.org -: {}".format(
                        self.logger_target.get("metadata_properties"), self.landing_url + " " + str(e)
                    )
                )
            if isinstance(extracted, dict):
                extracted = dict([(k, v) for k, v in extracted.items() if len(v) > 0])

                if len(extracted) == 0:
                    extracted = {}
        else:
            print("NO LANDING HTML")
        return extracted

    def lookup_metadatastandard_by_uri(self, value):
        metadata_standard_id = None
        if value:
            value = str(value).strip().strip("#/")
            # try to find it as direct match using http or https as prefix
            if value.startswith("http") or value.startswith("ftp"):
                value = value.replace("s://", "://")
                metadata_standard_id = self.COMMUNITY_METADATA_STANDARDS_URIS.get(value)
                if not metadata_standard_id:
                    metadata_standard_id = self.COMMUNITY_METADATA_STANDARDS_URIS.get(value.replace("://", "s://"))
            if not metadata_standard_id:
                # fuzzy as fall back
                try:
                    match = process.extractOne(value, self.COMMUNITY_METADATA_STANDARDS_URIS.keys())
                    if extract(str(value)).domain == extract(str(match[0])).domain:
                        req_similarity = 90
                        if "w3.org/ns" in value:
                            req_similarity = 95
                        if match[1] > req_similarity:
                            metadata_standard_id = list(self.COMMUNITY_METADATA_STANDARDS_URIS.values())[match[2]]
                except Exception as e:
                    print("METADATA STANDARD LOOKUP ERROR: ", str(e))
                    pass
        return metadata_standard_id

    def get_metadata_standard_by_uris(self, test_uris):
        metadata_standard_id = None
        if isinstance(test_uris, list):
            for uri in test_uris:
                metadata_standard_id = self.lookup_metadatastandard_by_uri(uri)
                if metadata_standard_id:
                    break
        return metadata_standard_id

    def get_metadata_standard_info(self, metadata_standard_id):
        metadata_standard_info = {}
        if metadata_standard_id:
            mstandard = self.COMMUNITY_METADATA_STANDARDS.get(metadata_standard_id)
            type = None
            subject = mstandard.get("field_of_science")
            std_ids = mstandard.get("identifier")
            metadatacatalogids = []
            for stid in std_ids:
                if stid.get("type") == "local":
                    caturi = stid.get("value")
                    if caturi.startswith("msc:"):
                        caturi = "https://rdamsc.bath.ac.uk/msc/" + caturi.split(":")[-1]
                    metadatacatalogids.append(caturi)
            if subject:
                if subject == ["sciences"] or all(elem == "Multidisciplinary" for elem in subject):
                    type = "generic"
                else:
                    type = "disciplinary"
            metadata_standard_info = {
                "id": metadata_standard_id,
                "subject": subject,
                "name": mstandard.get("title"),
                "acronym": mstandard["acronym"],
                "external_ids": std_ids,
                "type": type,
                "catalogue": metadatacatalogids,
            }
        return metadata_standard_info
