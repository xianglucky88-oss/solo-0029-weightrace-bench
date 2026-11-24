from .codec import canonical, digest, loads
from .errors import Problem
from .protocol import CARRIED_STEPS
from .rounds import current_round_no
from .sessions import advance, get_session
from .values import fields, identifier, instant, integer, now

MAX_PACKETS = 100
MAX_READINGS = 200


def parse_packet(item, plan):
    if not isinstance(item, dict) or not {"id", "rows"} <= set(item) <= {"id", "rows", "round"}:
        required = sorted({"id", "rows"} | ({"round"} if plan.get("increment_check") else set()))
        raise Problem("fields", "字段不完整或含未知字段", expected=required)
    identifier(item["id"], "采集包编号")
    if plan.get("increment_check"):
        if "round" not in item:
            raise Problem("packet_round_missing", "启用升档增量检查的测次，采集包必须声明所属加载轮")
        packet_round = integer(item["round"], "加载轮", 0, 15)
    else:
        packet_round = item.get("round", 0)
        if packet_round != 0:
            raise Problem("packet_round_unknown", "该测次未启用加载轮，不能声明非零轮次", 409)
    rows = item["rows"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 40:
        raise Problem("packet_size", "每包须有 1 至 40 条读数")
    seen = set()
    steps = {step["id"] for step in plan["steps"]}
    for row in rows:
        fields(row, "id", "step", "observed_at", "indicated_mg")
        row_id = identifier(row["id"], "读数编号")
        if row_id in seen:
            raise Problem("duplicate_row", "包内读数编号重复", reading=row_id)
        seen.add(row_id)
        step = identifier(row["step"], "步骤编号")
        if step not in steps:
            raise Problem("step", "读数引用了不在计划内的步骤", reading=row_id)
        if packet_round and step in CARRIED_STEPS:
            raise Problem("round_carried_step", "首空盘与升低在首轮采集后由后续轮沿用，不能在新轮重采",
                          reading=row_id, step=step)
        if instant(row["observed_at"]).date().isoformat() != plan["measured_on"]:
            raise Problem("observation_day", "读数须采自计划的 UTC 日期", reading=row_id)
        value = integer(row["indicated_mg"], "原始示值", -10**10, 10**10)
        if value % plan["resolution_mg"]:
            raise Problem("resolution", "原始示值不在分度网格上", reading=row_id)
    # Package row order is transport metadata, not acquisition order.
    return {"id": item["id"], "round": packet_round,
            "rows": sorted(rows, key=lambda row: row["id"])}


def accept_packet(db, key, item):
    plan, generation = get_session(db, key)
    active_round = current_round_no(db, key)
    packet = parse_packet(item, plan)
    checksum = digest(packet)
    previous = db.execute("SELECT digest FROM packets WHERE session=? AND id=?", (key, packet["id"])).fetchone()
    if previous:
        if previous[0] != checksum:
            raise Problem("packet_conflict", "同编号采集包内容不同", 409)
        # An already accepted packet replays idempotently even when its round has been superseded.
        return {"id": packet["id"], "digest": checksum, "inserted": 0, "duplicate": True,
                "generation": generation, "round": packet["round"]}
    if plan.get("increment_check") and packet["round"] != active_round:
        raise Problem("packet_round_stale", "采集包归属的加载轮不是当前轮，旧轮读数不能混入当前轮",
                      409, round=packet["round"], current_round=active_round)
    if db.execute("SELECT COUNT(*) FROM packets WHERE session=?", (key,)).fetchone()[0] >= MAX_PACKETS:
        raise Problem("packet_capacity", "该测次已达到采集包上限", 409)
    db.execute("INSERT INTO packets VALUES (?, ?, ?, ?, ?, ?)",
               (key, packet["id"], canonical(packet), checksum, now(), packet["round"]))
    inserted = 0
    for row in packet["rows"]:
        values = (row["step"], row["observed_at"], row["indicated_mg"])
        old = db.execute("SELECT step, observed_at, indicated_mg FROM readings WHERE session=? AND id=?",
                         (key, row["id"])).fetchone()
        if old:
            if tuple(old) != values:
                raise Problem("row_conflict", "已归集的读数编号不能改写", 409, reading=row["id"])
        else:
            db.execute("INSERT INTO readings VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (key, row["id"], *values, packet["id"], packet["round"]))
            inserted += 1
    if db.execute("SELECT COUNT(*) FROM readings WHERE session=?", (key,)).fetchone()[0] > MAX_READINGS:
        raise Problem("reading_capacity", "该测次超过读数上限，整包未归集", 409)
    # Even a second origin containing only duplicate readings is new evidence, not a retry.
    return {"id": packet["id"], "digest": checksum, "inserted": inserted, "duplicate": False,
            "generation": advance(db, key), "round": packet["round"]}


def list_packets(db, key, include_payload=False):
    rows = db.execute("SELECT id, digest, accepted_at, payload, round FROM packets WHERE session=? ORDER BY id", (key,))
    return [({**item, "payload": loads(row["payload"])} if include_payload else item)
            for row in rows
            for item in ({name: row[name] for name in ("id", "digest", "accepted_at", "round")},)]
