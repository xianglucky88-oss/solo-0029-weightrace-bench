from fractions import Fraction


def metric_inputs(plan, corrected, drift):
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
    return {
        "indication": [(abs(error(key)), by_id[key]["radius_mg"] + 2 * half, [key])
                       for key in ("rise_low", "rise_high", "fall_low")],
        "hysteresis": [difference("fall_low", "rise_low")],
        "repeatability": [difference(left, right) for i, left in enumerate(repeats) for right in repeats[i+1:]],
        "eccentricity": [(abs(error(key) - center), 2 * half * (1 + abs(corrected[key]["weight"] - center_weight)),
                          [key, *repeats]) for key in offsets],
        "drift": [(abs(drift), 2 * half, ["zero_in", "zero_out"])],
    }
