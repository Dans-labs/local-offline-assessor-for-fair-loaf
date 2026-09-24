from dataclasses import replace
from importlib.resources import files

import pytest
from pydantic import TypeAdapter

from fair_offline_assessor import load_profile
from fair_offline_assessor.assessors.champion.v0_5_12.definitions import (
    load_definitions,
)
from fair_offline_assessor.models import ResourceRecord


@pytest.fixture
def champion_profile():
    root = files("fair_offline_assessor").joinpath("resources")
    refs = TypeAdapter(tuple[ResourceRecord, ...]).validate_json(
        root.joinpath("resources.json").read_bytes()
    )
    refs = tuple(r for r in refs if r.id.startswith("champion:") or r.kind == "context")
    return replace(
        load_profile("fusji-offline@3.5.1"),
        references=refs,
        resources={r.id: root.joinpath(r.path).read_bytes() for r in refs},
    )


@pytest.fixture
def definitions(champion_profile):
    return load_definitions(champion_profile)
