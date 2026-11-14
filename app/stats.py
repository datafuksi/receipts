"""Small-sample statistics for the metrics page."""
from math import sqrt


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score interval for a proportion (95% by default). None when n is 0."""
    if n <= 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def proportion(successes: int, n: int) -> dict:
    ci = wilson(successes, n)
    return {
        "successes": successes,
        "n": n,
        "value": (successes / n) if n else None,
        "ci95": [round(ci[0], 4), round(ci[1], 4)] if ci else None,
        # With fewer than 20 cases the interval is too wide to support a claim.
        "too_small": n < 20,
    }
