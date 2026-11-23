from fractions import Fraction


def metric_inputs(plan, corrected, drift, multi=False):
    """Build check inputs from corrected errors.

    Legacy single-resolution sessions (``multi=False``) keep their original
    half-widths exactly so older signed releases recompute byte for byte.
    Multi-scale sessions follow the division actually used by each reading; the
    shared empty-pan anchors enter differences only through the difference of
    their interpolation weights, so their common part cancels instead of being
    counted as two independent uncertainties.
    """
    half = None if multi else Fraction(plan["resolution_mg"], 2)
    repeats = ("repeat_a", "repeat_b", "repeat_c")
    offsets = ("offset_left", "offset_right")
    by_id = {step["id"]: step for step in plan["steps"]}

    def error(key):
        return corrected[key]["error"]

    def width_of(key):
        return corrected[key]["half"] if multi else half

    def zero_between(left, right):
        # Shared zero anchors: only the change in interpolation weight widens a difference.
        anchor = corrected[left]["half_zero"] if multi else 2 * half
        return abs(corrected[left]["weight"] - corrected[right]["weight"]) * anchor

    def difference(left, right):
        width = width_of(left) + width_of(right) + zero_between(left, right)
        return abs(error(left) - error(right)), width, [left, right]

    center = sum(error(key) for key in repeats) / len(repeats)
    center_weight = sum(corrected[key]["weight"] for key in repeats) / len(repeats)
    center_half = sum(width_of(key) for key in repeats) / len(repeats)
    return {
        "indication": [(abs(error(key)),
                        by_id[key]["radius_mg"]
                        + (width_of(key) + corrected[key]["weight"] * corrected[key]["half_zero"]
                           if multi else 2 * half), [key])
                       for key in ("rise_low", "rise_high", "fall_low")],
        "hysteresis": [difference("fall_low", "rise_low")],
        "repeatability": [difference(left, right) for i, left in enumerate(repeats) for right in repeats[i+1:]],
        "eccentricity": [
            (abs(error(key) - center),
             (width_of(key) + center_half
              + abs(corrected[key]["weight"] - center_weight) * corrected[key]["half_zero"]) if multi
             else (2 * half * (1 + abs(corrected[key]["weight"] - center_weight))),
             [key, *repeats])
            for key in offsets],
        "drift": [(abs(drift),
                   corrected["zero_in"]["half"] + corrected["zero_out"]["half"] if multi else 2 * half,
                   ["zero_in", "zero_out"])],
    }
