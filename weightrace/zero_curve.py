from fractions import Fraction

from .values import instant


def zero_correct(plan, chosen):
    first = chosen["zero_in"]
    last = chosen["zero_out"]
    start = instant(first["observed_at"])
    duration = (instant(last["observed_at"]) - start).seconds
    drift = last["indicated_mg"] - first["indicated_mg"]
    corrected = {}
    for step in plan["steps"]:
        key = step["id"]
        row = chosen[key]
        ratio = Fraction((instant(row["observed_at"]) - start).seconds, duration)
        zero = first["indicated_mg"] + ratio * drift
        corrected[key] = {"zero": zero, "indication": row["indicated_mg"] - zero,
                          "error": row["indicated_mg"] - zero - step["reference_mg"], "weight": ratio}
    return corrected, drift
