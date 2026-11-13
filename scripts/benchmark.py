"""Compare cold profile setup and successive warm-process assessment times."""
from statistics import median
from time import perf_counter

from fair_offline_assessor import FairAssessor

metadata = {
    "@context": "https://schema.org",
    "@type": "Dataset",
    "@id": "https://example.org/datasets/1",
    "name": "Example dataset",
    "license": "https://creativecommons.org/licenses/by/4.0/",
}
start = perf_counter()
a = FairAssessor()
print(f"setup: {perf_counter() - start:.3f}s")
times = []
for n in range(10):
    start = perf_counter()
    result = a.assess(metadata=metadata)
    elapsed = perf_counter() - start
    times.append(elapsed)
    print(f"assessment {n + 1:02d}: {elapsed:.3f}s ({len(result.metrics)} metrics)")
print(f"warm median (runs 2–10): {median(times[1:]):.3f}s")
