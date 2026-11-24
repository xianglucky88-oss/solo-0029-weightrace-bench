from .archives import get_release
from .codec import digest


def compare_releases(db, key, left_number, right_number):
    left, right = (get_release(db, key, number) for number in (left_number, right_number))
    if any(digest(record["body"]) != record["sha256"] for record in (left, right)):
        raise Problem("corrupt_release", "交付件摘要不一致，不能对账", 409)
    old, new = (record["body"]["result"] for record in (left, right))
    old_steps = {step["id"]: step for step in old["steps"]}
    steps = []
    for row in new["steps"]:
        before = old_steps[row["id"]]
        if before["selected"] != row["selected"] or before["error"] != row["error"]:
            steps.append({"id": row["id"], "label": row["label"],
                          "before": {field: before[field] for field in ("selected", "error")},
                          "after": {field: row[field] for field in ("selected", "error")}})
    old_packets, new_packets = ({packet["id"] for packet in record["body"]["packets"]} for record in (left, right))
    metric_diff = []
    for name, metric in new["metrics"].items():
        before = old["metrics"].get(name)
        if before != metric:
            metric_diff.append({"id": name, "before": before, "after": metric})
    return {"left": left_number, "right": right_number, "outcomes": [old["outcome"], new["outcome"]],
            "steps": steps, "metrics": metric_diff,
            "packets_added": sorted(new_packets - old_packets), "packets_removed": sorted(old_packets - new_packets),
            "withdrawals": [left["withdrawal"], right["withdrawal"]]}
