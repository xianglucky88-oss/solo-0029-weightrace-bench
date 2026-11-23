from .errors import Problem
from .reviews import DUAL_REVIEW_STEP, QUORUM
from .sessions import advance, get_session, require_generation
from .values import fields, identifier, now, text


def record_decision(db, key, item):
    fields(item, "reading", "action", "reason", "generation")
    _, generation = get_session(db, key)
    require_generation(item["generation"], generation)
    reading = identifier(item["reading"], "读数编号")
    action = item["action"]
    if action not in ("include", "exclude"):
        raise Problem("decision", "复核决定须为剔除或复纳")
    reason = text(item["reason"], "复核说明")
    row = db.execute("SELECT step FROM readings WHERE session=? AND id=?", (key, reading)).fetchone()
    if not row:
        raise Problem("missing_reading", "读数不存在", 404)
    if row["step"] == DUAL_REVIEW_STEP and db.execute(
            "SELECT COUNT(*) FROM readings WHERE session=? AND step=?",
            (key, DUAL_REVIEW_STEP)).fetchone()[0] >= QUORUM:
        raise Problem("dual_review_required", "左偏载已有多条候选，须两名复核员一致意见，不能逐行裁决", 409)
    row = db.execute("SELECT action FROM decisions WHERE session=? AND reading=? ORDER BY generation DESC LIMIT 1",
                     (key, reading)).fetchone()
    if (row[0] if row else "include") == action:
        raise Problem("unchanged_decision", "读数已在该状态；未追加决定", 409)
    generation = advance(db, key)
    db.execute("INSERT INTO decisions VALUES (?, ?, ?, ?, ?, ?)", (key, generation, reading, action, reason, now()))
    return {"generation": generation, "reading": reading, "action": action}


def list_decisions(db, key):
    return [dict(row) for row in db.execute("""SELECT generation, reading, action, reason, made_at
        FROM decisions WHERE session=? ORDER BY generation""", (key,))]


def list_readings(db, key):
    return [dict(row) for row in db.execute("""SELECT id, step, observed_at, indicated_mg, origin_packet
        FROM readings WHERE session=? ORDER BY observed_at, id""", (key,))]
