import importlib
import json
from collections import Counter
from dataclasses import replace
from hashlib import sha256
from importlib.resources import files

import pytest
from pydantic import TypeAdapter, ValidationError

from fair_offline_assessor import Assessor, list_profiles, load_profile
from fair_offline_assessor.models import ProfileError, ResourceRecord


def module():
    path = files("fair_offline_assessor").joinpath(
        "assessors/champion/v0_5_12/definitions.py"
    )
    assert path.is_file(), "Champion definitions loader has not been implemented"
    return importlib.import_module(
        "fair_offline_assessor.assessors.champion.v0_5_12.definitions"
    )


def selected_profile():
    # Load data without advertising an unfinished assessor as a public profile.
    root = files("fair_offline_assessor").joinpath("resources")
    refs = TypeAdapter(tuple[ResourceRecord, ...]).validate_json(
        root.joinpath("resources.json").read_bytes()
    )
    refs = tuple(r for r in refs if r.id.startswith("champion:"))
    return replace(
        load_profile("fusji-offline@3.5.1"),
        references=refs,
        resources={r.id: root.joinpath(r.path).read_bytes() for r in refs},
    )


def test_pinned_definitions_preserve_upstream_groups_and_load_independently():
    api = module()
    profile = selected_profile()
    result = api.load_definitions(profile)
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
    again = api.load_definitions(profile)
    assert again.references["data_predicates"]
    assert len(again.policy["tests"]) == 16
    with pytest.raises(ValidationError, match="frozen"):
        result.tests[0].id = "replaced"


def test_loader_rejects_changed_bytes_even_with_matching_caller_digest():
    api = module()
    profile = selected_profile()
    altered = dict(profile.resources)
    altered["champion:tests"] = json.dumps([]).encode()
    with pytest.raises(ProfileError, match="definition"):
        api.load_definitions(
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
        api.load_definitions(replace(profile, references=()))


def test_champion_is_not_selectable_before_evaluators_are_ready():
    assert all(p.adapter != "champion" for p in list_profiles())
    with pytest.raises(ProfileError):
        Assessor("FAIR_CHAMPION", version="0.5.12")
