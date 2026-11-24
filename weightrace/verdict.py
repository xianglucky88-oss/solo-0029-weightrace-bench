from fractions import Fraction


def exact(value):
    value = Fraction(value)
    return {"mg": f"{value.numerator}/{value.denominator}", "display_mg": f"{round(value * 1000) / 1000:.3f}"}


def classify_metrics(inputs, limits):
    metrics = {}
    for key, candidates in inputs.items():
        limit = limits[key]
        checks = []
        for magnitude, radius, evidence in candidates:
            signed_lower = magnitude - radius
            upper = magnitude + radius
            checks.append({"center": exact(magnitude),
                           "lower": exact(max(Fraction(0), signed_lower)), "upper": exact(upper),
                           "steps": evidence, "outcome": "pass" if upper <= limit else
                           "fail" if signed_lower > limit else "borderline"})
        metrics[key] = {"limit_mg": limit, "outcome": outcome([check["outcome"] for check in checks]), "checks": checks}
    return metrics


def outcome(values):
    return "fail" if "fail" in values else "borderline" if "borderline" in values else "pass"
