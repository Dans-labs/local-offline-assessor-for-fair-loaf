from fair_offline_assessor import FairAssessor

result = FairAssessor().assess(
    metadata={
        "@context": "https://schema.org",
        "@type": "Dataset",
        "@id": "https://example.org/datasets/1",
        "name": "Example dataset",
        "license": "https://creativecommons.org/licenses/by/4.0/",
    }
)

print(result.model_dump_json(indent=2))
