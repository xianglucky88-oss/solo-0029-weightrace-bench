from .codec import canonical, digest, loads
from .errors import Problem
from .evaluation import evaluate, working_input
from .handoff import require_release_handoff
from .intake import list_packets
from .sessions import require_generation
from .values import fields, now, text


def freeze_release(db, key, item):
    fields(item, "generation")
    snapshot = working_input(db, key)
    generation = snapshot["generation"]
    expected = item["generation"]
    require_generation(expected, generation)
    old = db.execute("SELECT number FROM releases WHERE session=? AND generation=?", (key, generation)).fetchone()
    if old:
        return get_release(db, key, old[0]), False
    result = evaluate(snapshot)
    if result["outcome"] == "blocked":
        raise Problem("release_blocked", "存在缺步、歧义或时间倒序，不能签出", 409, issues=result["issues"])
    # A segmented session may only be signed off when the rise evidence it
    # signs matches the hand-off a reviewer actually confirmed.
    handoff = require_release_handoff(db, key, snapshot["plan"], result)
    number = db.execute("SELECT COALESCE(MAX(number), 0)+1 FROM releases WHERE session=?", (key,)).fetchone()[0]
    published_at = now()
    body = {"format": "weightrace-evidence-v1", "session": key, "number": number,
            "published_at": published_at, "input": snapshot, "packets": list_packets(db, key, True),
            "result": result, "handoff": handoff}
    db.execute("INSERT INTO releases VALUES (?, ?, ?, ?, ?, ?)",
               (key, number, generation, published_at, digest(body), canonical(body)))
    return get_release(db, key, number), True


def get_release(db, key, number):
    row = db.execute("""SELECT r.bundle, r.digest, w.reason, w.withdrawn_at FROM releases r
        LEFT JOIN withdrawals w ON r.session=w.session AND r.number=w.number
        WHERE r.session=? AND r.number=?""", (key, number)).fetchone()
    if not row:
        raise Problem("missing_release", "交付件不存在", 404)
    body = loads(row["bundle"])
    handoff = body.get("handoff")
    return {"body": body, "sha256": row["digest"], "withdrawal": (
        {"reason": row["reason"], "withdrawn_at": row["withdrawn_at"]} if row["reason"] else None),
        "handoff": None if handoff is None else {
            "number": handoff["number"], "confirmed_at": handoff["document"]["confirmed_at"],
            "reviewer": handoff["document"]["reviewer"], "readings": handoff["document"]["readings"],
            "status": handoff["status"]}}


def list_releases(db, key):
    rows = db.execute("""SELECT r.number, r.generation, r.published_at, r.digest,
        json_extract(r.bundle, '$.result.outcome') AS outcome, w.reason, w.withdrawn_at,
        json_extract(r.bundle, '$.handoff.number') AS handoff_number,
        json_extract(r.bundle, '$.handoff.document.reviewer') AS handoff_reviewer
        FROM releases r LEFT JOIN withdrawals w ON r.session=w.session AND r.number=w.number
        WHERE r.session=? ORDER BY r.number DESC""", (key,))
    return [_release_row(row) for row in rows]


def _release_row(row):
    record = {name: row[name] for name in ("number", "generation", "published_at", "digest",
                                           "outcome", "reason", "withdrawn_at")}
    record["handoff"] = None if row["handoff_number"] is None else {
        "number": row["handoff_number"], "reviewer": row["handoff_reviewer"]}
    return record


def withdraw_release(db, key, number, item):
    fields(item, "reason")
    reason = text(item["reason"], "撤回事由")
    record = get_release(db, key, number)
    if record["withdrawal"]:
        if record["withdrawal"]["reason"] == reason:
            return record["withdrawal"]
        raise Problem("withdrawn", "已经撤回，不能覆盖原事由", 409)
    timestamp = now()
    db.execute("INSERT INTO withdrawals VALUES (?, ?, ?, ?)", (key, number, reason, timestamp))
    return {"reason": reason, "withdrawn_at": timestamp}
