from .adjudication import list_decisions, list_readings
from .alignment import align_steps
from .bulletins import resolve_basis
from .metrics import metric_inputs
from .sessions import get_session
from .values import now
from .verdict import classify_metrics, exact, outcome
from .zero_curve import zero_correct

ENGINE = "weightrace-linear-v1"


def working_input(db, key):
    plan, generation = get_session(db, key)
    snapshot = {"plan": plan, "generation": generation, "readings": list_readings(db, key),
                "decisions": list_decisions(db, key)}
    if plan.get("judgement") == "bulletin":
        snapshot["basis"] = resolve_basis(db, plan, now())
    return snapshot


def evaluate(snapshot):
    plan = snapshot["plan"]
    steps, chosen, issues = align_steps(plan, snapshot["readings"], snapshot["decisions"])
    result = {"engine": ENGINE, "generation": snapshot["generation"], "steps": steps, "issues": issues}
    basis = snapshot.get("basis")
    if basis is not None:
        result["basis"] = basis
    if issues:
        return {**result, "outcome": "blocked", "metrics": {}}
    if basis is not None and basis["mode"] == "bulletin" and basis.get("bulletin") is None:
        return {**result, "outcome": "blocked", "metrics": {}, "issues": [
            {"code": "missing_bulletin", "measured_on": basis["measured_on"]}]}
    corrected, drift = zero_correct(plan, chosen)
    for step in steps:
        point = corrected[step["id"]]
        step["zero"] = exact(point["zero"])
        step["corrected"] = exact(point["indication"])
        step["error"] = exact(point["error"])
    limits = basis["bulletin"]["limits_mg"] if basis is not None and basis["mode"] == "bulletin" else plan["limits_mg"]
    metrics = classify_metrics(metric_inputs(plan, corrected, drift), limits)
    return {**result, "metrics": metrics, "outcome": outcome([item["outcome"] for item in metrics.values()])}
