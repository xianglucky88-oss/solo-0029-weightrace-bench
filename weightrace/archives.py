from .bulletins import get_bulletin
from .codec import canonical, digest, loads
from .errors import Problem
from .evaluation import evaluate, working_input
from .intake import list_packets
from .sessions import require_generation
from .values import fields, now, text


def freeze_release(db, key, item):
    if not isinstance(item, dict) or "generation" not in item or set(item) - {"generation", "bulletin_id"}:
        raise Problem("fields", "字段不完整或含未知字段", expected=["generation", "bulletin_id"])
    snapshot = working_input(db, key)
    generation = snapshot["generation"]
    require_generation(item["generation"], generation)
    plan = snapshot["plan"]
    if plan.get("judgement") == "bulletin":
        basis = snapshot.get("basis") or {}
        current = basis.get("bulletin")
        if current is None:
            raise Problem("release_basis", "没有适用于测次日的限值公告，缺少判定依据，不能签出", 409,
                          measured_on=basis.get("measured_on"))
        seen = item.get("bulletin_id")
        if seen is None:
            raise Problem("release_basis", "按公告判定的签出须带复核员查看的公告编号", 400)
        get_bulletin(db, seen)
        if seen != current["id"]:
            raise Problem("bulletin_changed", "适用公告已变更，请重新查看最新公告后再签出", 409,
                          current=current["id"])
        basis_id = current["id"]
    else:
        if "bulletin_id" in item:
            raise Problem("fields", "自带限值的测次不按公告签出")
        basis_id = None
    old = db.execute("SELECT number FROM releases WHERE session=? AND generation=? AND basis_id IS ?",
                     (key, generation, basis_id)).fetchone()
    if old:
        return get_release(db, key, old[0]), False
    result = evaluate(snapshot)
    if result["outcome"] == "blocked":
        raise Problem("release_blocked", "存在缺步、歧义或时间倒序，不能签出", 409, issues=result["issues"])
    number = db.execute("SELECT COALESCE(MAX(number), 0)+1 FROM releases WHERE session=?", (key,)).fetchone()[0]
    published_at = now()
    body = {"format": "weightrace-evidence-v1", "session": key, "number": number,
            "published_at": published_at, "input": snapshot, "packets": list_packets(db, key, True), "result": result}
    db.execute("INSERT INTO releases(session, number, generation, published_at, digest, bundle, basis_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
               (key, number, generation, published_at, digest(body), canonical(body), basis_id))
    return get_release(db, key, number), True


def get_release(db, key, number):
    row = db.execute("""SELECT r.bundle, r.digest, r.basis_id, w.reason, w.withdrawn_at FROM releases r
        LEFT JOIN withdrawals w ON r.session=w.session AND r.number=w.number
        WHERE r.session=? AND r.number=?""", (key, number)).fetchone()
    if not row:
        raise Problem("missing_release", "交付件不存在", 404)
    return {"body": loads(row["bundle"]), "sha256": row["digest"], "basis_id": row["basis_id"], "withdrawal": (
        {"reason": row["reason"], "withdrawn_at": row["withdrawn_at"]} if row["reason"] else None)}


def list_releases(db, key):
    return [dict(row) for row in db.execute("""SELECT r.number, r.generation, r.published_at, r.digest,
        r.basis_id, json_extract(r.bundle, '$.result.outcome') AS outcome, w.reason, w.withdrawn_at
        FROM releases r LEFT JOIN withdrawals w ON r.session=w.session AND r.number=w.number
        WHERE r.session=? ORDER BY r.number DESC""", (key,))]


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
