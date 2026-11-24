from fractions import Fraction


def exact(value):
    value = Fraction(value)
    return {"mg": f"{value.numerator}/{value.denominator}", "display_mg": f"{round(value * 1000) / 1000:.3f}"}


def classify_metrics(inputs, limits):
    return {key: classify_candidates(candidates, limits[key]) for key, candidates in inputs.items()}


def classify_candidates(candidates, limit):
    checks = []
    for magnitude, radius, evidence in candidates:
        lower = max(0, magnitude - radius)
        upper = magnitude + radius
        checks.append({"center": exact(magnitude), "lower": exact(lower), "upper": exact(upper),
                       "steps": evidence, "outcome": "pass" if upper <= limit else
                       "fail" if lower > limit else "borderline"})
    return {"limit_mg": limit, "outcome": outcome([check["outcome"] for check in checks]), "checks": checks}


def outcome(values):
    return "fail" if "fail" in values else "borderline" if "borderline" in values else "pass"
