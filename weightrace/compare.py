from .archives import get_release
from .codec import digest
from .errors import Problem


def compare_releases(db, key, left_number, right_number):
    left, right = (get_release(db, key, number) for number in (left_number, right_number))
    if any(digest(record["body"]) != record["sha256"] for record in (left, right)):
        raise Problem("corrupt_release", "交付件摘要不一致，不能对账", 409)
    old, new = (record["body"]["result"] for record in (left, right))
    if old["engine"] != new["engine"]:
        raise Problem("compare_engine", "复核口径不一致，不能逐项对账", 409)
    old_steps = {step["id"]: step for step in old["steps"]}
    steps = []
    for row in new["steps"]:
        before = old_steps[row["id"]]
        if before["selected"] != row["selected"] or before["error"] != row["error"]:
            steps.append({"id": row["id"], "label": row["label"],
                          "before": {field: before[field] for field in ("selected", "error")},
                          "after": {field: row[field] for field in ("selected", "error")}})
    old_packets, new_packets = ({packet["id"] for packet in record["body"]["packets"]} for record in (left, right))
    handoffs = []
    for side, record in (("left", left), ("right", right)):
        held = record["handoff"]
        handoffs.append(None if held is None else {
            "number": held["number"], "readings": held["readings"], "confirmed_at": held["confirmed_at"]})
    return {"left": left_number, "right": right_number, "outcomes": [old["outcome"], new["outcome"]],
            "steps": steps, "metrics": [{"id": name, "before": old["metrics"][name], "after": metric}
                for name, metric in new["metrics"].items() if old["metrics"][name] != metric],
            "packets_added": sorted(new_packets - old_packets), "packets_removed": sorted(old_packets - new_packets),
            "withdrawals": [left["withdrawal"], right["withdrawal"]],
            # Two versions rest on the same confirmed rise evidence only if they
            # name the same hand-off readings; showing this keeps sign-off honest.
            "handoffs": handoffs,
            "handoff_changed": (handoffs[0] or {}).get("readings") != (handoffs[1] or {}).get("readings")}
