from fractions import Fraction

from .rounds import increment_band


def metric_inputs(plan, corrected, drift, increment=None):
    half = Fraction(plan["resolution_mg"], 2)
    repeats = ("repeat_a", "repeat_b", "repeat_c")
    offsets = ("offset_left", "offset_right")
    by_id = {step["id"]: step for step in plan["steps"]}

    def error(key):
        return corrected[key]["error"]

    def difference(left, right):
        # The two zero anchors are shared; only their change in weight widens a difference.
        width = 2 * half * (1 + abs(corrected[left]["weight"] - corrected[right]["weight"]))
        return abs(error(left) - error(right)), width, [left, right]

    center = sum(error(key) for key in repeats) / len(repeats)
    center_weight = sum(corrected[key]["weight"] for key in repeats) / len(repeats)
    inputs = {
        "indication": [(abs(error(key)), by_id[key]["radius_mg"] + 2 * half, [key])
                       for key in ("rise_low", "rise_high", "fall_low")],
        "hysteresis": [difference("fall_low", "rise_low")],
        "repeatability": [difference(left, right) for i, left in enumerate(repeats) for right in repeats[i+1:]],
        "eccentricity": [(abs(error(key) - center), 2 * half * (1 + abs(corrected[key]["weight"] - center_weight)),
                          [key, *repeats]) for key in offsets],
        "drift": [(abs(drift), 2 * half, ["zero_in", "zero_out"])],
    }
    if increment is not None:
        # Corrected-indication lift minus the reference high-minus-low increment.
        # Each indication error already subtracted its own band reference, so the
        # observed lift is the error difference plus the reference increment;
        # subtract it once to obtain the signed increment error.
        lift = (corrected["rise_high"]["indication"] - corrected["rise_low"]["indication"])
        center_value = lift - Fraction(increment["reference_mg"])
        radius = Fraction(increment["radius_mg"])
        width = radius + 2 * half * (1 + abs(corrected["rise_high"]["weight"] - corrected["rise_low"]["weight"]))
        inputs["increment"] = [(center_value, width, ["rise_high", "rise_low"])]
    return inputs
