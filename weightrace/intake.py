from .codec import canonical, digest, loads
from .errors import Problem
from .sessions import advance, get_session
from .values import fields, identifier, instant, integer, now

MAX_PACKETS = 100
MAX_READINGS = 200


def parse_packet(item, plan):
    fields(item, "id", "rows")
    identifier(item["id"], "采集包编号")
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
        if identifier(row["step"], "步骤编号") not in steps:
            raise Problem("step", "读数引用了不在计划内的步骤", reading=row_id)
        if instant(row["observed_at"]).date().isoformat() != plan["measured_on"]:
            raise Problem("observation_day", "读数须采自计划的 UTC 日期", reading=row_id)
        value = integer(row["indicated_mg"], "原始示值", -10**10, 10**10)
        if value % plan["resolution_mg"]:
            raise Problem("resolution", "原始示值不在分度网格上", reading=row_id)
    # Package row order is transport metadata, not acquisition order.
    return {"id": item["id"], "rows": sorted(rows, key=lambda row: row["id"])}


def accept_packet(db, key, item):
    plan, generation = get_session(db, key)
    packet = parse_packet(item, plan)
    checksum = digest(packet)
    previous = db.execute("SELECT digest FROM packets WHERE session=? AND id=?", (key, packet["id"])).fetchone()
    if previous:
        if previous[0] != checksum:
            raise Problem("packet_conflict", "同编号采集包内容不同", 409)
        return {"id": packet["id"], "digest": checksum, "inserted": 0, "duplicate": True, "generation": generation}
    if db.execute("SELECT COUNT(*) FROM packets WHERE session=?", (key,)).fetchone()[0] >= MAX_PACKETS:
        raise Problem("packet_capacity", "该测次已达到采集包上限", 409)
    # Check every row against the working record before writing anything, so a
    # rejected packet leaves no partial packet, reading, or source behind.
    fresh = []
    for row in packet["rows"]:
        values = (row["step"], row["observed_at"], row["indicated_mg"])
        old = db.execute("SELECT step, observed_at, indicated_mg FROM readings WHERE session=? AND id=?",
                         (key, row["id"])).fetchone()
        if old:
            if tuple(old) != values:
                raise Problem("row_conflict", "已归集的读数编号不能改写", 409, reading=row["id"])
        else:
            fresh.append((row["id"], values))
    if db.execute("SELECT COUNT(*) FROM readings WHERE session=?", (key,)).fetchone()[0] + len(fresh) > MAX_READINGS:
        raise Problem("reading_capacity", "该测次超过读数上限，整包未归集", 409)
    # Packet, readings, and sources take effect inside the caller's transaction.
    db.execute("INSERT INTO packets VALUES (?, ?, ?, ?, ?)", (key, packet["id"], canonical(packet), checksum, now()))
    for reading, values in fresh:
        db.execute("INSERT INTO readings VALUES (?, ?, ?, ?, ?, ?)", (key, reading, *values, packet["id"]))
    db.executemany("INSERT INTO reading_sources VALUES (?, ?, ?)",
                   [(key, row["id"], packet["id"]) for row in packet["rows"]])
    # Even a second origin containing only duplicate readings is new evidence, not a retry.
    return {"id": packet["id"], "digest": checksum, "inserted": len(fresh), "duplicate": False,
            "generation": advance(db, key)}


def list_packets(db, key, include_payload=False):
    rows = db.execute("SELECT id, digest, accepted_at, payload FROM packets WHERE session=? ORDER BY id", (key,))
    return [({**item, "payload": loads(row["payload"])} if include_payload else item)
            for row in rows for item in ({name: row[name] for name in ("id", "digest", "accepted_at")},)]


def list_sources(db, key):
    """Map every reading of the session to all packets that carried it, oldest first."""
    rows = db.execute("""SELECT s.reading, s.packet FROM reading_sources s
        JOIN packets p ON p.session=s.session AND p.id=s.packet
        WHERE s.session=? ORDER BY s.reading, p.accepted_at, s.packet""", (key,))
    sources = {}
    for row in rows:
        sources.setdefault(row["reading"], []).append(row["packet"])
    return sources
