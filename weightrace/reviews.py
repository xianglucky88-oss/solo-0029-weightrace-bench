from .codec import canonical, loads
from .errors import Problem
from .sessions import advance, get_session, require_generation
from .values import fields, identifier, now, text

DUAL_REVIEW_STEP = "offset_left"
QUORUM = 2


def offset_candidates(readings):
    # The candidate set is every reading ever assigned to the step; rows are never deleted.
    return sorted(row["id"] for row in readings if row["step"] == DUAL_REVIEW_STEP)


def review_round(readings, opinions):
    """Fold the append-only opinion log into the state of the current candidate set."""
    candidates = offset_candidates(readings)
    counted, latest = set(), {}
    for index, opinion in enumerate(opinions):
        if opinion["candidates"] == candidates:
            if opinion["reviewer"] in latest:
                counted.discard(latest[opinion["reviewer"]])
            latest[opinion["reviewer"]] = index
            counted.add(index)
    current = [opinions[index] for index in sorted(counted)]
    stale = [{**opinion, "cause": "superseded" if opinion["candidates"] == candidates else "candidates_changed"}
             for index, opinion in enumerate(opinions) if index not in counted]
    keeps = {opinion["keep"] for opinion in current}
    confirmed = len(current) >= QUORUM and len(keeps) == 1
    if confirmed:
        status = "confirmed"
    elif len(keeps) > 1:
        status = "conflict"
    elif current:
        status = "awaiting_second"
    else:
        status = "awaiting_first"
    return {"step": DUAL_REVIEW_STEP, "required": len(candidates) >= QUORUM, "candidates": candidates,
            "status": status, "selection": current[0]["keep"] if confirmed else None,
            "opinions": current, "stale": stale}


def submit_opinion(db, key, item):
    fields(item, "reviewer", "candidates", "keep", "drops", "reason", "generation")
    _, generation = get_session(db, key)
    require_generation(item["generation"], generation)
    reviewer = text(item["reviewer"], "复核员姓名", 48)
    reason = text(item["reason"], "复核说明")
    rows = db.execute("SELECT id FROM readings WHERE session=? AND step=?", (key, DUAL_REVIEW_STEP)).fetchall()
    current = sorted(row["id"] for row in rows)
    if len(current) < QUORUM:
        raise Problem("dual_review_not_required", "左偏载候选不足两条，无需双人复核", 409)
    offered = item["candidates"]
    if not isinstance(offered, list):
        raise Problem("candidates", "候选集合须为读数编号数组")
    offered = sorted(identifier(row, "候选读数") for row in offered)
    if offered != current:
        raise Problem("stale_candidates", "左偏载候选集合已变化，请按最新候选重新复核", 409, candidates=current)
    keep = identifier(item["keep"], "保留读数")
    drops = item["drops"]
    complete = isinstance(drops, list) and keep in current and \
        sorted(identifier(row, "剔除读数") for row in drops) == [row for row in current if row != keep]
    if not complete:
        raise Problem("opinion_incomplete", "意见须选定一条候选并剔除其余全部候选")
    generation = advance(db, key)
    db.execute("INSERT INTO reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
               (key, generation, reviewer, keep, canonical(sorted(drops)), canonical(current), reason, now()))
    return {"generation": generation, "reviewer": reviewer, "keep": keep}


def list_opinions(db, key):
    return [{"generation": row["generation"], "reviewer": row["reviewer"], "keep": row["keep"],
             "drops": loads(row["drops"]), "candidates": loads(row["candidates"]),
             "reason": row["reason"], "made_at": row["made_at"]}
            for row in db.execute("SELECT * FROM reviews WHERE session=? ORDER BY generation", (key,))]
