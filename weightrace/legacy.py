"""Frozen v1 computation, kept so archived releases still replay.

Version 2 splits a mid-reset session into two zero segments and widens
differences that span them.  A single-pan session yields identical numbers under
either engine, but a sealed v1 release must be replayed with the rules it was
judged under, so this module preserves them verbatim and imports nothing from
the live metric code.
"""

from fractions import Fraction

from .alignment import align_steps
from .values import instant
from .verdict import classify_metrics, exact, outcome

ENGINE = "weightrace-linear-v1"


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


def metric_inputs(plan, corrected, drift):
    # Verbatim v1: one shared anchor pair, so a difference narrows by weight only.
    half = Fraction(plan["resolution_mg"], 2)
    repeats = ("repeat_a", "repeat_b", "repeat_c")
    offsets = ("offset_left", "offset_right")
    by_id = {step["id"]: step for step in plan["steps"]}

    def error(key):
        return corrected[key]["error"]

    def difference(left, right):
        width = 2 * half * (1 + abs(corrected[left]["weight"] - corrected[right]["weight"]))
        return abs(error(left) - error(right)), width, [left, right]

    center = sum(error(key) for key in repeats) / len(repeats)
    center_weight = sum(corrected[key]["weight"] for key in repeats) / len(repeats)
    return {
        "indication": [(abs(error(key)), by_id[key]["radius_mg"] + 2 * half, [key])
                       for key in ("rise_low", "rise_high", "fall_low")],
        "hysteresis": [difference("fall_low", "rise_low")],
        "repeatability": [difference(left, right) for i, left in enumerate(repeats) for right in repeats[i+1:]],
        "eccentricity": [(abs(error(key) - center), 2 * half * (1 + abs(corrected[key]["weight"] - center_weight)),
                          [key, *repeats]) for key in offsets],
        "drift": [(abs(drift), 2 * half, ["zero_in", "zero_out"])],
    }


def evaluate(snapshot):
    plan = snapshot["plan"]
    steps, chosen, issues = align_steps(plan, snapshot["readings"], snapshot["decisions"])
    result = {"engine": ENGINE, "generation": snapshot["generation"], "steps": steps, "issues": issues}
    if issues:
        return {**result, "outcome": "blocked", "metrics": {}}
    corrected, drift = zero_correct(plan, chosen)
    for step in steps:
        point = corrected[step["id"]]
        step["zero"] = exact(point["zero"])
        step["corrected"] = exact(point["indication"])
        step["error"] = exact(point["error"])
    metrics = classify_metrics(metric_inputs(plan, corrected, drift), plan["limits_mg"])
    return {**result, "metrics": metrics, "outcome": outcome([item["outcome"] for item in metrics.values()])}
