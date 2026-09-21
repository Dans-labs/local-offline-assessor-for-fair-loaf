# SPDX-FileCopyrightText: 2020 PANGAEA (https://www.pangaea.de/)
#
# SPDX-License-Identifier: MIT


from fair_offline_assessor._vendor.fuji.v3_5_1.evaluators.fair_evaluator import FAIREvaluator
from fair_offline_assessor._vendor.fuji.v3_5_1.models.community_endorsed_standard import CommunityEndorsedStandard
from fair_offline_assessor._vendor.fuji.v3_5_1.models.community_endorsed_standard_output_inner import CommunityEndorsedStandardOutputInner


class FAIREvaluatorCommunityMetadata(FAIREvaluator):
    """
    A class to evaluate metadata that follows a standard recommended by the target research of the data (R.13-01M).
    A child class of FAIREvaluator.
    ...

    Methods
    -------
    evaluate()
        This method will evaluate whether the metadata follows community specific metadata standard listed in, e.g., re3data,
        or metadata follows community specific metadata standard using namespaces or schemas found in the provided metadata
        or the metadata service outputs.
    """

    def __init__(self, fuji_instance):
        self.pids_which_resolve = {}
        FAIREvaluator.__init__(self, fuji_instance)
        self.set_metric("FsF-R1.3-01M")
        self.community_standards_output = []
        self.found_metadata_standards = []
        self.valid_metadata_standards = []


    def retrieve_metadata_standards_from_namespaces(self):
        nsstandards = []
        if self.fuji.namespace_uri:
            self.logger.info(
                f"FsF-R1.3-01M : Namespaces included in the metadata -: {list(set(self.fuji.namespace_uri))}"
            )
            for nsuri in list(set(self.fuji.namespace_uri)):
                sinfo = self.get_metadata_standards_info(nsuri, "ns")
                if sinfo:
                    self.found_metadata_standards.append(sinfo)
                    if sinfo.get("type") == "disciplinary":
                        if sinfo.get("name") not in nsstandards:
                            nsstandards.append(sinfo.get("name"))
        if nsstandards:
            self.logger.info(
                "{} : Found metadata standards that are given as namespaces -: {}".format(
                    "FsF-R1.3-01M", str(set(nsstandards))
                )
            )






    def filter_community_metadata_standards(self, testid, found_metadata_standards):
        test_requirements = []
        if self.metric_tests[self.metric_identifier + str(testid)].metric_test_requirements:
            test_requirements = self.metric_tests[self.metric_identifier + str(testid)].metric_test_requirements[0]
        if test_requirements:
            community_standards = []
            if test_requirements.get("required"):
                test_required = []
                if isinstance(test_requirements.get("required"), list):
                    test_required = test_requirements.get("required")
                elif test_requirements.get("required").get("name"):
                    test_required = test_requirements.get("required").get("name")
                if not isinstance(test_required, list):
                    test_required = [test_required]
                if test_required:
                    self.logger.info(
                        "{0} : Will exclusively consider community specific metadata standards for {0}{1} which are specified in metrics -: {2}".format(
                            self.metric_identifier, str(testid), test_required
                        )
                    )
                    for rq_mstandard_id in list(test_required):
                        for kn_mstandard in found_metadata_standards:
                            # check if internal or external identifiers (RDA, fairsharing) are listed
                            if rq_mstandard_id in kn_mstandard.get(
                                "external_ids"
                            ) or rq_mstandard_id == kn_mstandard.get("id"):
                                community_standards.append(kn_mstandard.get("id"))
                    if len(community_standards) > 0:
                        self.logger.info(
                            "{} : Identifiers of community specific metadata standards found -: {}".format(
                                self.metric_identifier, community_standards
                            )
                        )
                    found_metadata_standards = [
                        x for x in found_metadata_standards if x.get("id") in community_standards
                    ]
        return found_metadata_standards

    def testMultidisciplinarybutCommunityEndorsedMetadataDetected(self):
        test_status = False
        if self.isTestDefined(self.metric_identifier + "-3"):
            test_score = self.getTestConfigScore(self.metric_identifier + "-3")
            generic_found = False
            found_metadata_standards = self.filter_community_metadata_standards("-3", self.found_metadata_standards)
            for found_standard in found_metadata_standards:
                if self.fuji.metric_helper.get_metric_version() < 0.8:
                    if found_standard.get("type") == "generic":
                        generic_found = True
                        if found_standard not in self.valid_metadata_standards:
                            self.valid_metadata_standards.append(found_standard)
                else:
                    if found_standard.get("type") == "generic" and found_standard.get("source") == "ns":
                        generic_found = True
                        if found_standard not in self.valid_metadata_standards:
                            self.valid_metadata_standards.append(found_standard)
            if generic_found:
                if self.fuji.metric_helper.get_metric_version() < 0.8:
                    self.logger.log(
                        self.fuji.LOG_SUCCESS,
                        "FsF-R1.3-01M : Found non-disciplinary standards (but RDA listed) using namespaces or schemas found in re3data record or via provided metadata or metadata services outputs",
                    )
                else:
                    self.logger.info(
                        "FsF-R1.3-01M : Found non-disciplinary standards (but RDA listed) using namespaces or schemas in provided metadata "
                    )
                self.setEvaluationCriteriumScore(self.metric_identifier + "-3", test_score, "pass")
                self.maturity = self.metric_tests.get(self.metric_identifier + "-3").metric_test_maturity_config
                self.score.earned = test_score
                test_status = True
        return test_status

    def testCommunitySpecificMetadataDetectedviaRe3Data(self):
        if self.isTestDefined(self.metric_identifier + "-2"):
            test_score = self.getTestConfigScore(self.metric_identifier + "-2")
            specific_found = False
            found_metadata_standards = self.filter_community_metadata_standards("-2", self.found_metadata_standards)
            for found_standard in found_metadata_standards:
                if found_standard.get("type") == "disciplinary" and found_standard.get("source") == "re3data":
                    specific_found = True
                    if found_standard not in self.valid_metadata_standards:
                        self.valid_metadata_standards.append(found_standard)
            if specific_found:
                self.logger.log(
                    self.fuji.LOG_SUCCESS,
                    "FsF-R1.3-01M : Found disciplinary standard listed in the re3data record of the responsible repository",
                )
                self.setEvaluationCriteriumScore(self.metric_identifier + "-2", test_score, "pass")
                self.maturity = self.metric_tests.get(self.metric_identifier + "-2").metric_test_maturity_config
                self.score.earned = test_score
                return True
        else:
            return False

    def testCommunitySpecificMetadataDetectedviaNamespaces(self):
        test_status = False
        if self.isTestDefined(self.metric_identifier + "-1"):
            test_score = self.getTestConfigScore(self.metric_identifier + "-1")
            specific_found = False
            found_metadata_standards = self.filter_community_metadata_standards("-1", self.found_metadata_standards)
            for found_standard in found_metadata_standards:
                if self.fuji.metric_helper.get_metric_version() < 0.8:
                    if found_standard.get("type") == "disciplinary" and found_standard.get("source") != "re3data":
                        specific_found = True
                        if found_standard not in self.valid_metadata_standards:
                            self.valid_metadata_standards.append(found_standard)
                else:
                    if found_standard.get("type") == "disciplinary" and found_standard.get("source") == "ns":
                        specific_found = True
                        if found_standard not in self.valid_metadata_standards:
                            self.valid_metadata_standards.append(found_standard)

            if specific_found:
                if self.fuji.metric_helper.get_metric_version() < 0.8:
                    self.logger.log(
                        self.fuji.LOG_SUCCESS,
                        "FsF-R1.3-01M : Found disciplinary standard using namespaces or schemas found in provided metadata or metadata services outputs ",
                    )
                else:
                    self.logger.log(
                        self.fuji.LOG_SUCCESS,
                        "FsF-R1.3-01M : Found disciplinary standard using namespaces or schemas found in provided metadata ",
                    )
                self.setEvaluationCriteriumScore(self.metric_identifier + "-1", test_score, "pass")
                self.maturity = self.metric_tests.get(self.metric_identifier + "-1").metric_test_maturity_config
                self.score.earned = test_score
                test_status = True
        return test_status

    def get_metadata_standards_info(self, uri, source):
        standard_found = self.fuji.metadata_harvester.lookup_metadatastandard_by_uri(uri)
        if standard_found:
            metadata_info = self.fuji.metadata_harvester.get_metadata_standard_info(standard_found)
            if metadata_info.get("type") == "generic":
                self.logger.info(
                    "FsF-R1.3-01M : Found non-disciplinary standard (but RDA listed) -: via {}:  {} - {}".format(
                        str(source), metadata_info.get("name"), uri
                    )
                )
            else:
                self.logger.info(
                    "FsF-R1.3-01M : Found disciplinary standard -: via {} : {} - {}".format(
                        str(source), metadata_info.get("name"), uri
                    )
                )
            metadata_info["uri"] = uri
            metadata_info["source"] = source
            return metadata_info
        else:
            return {}

    def evaluate(self):
        self.community_standards_output: list[CommunityEndorsedStandardOutputInner] = []

        self.retrieve_metadata_standards_from_namespaces()
        # print('FOUND STANDARDS: ',self.found_metadata_standards)
        # print('VALID STANDARDS: ',self.valid_metadata_standards)
        self.result = CommunityEndorsedStandard(
            id=self.metric_number, metric_identifier=self.metric_identifier, metric_name=self.metric_name
        )

        if self.testMultidisciplinarybutCommunityEndorsedMetadataDetected():
            self.result.test_status = "pass"
        if self.testCommunitySpecificMetadataDetectedviaRe3Data():
            self.result.test_status = "pass"
        if self.testCommunitySpecificMetadataDetectedviaNamespaces():
            self.result.test_status = "pass"
        for found_standard in self.valid_metadata_standards:
            out = CommunityEndorsedStandardOutputInner()
            out.metadata_standard = found_standard.get("name")  # use here original standard uri detected
            out.subject_areas = found_standard.get("subject")
            out.url = found_standard.get("uri")
            out.type = found_standard.get("type")
            out.source = found_standard.get("catalogue")
            self.community_standards_output.append(out)
        if not self.community_standards_output:
            self.logger.warning("FsF-R1.3-01M : Unable to determine community standard(s)")
        self.result.metric_tests = self.metric_tests
        self.result.score = self.score
        self.result.maturity = self.maturity
        self.result.output = self.community_standards_output
