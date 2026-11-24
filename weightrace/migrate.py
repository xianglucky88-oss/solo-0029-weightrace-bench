"""Rebuild the complete reading-to-packet source map when opening a v1 database.

The old schema recorded only the first receiving packet on each reading. Every
accepted packet payload is sealed in ``packets``, so the full set of origins —
including supplementary packets that carried only already-known readings — can
be reconstructed. The rebuild runs in a single immediate transaction: either
every source is verified, rebuilt, and the schema version advances, or nothing
changes and the old database remains usable. Fixing the data and reopening is
therefore a safe, idempotent retry.
"""

from .codec import digest, loads
from .schema import SOURCES_INDEX, SOURCES_TABLE, VERSION


class MigrationError(ValueError):
    """迁移中止：旧库未改动，仍可回用。"""


def fail(message):
    raise MigrationError(f"{message}，迁移中止：旧库未改动，仍可回用")


def migrate_v1(connection):
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute(SOURCES_TABLE)
        connection.execute(SOURCES_INDEX)
        # A leftover map from an interrupted attempt is rebuilt from scratch, so
        # a retry can never count a source twice.
        connection.execute("DELETE FROM reading_sources")
        readings = {}
        for row in connection.execute(
                "SELECT session, id, step, observed_at, indicated_mg, origin_packet FROM readings"):
            readings[(row["session"], row["id"])] = row
        sources = set()
        for packet in connection.execute(
                "SELECT session, id, payload, digest FROM packets ORDER BY session, id").fetchall():
            label = f"采集包 {packet['session']}/{packet['id']}"
            try:
                payload = loads(packet["payload"])
            except ValueError:
                fail(f"{label}的封存载荷无法解析")
            if not isinstance(payload, dict) or payload.get("id") != packet["id"] \
                    or not isinstance(payload.get("rows"), list):
                fail(f"{label}的封存载荷结构不完整")
            if digest(payload) != packet["digest"]:
                fail(f"{label}的封存载荷与登记摘要不符")
            for item in payload["rows"]:
                reading = readings.get((packet["session"], item.get("id") if isinstance(item, dict) else None))
                if reading is None or (reading["step"], reading["observed_at"], reading["indicated_mg"]) != \
                        (item.get("step"), item.get("observed_at"), item.get("indicated_mg")):
                    fail(f"{label}中读数 {item.get('id') if isinstance(item, dict) else item!r} 与工作记录不符")
                sources.add((packet["session"], item["id"], packet["id"]))
        orphans = [key for key, row in readings.items() if (key[0], key[1], row["origin_packet"]) not in sources]
        if orphans:
            names = "、".join(f"{session}/{reading}" for session, reading in sorted(orphans))
            fail(f"读数 {names} 在封存采集包中找不到来源")
        connection.executemany("INSERT INTO reading_sources VALUES (?, ?, ?)", sorted(sources))
        shortfall = connection.execute("""SELECT COUNT(*) FROM readings r WHERE NOT EXISTS (
            SELECT 1 FROM reading_sources s WHERE s.session=r.session AND s.reading=r.id)""").fetchone()[0]
        if shortfall:
            fail(f"仍有 {shortfall} 条读数缺少来源")
        connection.execute(f"PRAGMA user_version = {VERSION}")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
