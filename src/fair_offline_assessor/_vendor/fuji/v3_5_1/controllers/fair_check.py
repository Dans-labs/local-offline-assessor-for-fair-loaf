# SPDX-FileCopyrightText: 2020 PANGAEA (https://www.pangaea.de/)
#
# SPDX-License-Identifier: MIT

import json


class FAIRCheck:
    def clean_metadata(self):
        # replace nasty "None" strings by real  None
        try:
            # print(self.metadata_merged)
            nonerepdict = json.dumps(self.metadata_merged).replace('"None"', "null")
            self.metadata_merged = json.loads(nonerepdict)
        except Exception as e:
            print("Nasty None replace error: ", e)
            pass
        data_objects = self.metadata_merged.get("object_content_identifier")
        if data_objects == {"url": None} or data_objects == [None]:
            data_objects = self.metadata_merged["object_content_identifier"] = None
        if data_objects is not None:
            if not isinstance(data_objects, list):
                self.metadata_merged["object_content_identifier"] = [data_objects]
        # duplicate handling
        if self.metadata_merged.get("object_content_identifier"):
            fdci = {}
            for dci in self.metadata_merged.get("object_content_identifier"):
                dcurl = dci.get("url")
                if dcurl not in fdci:
                    fdci[dcurl] = dci
                else:
                    # complete size and type
                    if not fdci[dcurl].get("type") and dci.get("type"):
                        fdci[dcurl]["type"] = dci.get("type")
                    elif dci.get("type") and fdci[dcurl].get("type"):
                        if "/" in dci.get("type") and "/" not in fdci[dcurl].get("type"):
                            fdci[dcurl]["type"] = dci.get("type")
                    if not fdci[dcurl].get("size") and dci.get("size"):
                        fdci[dcurl]["size"] = dci.get("size")
            self.metadata_merged["object_content_identifier"] = [di for di in fdci.values()]

            # if "object_content_identifier" in self.metadata_merged:
            # if self.metadata_merged.get("object_content_identifier"):
            oi = 0
            for c in self.metadata_merged["object_content_identifier"]:
                # check special case if only one file is given but a size value is available via object_size:
                if (
                    not c.get("size")
                    and self.metadata_merged.get("object_size")
                    and len(self.metadata_merged["object_content_identifier"]) == 1
                ):
                    # c["size"] = self.metadata_merged.get("object_size")
                    self.metadata_merged["object_content_identifier"][oi]["size"] = self.metadata_merged.get(
                        "object_size"
                    )
                    self.logger.info(
                        "FsF-R1-01M : File info about exactly one object found for which no size is given but since size at object level is given, will take this for file level testing"
                    )

                # clean mime types in case these are in URI form:
                if c.get("type"):
                    if isinstance(c["type"], list):
                        c["type"] = c["type"][0]
                        self.metadata_merged["object_content_identifier"][oi]["type"] = c["type"][0]
                    mime_parts = str(c.get("type")).split("/")
                    if len(mime_parts) > 2:
                        if mime_parts[-2] in [
                            "application",
                            "audio",
                            "font",
                            "example",
                            "image",
                            "message",
                            "model",
                            "multipart",
                            "text",
                            "video",
                        ]:
                            self.metadata_merged["object_content_identifier"][oi]["type"] = (
                                str(mime_parts[-2]) + "/" + str(mime_parts[-1])
                            )
                oi += 1
        # clean empty entries
        for mk, mv in list(self.metadata_merged.items()):
            if mv == "" or mv is None:
                del self.metadata_merged[mk]
