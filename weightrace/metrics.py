from fractions import Fraction


def metric_inputs(plan, corrected, drifts):
    half = Fraction(plan["resolution_mg"], 2)
    repeats = ("repeat_a", "repeat_b", "repeat_c")
    offsets = ("offset_left", "offset_right")
    by_id = {step["id"]: step for step in plan["steps"]}

    def error(key):
        return corrected[key]["error"]

    def difference(left, right):
        # Steps in one zero segment share their empty-pan anchors, so only the
        # change in interpolation weight widens a difference.  Steps corrected
        # against different segments share no error source: neither the zero
        # estimates nor their roundings cancel, so the interval widens fully.
        if corrected[left]["segment"] == corrected[right]["segment"]:
            width = 2 * half * (1 + abs(corrected[left]["weight"] - corrected[right]["weight"]))
        else:
            width = 4 * half
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
        # Drift is judged per zero segment against that segment's own pans; the
        # worst segment decides the whole item.
        "drift": [(abs(info["drift"]), 2 * half, info["anchors"]) for _, info in sorted(drifts.items())],
    }
