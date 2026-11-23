from .archives import get_release
from .codec import digest
from .errors import Problem
from .protocol import LIMIT_KEYS
from .sessions import get_session
from .values import fields, integer, now, text


def verify_adoptable(record, metric):
    # A takeover only ever points at one frozen release; nothing is recomputed across versions.
    if record["withdrawal"]:
        raise Problem("release_withdrawn", "已撤回的交付件不能作为接替来源", 409)
    body = record["body"]
    if digest(body) != record["sha256"]:
        raise Problem("corrupt_release", "交付件摘要不一致，不能接替", 409)
    result = body["result"]
    data = result.get("metrics", {}).get(metric)
    if result["outcome"] == "blocked" or data is None:
        raise Problem("adoption_unverifiable", "候选版未发布该分项结论，不能接替", 409)
    plan = body["input"]["plan"]
    readings = {row["id"] for row in body["input"]["readings"]}
    steps = {step["id"]: step for step in result["steps"]}
    planned = {step["id"]: step for step in plan["steps"]}
    for check in data["checks"]:
        for key in check["steps"]:
            if steps.get(key, {}).get("selected") not in readings:
                raise Problem("adoption_unverifiable", "候选版该分项所用读数不能从该版核实", 409)
            if not {"reference_mg", "radius_mg"} <= planned.get(key, {}).keys():
                raise Problem("adoption_unverifiable", "候选版该分项所用基准不能从该版核实", 409)
    if plan["limits_mg"].get(metric) != data["limit_mg"]:
        raise Problem("adoption_unverifiable", "候选版该分项限值不能从该版核实", 409)


def register_adoption(db, key, item):
    fields(item, "metric", "release", "reason", "expect_release")
    metric = item["metric"]
    if metric not in LIMIT_KEYS:
        raise Problem("adoption_metric", "接替分项须为五项判定之一")
    number = integer(item["release"], "交付版号", 1)
    reason = text(item["reason"], "接替事由")
    expect = item["expect_release"]
    if expect is not None:
        integer(expect, "预期现任版号", 1)
    get_session(db, key)
    verify_adoptable(get_release(db, key, number), metric)
    current = db.execute("""SELECT id, release, reason, registered_at FROM adoptions
        WHERE session=? AND metric=? AND superseded_at IS NULL""", (key, metric)).fetchone()
    if current and current["release"] == number:
        if current["reason"] == reason:
            return current_item(db, key, metric), False
        raise Problem("adoption_unchanged", "该分项已接替该交付件，未作更改", 409)
    if (current["release"] if current else None) != expect:
        raise Problem("adoption_conflict", "该分项的现任接替与预期不符，请核对后重新确认", 409,
                      current=({"release": current["release"], "reason": current["reason"],
                                "registered_at": current["registered_at"]} if current else None))
    timestamp = now()
    if current:
        db.execute("UPDATE adoptions SET superseded_at=?, supersede_reason=? WHERE id=?",
                   (timestamp, reason, current["id"]))
    db.execute("INSERT INTO adoptions(session, metric, release, reason, registered_at) VALUES (?, ?, ?, ?, ?)",
               (key, metric, number, reason, timestamp))
    return current_item(db, key, metric), True


def current_item(db, key, metric):
    return next(item for item in adoption_view(db, key)["current"] if item["metric"] == metric)


def adoption_view(db, key):
    rows = db.execute("""
        SELECT a.metric, a.release, a.reason, a.registered_at, a.superseded_at, a.supersede_reason,
               w.reason IS NOT NULL AS source_withdrawn
        FROM adoptions a LEFT JOIN withdrawals w ON w.session=a.session AND w.number=a.release
        WHERE a.session=? ORDER BY a.id""", (key,)).fetchall()
    active = {row["metric"]: row for row in rows if row["superseded_at"] is None}
    current = []
    for metric in LIMIT_KEYS:
        row = active.get(metric)
        if row is None:
            current.append({"metric": metric, "status": "unregistered"})
            continue
        item = {"metric": metric, "release": row["release"], "reason": row["reason"],
                "registered_at": row["registered_at"],
                "status": "pending" if row["source_withdrawn"] else "adoptable"}
        if item["status"] == "adoptable":
            outcome, limit = db.execute("SELECT json_extract(bundle, ?), json_extract(bundle, ?) FROM releases "
                                        "WHERE session=? AND number=?",
                                        (f"$.result.metrics.{metric}.outcome", f"$.result.metrics.{metric}.limit_mg",
                                         key, row["release"])).fetchone()
            item["outcome"] = outcome
            item["limit_mg"] = limit
        current.append(item)
    history = [{"metric": row["metric"], "release": row["release"], "reason": row["reason"],
                "registered_at": row["registered_at"], "superseded_at": row["superseded_at"],
                "supersede_reason": row["supersede_reason"]}
               for row in rows if row["superseded_at"] is not None]
    return {"current": current, "history": history}
