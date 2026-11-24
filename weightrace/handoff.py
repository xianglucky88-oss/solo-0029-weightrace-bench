from fractions import Fraction

from .adjudication import list_decisions, list_readings
from .alignment import align_rise_segment
from .codec import canonical, digest, loads
from .errors import Problem
from .protocol import RISE_SEGMENT
from .sessions import advance, get_session, require_generation
from .values import fields, identifier, now, text
from .verdict import classify_candidates, exact
from .zero_curve import segment_corrections

# A hand-off freezes the stepped rise evidence, never the whole result.
HANDOFF_SCOPE = "rise-segment"
CAVEAT = "确认本段证据，不代表示值分项通过，也不等于整场签出"

# Why an existing hand-off no longer binds current evidence.  These strings are
# surfaced to the reviewer, so they name a concrete cause rather than "invalid".
REASONS = {
    "reading_excluded": "交接所用读数已被剔除",
    "missing_reading": "本段缺少唯一有效读数",
    "reading_changed": "本段有效读数已不同于交接所用读数",
    "step_ambiguous": "本段出现多条有效候选，交接读数不再唯一",
    "order_changed": "本段时序不再满足交接时的顺序",
    "handoff_superseded": "复核员已重新确认交接",
    "plan_changed": "测次计划已改变，原交接不再适用",
    "reviewer_invalidated": "复核员声明交接失效",
}

RISE_KEYS = RISE_SEGMENT
PANS = ("zero_in", "zero_mid_before")
RISES = ("rise_low", "rise_high")


def plan_digest(plan):
    shape = {key: plan[key] for key in ("id", "measured_on", "resolution_mg", "mid_zero",
                                        "limits_mg", "steps") if key in plan}
    return digest(shape)


def segment_evidence(db, key, plan):
    return align_rise_segment(plan, list_readings(db, key), list_decisions(db, key))


def missing_rise_keys(plan, chosen):
    included = {step["id"] for step in plan["steps"]}
    return [name for name in RISE_KEYS if name in included and name not in chosen]


def confirm_handoff(db, key, item):
    fields(item, "generation", "reviewer", "zero_in", "rise_low", "rise_high", "zero_mid_before")
    plan, generation = get_session(db, key)
    require_generation(item["generation"], generation)
    if not plan.get("mid_zero"):
        raise Problem("not_mid_zero", "该测次未声明中途清零，不设交接", 409)
    reviewer = text(item["reviewer"], "交接复核员", 64)
    claimed = {name: identifier(item[name], f"交接读数 · {name}") for name in RISE_KEYS}
    steps, chosen, issues = segment_evidence(db, key, plan)
    if issues:
        raise Problem("handoff_blocked", "升程段证据不足或有歧义，不能交接", 409,
                      issues=issues, missing=missing_rise_keys(plan, chosen))
    selected = {name: chosen[name]["id"] for name in RISE_KEYS}
    if claimed != selected:
        raise Problem("handoff_mismatch", "交接读数须与本段唯一有效读数一致", 409, selected=selected)
    readings = {row["id"]: row for row in list_readings(db, key)}
    corrected, drifts = segment_corrections(plan, chosen)
    reference = {step["id"]: step["reference_mg"] for step in plan["steps"]}
    radius = {step["id"]: step["radius_mg"] for step in plan["steps"]}
    half = Fraction(plan["resolution_mg"], 2)
    limit = plan["limits_mg"]["indication"]
    segment_drift = drifts["rise"]
    number = db.execute("SELECT COALESCE(MAX(number), 0)+1 FROM handoffs WHERE session=?",
                        (key,)).fetchone()[0]
    generation = advance(db, key)

    def row_for(name):
        return readings[selected[name]]

    def judgement(name):
        magnitude = abs(corrected[name]["error"])
        return classify_candidates([(magnitude, radius[name] + 2 * half, [name])], limit)["checks"][0]

    document = {
        "format": "weightrace-handoff-v1", "scope": HANDOFF_SCOPE, "session": key,
        "number": number, "generation": generation, "plan_digest": plan_digest(plan),
        "reviewer": reviewer, "confirmed_at": now(), "readings": selected,
        "pans": {name: {field: row_for(name)[field] for field in
                        ("id", "observed_at", "indicated_mg", "origin_packet")} for name in PANS},
        "rise": {name: {**{field: row_for(name)[field] for field in
                           ("id", "observed_at", "indicated_mg", "origin_packet")},
                        "reference_mg": reference[name], "error": exact(corrected[name]["error"]),
                        "judgement": judgement(name)}
                 for name in RISES},
        "segment": {"id": "rise", "drift_mg": segment_drift["drift"],
                    "span_seconds": segment_drift["span_seconds"], "anchors": segment_drift["anchors"],
                    "correction": "linear between the two empty-pan readings"},
        "caveat": CAVEAT,
    }
    previous = db.execute("SELECT number FROM handoffs WHERE session=? ORDER BY number DESC LIMIT 1",
                          (key,)).fetchone()
    if previous and not _invalidation(db, key, previous["number"]):
        invalidate(db, key, previous["number"], generation, "handoff_superseded",
                   f"由 v{number} 交接重新确认")
    db.execute("""INSERT INTO handoffs(session, number, generation, plan_digest, confirmed_at, reviewer,
        zero_in, rise_low, rise_high, zero_mid_before, digest, document)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
               (key, number, generation, document["plan_digest"], document["confirmed_at"], reviewer,
                *(selected[name] for name in RISE_KEYS), digest(document), canonical(document)))
    return read_handoff(db, key, number)


def invalidate(db, key, number, generation, reason, detail):
    event = db.execute("SELECT COALESCE(MAX(event), 0)+1 FROM invalidations WHERE session=? AND number=?",
                       (key, number)).fetchone()[0]
    db.execute("INSERT INTO invalidations VALUES (?, ?, ?, ?, ?, ?, ?)",
               (key, number, event, generation, reason, detail, now()))


def record_invalidation(db, key, number, item):
    fields(item, "reason")
    detail = text(item["reason"], "失效事由")
    row = db.execute("SELECT number FROM handoffs WHERE session=? AND number=?", (key, number)).fetchone()
    if not row:
        raise Problem("missing_handoff", "交接记录不存在", 404)
    existing = _invalidation(db, key, number)
    if existing:
        if existing["reason"] == "reviewer_invalidated" and existing["detail"] == detail:
            return dict(existing)
        raise Problem("invalidated", "该交接已失效，不能改写原记录", 409)
    generation = advance(db, key)
    invalidate(db, key, number, generation, "reviewer_invalidated", detail)
    return dict(_invalidation(db, key, number))


def _invalidation(db, key, number):
    return db.execute("""SELECT * FROM invalidations WHERE session=? AND number=?
        ORDER BY event DESC LIMIT 1""", (key, number)).fetchone()


def assess(db, key, document):
    """Say whether a frozen hand-off still describes current rise evidence.

    An invalidation event is permanent: even if later adjudication restores the
    very readings the hand-off used, it must be confirmed again.
    """
    number = document["number"]
    event = _invalidation(db, key, number)
    if event:
        return {"number": number, "valid": False, "reason": event["reason"],
                "detail": event["detail"], "invalidated_at": event["invalidated_at"]}
    plan, _ = get_session(db, key)
    if not plan.get("mid_zero") or plan_digest(plan) != document["plan_digest"]:
        return {"number": number, "valid": False, "reason": "plan_changed",
                "detail": REASONS["plan_changed"]}
    steps, chosen, issues = segment_evidence(db, key, plan)
    if issues:
        codes = {issue["code"] for issue in issues}
        if "ambiguous" in codes:
            reason = "step_ambiguous"
        elif "out_of_order" in codes:
            reason = "order_changed"
        else:
            reason = "reading_excluded"
        return {"number": number, "valid": False, "reason": reason,
                "detail": REASONS[reason], "issues": issues}
    current = {name: chosen[name]["id"] for name in RISE_KEYS}
    if current != document["readings"]:
        return {"number": number, "valid": False, "reason": "reading_changed",
                "detail": REASONS["reading_changed"], "current": current}
    return {"number": number, "valid": True, "reason": None, "detail": None,
            "generation": document["generation"], "reviewer": document["reviewer"],
            "confirmed_at": document["confirmed_at"], "readings": current}


def reconcile(db, key):
    """Persist an invalidation the first time current evidence breaks a hand-off."""
    plan, generation = get_session(db, key)
    events = []
    for row in db.execute("SELECT number, document FROM handoffs WHERE session=? ORDER BY number", (key,)):
        if _invalidation(db, key, row["number"]):
            continue
        status = assess(db, key, loads(row["document"]))
        if not status["valid"]:
            invalidate(db, key, row["number"], generation, status["reason"], status["detail"])
            events.append({"number": row["number"], **status})
    return events


def active_handoff(db, key):
    row = db.execute("SELECT number, document FROM handoffs WHERE session=? ORDER BY number DESC LIMIT 1",
                     (key,)).fetchone()
    if not row:
        return None
    document = loads(row["document"])
    return {"number": row["number"], "document": document, "status": assess(db, key, document)}


def require_release_handoff(db, key, plan, result):
    """Refuse a full release that rests on rise readings no reviewer confirmed."""
    if not plan.get("mid_zero"):
        return None
    active = active_handoff(db, key)
    if not active:
        raise Problem("handoff_required", "未声明中途清零的测次须先确认并交接升程证据", 409)
    status = active["status"]
    document = active["document"]
    if not status["valid"]:
        raise Problem("handoff_invalid", "当前升程证据与有效交接不一致，须重新确认", 409,
                      reason=status["reason"], detail=status["detail"], handoff=status["number"])
    selected = {step["id"]: step.get("selected") for step in result["steps"]}
    drift = {name: selected.get(name) for name in RISE_KEYS}
    if drift != document["readings"]:
        raise Problem("handoff_mismatch", "签出所用升程读数未经复核员确认", 409,
                      confirmed=document["readings"], selected=drift)
    return active


def read_handoff(db, key, number):
    row = db.execute("SELECT digest, document FROM handoffs WHERE session=? AND number=?",
                     (key, number)).fetchone()
    if not row:
        raise Problem("missing_handoff", "交接记录不存在", 404)
    document = loads(row["document"])
    return {"number": number, "sha256": row["digest"], "scope": HANDOFF_SCOPE, "caveat": CAVEAT,
            "document": document, "status": assess(db, key, document)}


def list_handoffs(db, key):
    rows = db.execute("SELECT number FROM handoffs WHERE session=? ORDER BY number DESC", (key,))
    return [read_handoff(db, key, row["number"]) for row in rows]


def list_invalidations(db, key):
    return [dict(row) for row in db.execute(
        """SELECT number, event, generation, reason, detail, invalidated_at FROM invalidations
        WHERE session=? ORDER BY number, event""", (key,))]
