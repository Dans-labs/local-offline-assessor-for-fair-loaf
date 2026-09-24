import pytest

from fair_offline_assessor import load_profile
from fair_offline_assessor.assessors.champion.v0_5_12.definitions import (
    load_definitions,
)


@pytest.fixture
def champion_profile():
    return load_profile("fair-champion-offline@0.5.12")


@pytest.fixture
def definitions(champion_profile):
    return load_definitions(champion_profile)
