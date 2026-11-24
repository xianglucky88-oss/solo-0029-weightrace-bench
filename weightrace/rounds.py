from .codec import canonical, loads
from .errors import Problem
from .protocol import MAX_ROUNDS
from .standards import resolve_load
from .values import fields, now, text


def list_rounds(db, key):
    rows = db.execute("SELECT round, high_load, origin, switched_at FROM rounds WHERE session=? ORDER BY round", (key,))
    return [{"round": row["round"], "high_load": loads(row["high_load"]),
             "origin": row["origin"], "switched_at": row["switched_at"]} for row in rows]


def current_round_no(db, key):
    row = db.execute("SELECT COALESCE(MAX(round), 0) FROM rounds WHERE session=?", (key,)).fetchone()
    return row[0]


def get_round(db, key, number):
    row = db.execute("SELECT round, high_load, origin, switched_at FROM rounds WHERE session=? AND round=?",
                     (key, number)).fetchone()
    if not row:
        raise Problem("missing_round", "加载轮不存在", 404, round=number)
    return {"round": row["round"], "high_load": loads(row["high_load"]),
            "origin": row["origin"], "switched_at": row["switched_at"]}


def open_round(db, key, number, high_band, origin):
    db.execute("INSERT INTO rounds(session, round, high_load, origin, switched_at) VALUES (?, ?, ?, ?, ?)",
               (key, number, canonical(high_band), origin, now()))


def increment_band(low_band, high_band):
    """Reference mass added on top of the low band.

    An item appearing in both bands is the same physical artefact; its correction
    and radius cancel, so only high-only artefacts widen the reference increment.
    """
    low_items = {item["id"]: item for item in low_band["items"]}
    high_items = {item["id"]: item for item in high_band["items"]}
    shared = set(low_items) & set(high_items)
    added = [high_items[item_id] for item_id in sorted(set(high_items) - shared)]
    return {
        "shared_items": sorted(shared),
        "added_items": [item["id"] for item in added],
        "reference_mg": sum(item["nominal_mg"] + item["correction_mg"] for item in added),
        "radius_mg": sum(item["radius_mg"] for item in added),
    }


def validate_high_combo(db, references, measured_on, low_band):
    high_band = resolve_load(db, references, measured_on)
    low_revisions = {item["id"]: item["revision"] for item in low_band["items"]}
    for item in high_band["items"]:
        if item["id"] in low_revisions and low_revisions[item["id"]] != item["revision"]:
            raise Problem("standard_split", "同一实物在同测次不能使用不同凭据修订", id=item["id"])
    low_ids = set(low_revisions)
    high_ids = {item["id"] for item in high_band["items"]}
    # Offset substitution requires every low-gear artefact to be carried over unchanged.
    if not low_ids <= high_ids:
        missing = sorted(low_ids - high_ids)
        raise Problem("increment_carrier", "高档换用必须完整沿用低档实物，不能以独立同值砝码替代", ids=missing)
    band = increment_band(low_band, high_band)
    if band["reference_mg"] - band["radius_mg"] <= 0:
        raise Problem("increment_interval", "高档减低档的参考增量下界须严格大于零")
    return high_band, band


def switch_high(db, key, item):
    from .archives import list_releases
    from .sessions import advance, get_session, require_generation
    fields(item, "generation", "high", "reason")
    plan, generation = get_session(db, key)
    require_generation(item["generation"], generation)
    if not plan.get("increment_check"):
        raise Problem("increment_disabled", "该测次未启用升档增量检查，不能换用高档组合", 409)
    if list_releases(db, key):
        raise Problem("switch_locked", "首次整场签出后不能再换用高档组合", 409)
    number = current_round_no(db, key)
    if number >= MAX_ROUNDS - 1:
        raise Problem("round_capacity", "该测次已达到加载轮上限", 409)
    carried = {row[0] for row in db.execute(
        "SELECT DISTINCT step FROM readings WHERE session=? AND round=0 AND step IN ('zero_in', 'rise_low')",
        (key,))}
    missing_carried = sorted({"zero_in", "rise_low"} - carried)
    if missing_carried:
        raise Problem("switch_missing_carrier",
                      "换用前须已接纳首轮首空盘与升低证据，换用后这两步只能沿用不能重采", 409,
                      steps=missing_carried)
    current = get_round(db, key, number)
    low_band = plan["loads"]["low"]
    high_band, band = validate_high_combo(db, item["high"], plan["measured_on"], low_band)
    if high_band == current["high_load"]:
        raise Problem("switch_unchanged", "新高档组合与当前轮一致，无需换用", 409)
    reason = text(item["reason"], "换用说明")
    new_number = number + 1
    open_round(db, key, new_number, high_band, f"switch:{reason}")
    new_generation = advance(db, key)
    return {"round": new_number, "generation": new_generation,
            "high_load": high_band, "increment_band": band}
