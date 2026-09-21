# SPDX-FileCopyrightText: 2020 PANGAEA (https://www.pangaea.de/)
#
# SPDX-License-Identifier: MIT

from rapidfuzz import fuzz, process
from tldextract import TLDExtract

extract = TLDExtract(suffix_list_urls=(), cache_dir=None)


class MetadataHarvester:
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
