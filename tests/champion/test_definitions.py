import json
from collections import Counter
from dataclasses import replace
from hashlib import sha256

import pytest
from pydantic import ValidationError

from fair_offline_assessor import load_profile
from fair_offline_assessor.assessors.champion.v0_5_12.definitions import (
    load_definitions,
)
from fair_offline_assessor.models import ProfileError


def test_pinned_definitions_preserve_upstream_groups_and_load_independently():
    profile = load_profile("fair-champion-offline@0.5.12")
    result = load_definitions(profile)
    assert len(result.tests) == 16
    groups = Counter(t.metric for t in result.tests)
    assert len(groups) == 13
    assert {k.rsplit("/", 1)[1] for k, n in groups.items() if n == 2} == {
        "FM_A1-1_M_OpenProt",
        "FM_A1-2_M_Auth",
        "FM_R1-1_M_StdLic",
    }
    assert all(t.test_version.startswith("Hvst-0.1.17:Tst-") for t in result.tests)
    assert len({t.id for t in result.tests}) == 16
    assert set(result.policy["tests"]) == {t.id for t in result.tests}
    assert (
        result.references["data_predicates"][0] == "http://www.w3.org/ns/ldp#contains"
    )
    result.references["data_predicates"].clear()
    result.policy["tests"].clear()
    again = load_definitions(profile)
    assert again.references["data_predicates"]
    assert len(again.policy["tests"]) == 16
    with pytest.raises(ValidationError, match="frozen"):
        result.tests[0].id = "replaced"


def test_loader_rejects_changed_bytes_even_with_matching_caller_digest():
    profile = load_profile("fair-champion-offline@0.5.12")
    altered = dict(profile.resources)
    altered["champion:tests"] = json.dumps([]).encode()
    with pytest.raises(ProfileError, match="definition"):
        load_definitions(
            replace(
                profile,
                resources=altered,
                references=tuple(
                    ref.model_copy(
                        update={"digest": sha256(altered[ref.id]).hexdigest()}
                    )
                    for ref in profile.references
                ),
            )
        )
    with pytest.raises(ProfileError, match="definition"):
        load_definitions(replace(profile, references=()))
