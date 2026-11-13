"""Smoke and reproducibility checks for the single public engine."""
from fair_offline_assessor import Assessor, FairAssessor
from fair_offline_assessor.assessment import _profile
from fair_offline_assessor.assessors.fuji.checks import _parsed_catalogues, _prepared_lookups

DATASET = {
    "@context": "https://schema.org",
    "@type": "Dataset",
    "@id": "https://example.org/data/1",
    "name": "Example dataset",
    "license": "https://creativecommons.org/licenses/by/4.0/",
}


def test_one_pinned_engine_and_reproducible_results():
    engine = FairAssessor()
    first = engine.assess(metadata=DATASET)
    second = engine.assess(metadata=DATASET)
    assert first == second
    assert first == Assessor("FUJI", version="3.5.1").assess(metadata=DATASET)
    assert _profile().info.version == "3.5.1"
    assert _parsed_catalogues.cache_info().hits > 0
    assert _prepared_lookups.cache_info().hits > 0


def test_assess_many_is_lazy_and_matches_single():
    engine = FairAssessor()
    outputs = engine.assess_many([DATASET, DATASET])
    assert iter(outputs) is outputs
    a, b = outputs
    assert a == b
