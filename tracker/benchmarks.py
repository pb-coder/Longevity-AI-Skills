"""Small benchmark helpers used by CLI performance checks."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class BenchmarkResult:
    name: str
    runs: int
    best_s: float
    mean_s: float


def benchmark(name: str, fn: Callable[[], T], *, runs: int = 5) -> BenchmarkResult:
    """Run ``fn`` repeatedly and return best/mean wall time.

    The callable's return value is intentionally ignored; benchmark targets
    should include any correctness checks outside this helper.
    """
    if runs <= 0:
        raise ValueError("runs must be positive")
    samples: list[float] = []
    for _ in range(runs):
        start = perf_counter()
        fn()
        samples.append(perf_counter() - start)
    return BenchmarkResult(
        name=name,
        runs=runs,
        best_s=min(samples),
        mean_s=sum(samples) / len(samples),
    )
