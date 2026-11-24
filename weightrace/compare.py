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
    return {"left": left_number, "right": right_number, "outcomes": [old["outcome"], new["outcome"]],
            "basis": [_basis_summary(left), _basis_summary(right)],
            "steps": steps, "metrics": [{"id": name, "before": old["metrics"][name], "after": metric}
                for name, metric in new["metrics"].items() if old["metrics"][name] != metric],
            "packets_added": sorted(new_packets - old_packets), "packets_removed": sorted(old_packets - new_packets),
            "withdrawals": [left["withdrawal"], right["withdrawal"]]}


def _basis_summary(record):
    basis = record["body"]["result"].get("basis")
    if basis is None or basis["mode"] == "own":
        return {"mode": "own"}
    bulletin = basis.get("bulletin")
    return {"mode": "bulletin", "bulletin_id": bulletin["id"] if bulletin else None}
