from fractions import Fraction

from .values import instant


def zero_correct(plan, chosen, grid_mg=None):
    """Linearly interpolate the zero drift between the two empty-pan readings.

    When ``grid_mg`` is provided each reading keeps its own locked division;
    the two zero anchors are shared evidence, so their quantization uncertainty
    only widens a difference through its actual weight contribution, never twice
    independently. Without it the legacy single-resolution path is reproduced
    exactly, so older signed releases recompute byte for byte.
    """
    first = chosen["zero_in"]
    last = chosen["zero_out"]
    start = instant(first["observed_at"])
    duration = (instant(last["observed_at"]) - start).seconds
    first_mg = first["indicated_mg"]
    last_mg = last["indicated_mg"]
    drift = last_mg - first_mg
    corrected = {}
    for step in plan["steps"]:
        key = step["id"]
        row = chosen[key]
        ratio = Fraction((instant(row["observed_at"]) - start).seconds, duration)
        zero = first_mg + ratio * drift
        point = {"zero": zero, "indication": row["indicated_mg"] - zero,
                 "error": row["indicated_mg"] - zero - step["reference_mg"], "weight": ratio}
        if grid_mg is not None:
            point["half"] = Fraction(grid_mg[row["scale"]], 2)
            point["half_zero"] = (Fraction(grid_mg[first["scale"]]) + Fraction(grid_mg[last["scale"]])) / 2
        corrected[key] = point
    return corrected, drift
