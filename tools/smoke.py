"""Exercise the shipped HTTP workflows on a throwaway local database."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from weightrace.archives import freeze_release, get_release, withdraw_release
from weightrace.codec import canonical, digest
from weightrace.database import Database
from weightrace.demo import demo_data
from weightrace.errors import Problem
from weightrace.export import export_release
from weightrace.httpd import WorkbenchServer
from weightrace.intake import accept_packet, list_sources
from weightrace.migrate import MigrationError
from weightrace.replay import replay
from weightrace.sessions import create_session
from weightrace.standards import register_standard
from weightrace.values import now

WORKFLOWS = ("catalog", "plan", "ingest", "evaluate", "freeze", "review", "compare", "replay", "export", "withdraw",
             "sources", "migrate")

# The structure the pre-migration intake wrote: each reading named only the
# first packet that carried it, and no source map existed at all.
LEGACY_SCHEMA = """
CREATE TABLE standards (
    id TEXT NOT NULL, revision INTEGER NOT NULL, document TEXT NOT NULL,
    PRIMARY KEY (id, revision)
);
CREATE TABLE sessions (
    id TEXT PRIMARY KEY, plan TEXT NOT NULL, generation INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE packets (
    session TEXT NOT NULL REFERENCES sessions ON DELETE RESTRICT,
    id TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL, accepted_at TEXT NOT NULL,
    PRIMARY KEY (session, id)
);
CREATE TABLE readings (
    session TEXT NOT NULL REFERENCES sessions ON DELETE RESTRICT,
    id TEXT NOT NULL, step TEXT NOT NULL, observed_at TEXT NOT NULL, indicated_mg INTEGER NOT NULL,
    origin_packet TEXT NOT NULL, PRIMARY KEY (session, id),
    FOREIGN KEY (session, origin_packet) REFERENCES packets(session, id)
);
CREATE INDEX readings_step ON readings(session, step, observed_at);
CREATE TABLE decisions (
    session TEXT NOT NULL, generation INTEGER NOT NULL, reading TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('exclude', 'include')),
    reason TEXT NOT NULL, made_at TEXT NOT NULL, PRIMARY KEY (session, generation),
    FOREIGN KEY (session, reading) REFERENCES readings(session, id)
);
CREATE INDEX decisions_reading ON decisions(session, reading, generation);
CREATE TABLE releases (
    session TEXT NOT NULL REFERENCES sessions ON DELETE RESTRICT,
    number INTEGER NOT NULL, generation INTEGER NOT NULL, published_at TEXT NOT NULL,
    digest TEXT NOT NULL, bundle TEXT NOT NULL,
    PRIMARY KEY (session, number), UNIQUE (session, generation)
);
CREATE TABLE withdrawals (
    session TEXT NOT NULL, number INTEGER NOT NULL, reason TEXT NOT NULL, withdrawn_at TEXT NOT NULL,
    PRIMARY KEY (session, number), FOREIGN KEY (session, number) REFERENCES releases(session, number)
);
"""


def legacy_accept(connection, key, packet):
    """Replicate the old intake: a later packet of known readings left no trace."""
    rows = sorted(packet["rows"], key=lambda row: row["id"])
    normalized = {"id": packet["id"], "rows": rows}
    connection.execute("INSERT INTO packets VALUES (?, ?, ?, ?, ?)",
                       (key, packet["id"], canonical(normalized), digest(normalized), now()))
    for row in rows:
        if not connection.execute("SELECT 1 FROM readings WHERE session=? AND id=?", (key, row["id"])).fetchone():
            connection.execute("INSERT INTO readings VALUES (?, ?, ?, ?, ?, ?)",
                               (key, row["id"], row["step"], row["observed_at"], row["indicated_mg"], packet["id"]))
    connection.execute("UPDATE sessions SET generation=generation+1 WHERE id=?", (key,))


def build_legacy(path):
    """Create a version 1 database exactly as the old intake would have left it."""
    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(LEGACY_SCHEMA)
    data = demo_data()
    key = data["session"]["id"]
    for standard in data["standards"]:
        register_standard(connection, standard)
    create_session(connection, data["session"])
    create_session(connection, {**data["session"], "id": "LINDEN-0919"})
    for packet in data["packets"]:
        legacy_accept(connection, key, packet)
    freeze_release(connection, key, {"generation": 2})
    withdraw_release(connection, key, 1, {"reason": "换库前登记撤回"})
    original_file = export_release(connection, key, 1)[0]
    # The last packet confirmed before the switch carries only known readings.
    legacy_accept(connection, key, {"id": "LINDEN-LOGGER-RE",
                                    "rows": [data["packets"][1]["rows"][0], data["packets"][0]["rows"][0]]})
    # Another session reusing the same packet and reading numbers.
    legacy_accept(connection, "LINDEN-0919", {"id": "LINDEN-LOGGER-A", "rows": [data["packets"][1]["rows"][0]]})
    connection.execute("PRAGMA user_version = 1")
    connection.close()
    return original_file


def exercise(port, stop):
    base = f"http://127.0.0.1:{port}"
    d = demo_data()
    key = d["session"]["id"]
    session = f"sessions/{key}"

    def api(path, data=None, *, status=200, error=None, binary=False):
        body = data if isinstance(data, bytes) else None if data is None else json.dumps(data).encode()
        request = Request(f"{base}/weightrace/api/{path}", body, {"Content-Type": "application/json"})
        try:
            response = urlopen(request, timeout=4)
        except HTTPError as exc:
            response = exc
        with response:
            payload = response.read()
            assert response.status == status, (path, response.status, payload[:400])
            if binary:
                assert response.headers["Content-Disposition"].startswith("attachment;")
                return payload
        result = json.loads(payload)
        if error:
            assert result["error"] == error, result
        return result

    def done(workflow):
        print(f"PASS {workflow}")
        return workflow == stop

    for standard in d["standards"]:
        assert api("standards", standard, status=201) == standard
        assert api("standards", standard) == standard
    original = d["standards"][0]
    api("standards", {**original, "correction_mg": 4}, status=409, error="standard_conflict")
    assert api("standards") == d["standards"]
    if done("catalog"):
        return

    api("sessions", {**d["session"], "measured_on": "2027-01-01"}, status=400, error="expired_standard")
    plan = api("sessions", d["session"], status=201)
    api("standards", {**original, "revision": 2, "correction_mg": 9}, status=201)
    assert api(session)["plan"] == plan and len(plan["steps"]) == 10
    if done("plan"):
        return

    packets = f"{session}/packets"
    first, second = d["packets"]
    assert api(packets, first, status=201)["generation"] == 1
    assert api(session)["result"]["outcome"] == "blocked"
    duplicate = api(packets, {**first, "rows": first["rows"][::-1]})
    assert duplicate["duplicate"] and duplicate["generation"] == 1
    bad = {"id": "ROLLBACK", "rows": [{**second["rows"][0], "id": "A-ROLLBACK"},
                                      {**first["rows"][0], "indicated_mg": 300014}]}
    api(packets, bad, status=409, error="row_conflict")
    api(packets, b'{"id":"a","id":"b","rows":[]}', status=400, error="json")
    view = api(session)
    assert len(view["packets"]) == 1
    assert "A-ROLLBACK" not in view["sources"] and view["sources"]["LINDEN-05"] == ["LINDEN-LOGGER-B"]
    assert api(packets, second, status=201)["generation"] == 2
    if done("ingest"):
        return

    result = api(session)["result"]
    assert len(result["steps"]) == 10 and all(x["state"] == "matched" for x in result["steps"])
    assert all(x["id"] != "A-ROLLBACK" for step in result["steps"] for x in step["candidates"])
    assert result["metrics"]["drift"]["checks"][0]["upper"]["mg"] == "11/1"
    assert result["outcome"] == "borderline"
    other = deepcopy(d["session"])
    other["id"] = "ORDER-CHECK"
    api("sessions", other, status=201)
    mistimed = deepcopy(second)
    mistimed["rows"][1]["observed_at"] = mistimed["rows"][0]["observed_at"]
    api("sessions/ORDER-CHECK/packets", {**first, "id": "ORDER-A"}, status=201)
    api("sessions/ORDER-CHECK/packets", {**mistimed, "id": "ORDER-B"}, status=201)
    assert api("sessions/ORDER-CHECK")["result"]["issues"][0]["code"] == "out_of_order"
    if done("evaluate"):
        return

    releases = f"{session}/releases"
    r1 = api(releases, {"generation": 2}, status=201)
    assert api(releases, {"generation": 2}) == r1
    late = Path(__file__).resolve().parents[1] / "examples" / "linden-late.json"
    api(packets, late.read_bytes(), status=201)
    api(releases, {"generation": 3}, status=409, error="release_blocked")
    if done("freeze"):
        return

    decisions = f"{session}/decisions"
    decision = {"reading": "LINDEN-08", "action": "exclude", "reason": "采用复测行", "generation": 2}
    api(decisions, decision, status=409, error="stale_generation")
    assert api(decisions, {**decision, "generation": 3}, status=201)["generation"] == 4
    assert api(session)["result"]["outcome"] == "fail"
    api(decisions, {**decision, "action": "include", "generation": 4}, status=201)
    assert api(session)["result"]["outcome"] == "blocked"
    api(decisions, {**decision, "generation": 5}, status=201)
    if done("review"):
        return

    r2 = api(releases, {"generation": 6}, status=201)
    assert r2["body"]["number"] == 2
    diff = api(f"{session}/compare?left=1&right=2")
    assert diff["outcomes"] == ["borderline", "fail"] and diff["packets_added"] == ["LINDEN-LOGGER-C"]
    assert [x["id"] for x in diff["steps"]] == ["offset_left"]
    api(f"{session}/compare?left=1&right=3", status=404, error="missing_release")
    if done("compare"):
        return

    assert api(f"{releases}/1/replay")["verified"] and api(f"{releases}/2/replay")["verified"]
    assert api(f"{releases}/1") == r1
    api(f"{releases}/3/replay", status=404, error="missing_release")
    if done("replay"):
        return

    path = f"{releases}/2/file"
    original_file = api(path, binary=True)
    assert json.loads(original_file) == {"body": r2["body"], "sha256": r2["sha256"]}
    api(f"{releases}/3/file", status=404, error="missing_release")
    if done("export"):
        return

    action = f"{releases}/2/withdraw"
    reason = {"reason": "外部复核撤回"}
    withdrawal = api(action, reason)
    assert withdrawal == api(action, reason)
    api(action, {"reason": "更改事由"}, status=409, error="withdrawn")
    assert api(session)["state"] == "withdrawn" and api(releases, {"generation": 6})["withdrawal"] == withdrawal
    assert api(path, binary=True) == original_file and api(f"{releases}/2/replay")["verified"]
    if done("withdraw"):
        return

    # A supplementary packet carrying only known readings is a real new origin.
    supplement = {"id": "LINDEN-LOGGER-RE", "rows": [first["rows"][0], second["rows"][0]]}
    relay = api(packets, supplement, status=201)
    assert relay["inserted"] == 0 and not relay["duplicate"] and relay["generation"] == 7
    sources = api(session)["sources"]
    assert sources["LINDEN-01"] == ["LINDEN-LOGGER-A", "LINDEN-LOGGER-RE"]
    assert sources["LINDEN-05"] == ["LINDEN-LOGGER-B", "LINDEN-LOGGER-RE"]
    assert sources["LINDEN-08-SECOND"] == ["LINDEN-LOGGER-C"]
    # Resending the same packet is not a third origin.
    assert api(packets, {**supplement, "rows": supplement["rows"][::-1]})["duplicate"]
    assert api(session)["sources"]["LINDEN-01"] == ["LINDEN-LOGGER-A", "LINDEN-LOGGER-RE"]
    # Another session reusing the same reading numbers never leaks in.
    assert api("sessions/ORDER-CHECK")["sources"]["LINDEN-01"] == ["ORDER-B"]
    assert api(session)["sources"]["LINDEN-01"] == ["LINDEN-LOGGER-A", "LINDEN-LOGGER-RE"]
    # A packet rejected for rewriting a reading leaves no partial sources.
    rewrite = {"id": "REWRITE", "rows": [{**first["rows"][1], "id": "RE-NEW"},
                                         {**first["rows"][0], "indicated_mg": 300014}]}
    api(packets, rewrite, status=409, error="row_conflict")
    view = api(session)
    assert view["generation"] == 7 and "RE-NEW" not in view["sources"]
    assert all(packet["id"] != "REWRITE" for packet in view["packets"])
    # Origins arriving later never enter already signed artifacts.
    assert api(path, binary=True) == original_file
    assert api(f"{releases}/1/replay")["verified"] and api(f"{releases}/2/replay")["verified"]
    assert api(f"{releases}/2")["withdrawal"] == withdrawal
    for number in (1, 2):
        assert all(packet["id"] != "LINDEN-LOGGER-RE" for packet in api(f"{releases}/{number}")["body"]["packets"])
    if done("sources"):
        return


def exercise_migration():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "legacy.sqlite3"
        key = "LINDEN-0918"
        original_file = build_legacy(path)
        db = Database(path)
        with db.transaction(write=True) as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
            sources = list_sources(connection, key)
            # Both origins of a shared reading are found, including the last
            # packet confirmed before the switch; the other session stays apart.
            assert sources["LINDEN-01"] == ["LINDEN-LOGGER-A", "LINDEN-LOGGER-RE"]
            assert sources["LINDEN-05"] == ["LINDEN-LOGGER-B", "LINDEN-LOGGER-RE"]
            assert sources["LINDEN-10"] == ["LINDEN-LOGGER-B"]
            assert list_sources(connection, "LINDEN-0919") == {"LINDEN-01": ["LINDEN-LOGGER-A"]}
            # Signed artifacts keep bytes, replay, and withdrawal; the later
            # supplementary origin is not stuffed into the historical bundle.
            record = get_release(connection, key, 1)
            assert export_release(connection, key, 1)[0] == original_file
            assert replay(record)["verified"]
            assert record["withdrawal"]["reason"] == "换库前登记撤回"
            assert [packet["id"] for packet in record["body"]["packets"]] == ["LINDEN-LOGGER-A", "LINDEN-LOGGER-B"]
            # After enabling the new database, packet, readings, and sources
            # take effect together.
            followup = {"id": "LINDEN-LOGGER-POST", "rows": [
                {"id": "LINDEN-11", "step": "repeat_b", "observed_at": "2026-09-18T09:00:45Z", "indicated_mg": 300013},
                {"id": "LINDEN-02", "step": "rise_low", "observed_at": "2026-09-18T09:00:05Z", "indicated_mg": 100007}]}
            result = accept_packet(connection, key, followup)
            assert result["inserted"] == 1 and result["generation"] == 4
            sources = list_sources(connection, key)
            assert sources["LINDEN-02"] == ["LINDEN-LOGGER-A", "LINDEN-LOGGER-POST"]
            assert sources["LINDEN-11"] == ["LINDEN-LOGGER-POST"]
        # A packet rejected for rewriting a reading leaves no partial sources.
        bad = {"id": "LINDEN-LOGGER-BAD", "rows": [
            {"id": "LINDEN-12", "step": "repeat_c", "observed_at": "2026-09-18T09:00:58Z", "indicated_mg": 300014},
            {"id": "LINDEN-01", "step": "zero_in", "observed_at": "2026-09-18T09:00:00Z", "indicated_mg": 999}]}
        try:
            with db.transaction(write=True) as connection:
                accept_packet(connection, key, bad)
            raise AssertionError("改写既有读数必须整包拒绝")
        except Problem as exc:
            assert exc.code == "row_conflict"
        with db.transaction() as connection:
            sources = list_sources(connection, key)
            assert "LINDEN-12" not in sources and sources["LINDEN-01"] == ["LINDEN-LOGGER-A", "LINDEN-LOGGER-RE"]
            assert connection.execute("SELECT COUNT(*) FROM packets WHERE session=?", (key,)).fetchone()[0] == 4
            assert connection.execute("SELECT generation FROM sessions WHERE id=?", (key,)).fetchone()[0] == 4
        Database(path)  # reopening the migrated database is a no-op
        with sqlite3.connect(path, isolation_level=None) as connection:
            assert connection.execute("SELECT COUNT(*) FROM reading_sources").fetchone()[0] == 15

        # A corrupted old packet stops the migration; the old database stays
        # reusable, and a retry after the fix does not count sources twice.
        broken = Path(tmp) / "broken.sqlite3"
        build_legacy(broken)
        with sqlite3.connect(broken, isolation_level=None) as connection:
            saved = connection.execute("SELECT payload FROM packets WHERE id='LINDEN-LOGGER-RE'").fetchone()[0]
            connection.execute("UPDATE packets SET payload=? WHERE id='LINDEN-LOGGER-RE'",
                               ('{"id":"LINDEN-LOGGER-RE","rows":[',))
        try:
            Database(broken)
            raise AssertionError("旧包损坏必须中止迁移")
        except MigrationError:
            pass
        with sqlite3.connect(broken, isolation_level=None) as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='reading_sources'").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM packets").fetchone()[0] == 4
            connection.execute("UPDATE packets SET payload=? WHERE id='LINDEN-LOGGER-RE'", (saved,))
        Database(broken)
        with sqlite3.connect(broken, isolation_level=None) as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
            assert connection.execute("SELECT COUNT(*) FROM reading_sources").fetchone()[0] == 13

        # A tampered payload that no longer matches its registered digest is
        # likewise rejected without touching the old database.
        tampered = Path(tmp) / "tampered.sqlite3"
        build_legacy(tampered)
        fake = canonical({"id": "LINDEN-LOGGER-RE", "rows": [
            {"id": "LINDEN-01", "step": "zero_in", "observed_at": "2026-09-18T09:00:00Z", "indicated_mg": 777}]})
        with sqlite3.connect(tampered, isolation_level=None) as connection:
            connection.execute("UPDATE packets SET payload=? WHERE id='LINDEN-LOGGER-RE'", (fake,))
        try:
            Database(tampered)
            raise AssertionError("载荷摘要被篡改必须中止迁移")
        except MigrationError:
            pass
        with sqlite3.connect(tampered, isolation_level=None) as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
    print("PASS migrate")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--through", choices=WORKFLOWS, default="migrate")
    args = parser.parse_args()
    with TemporaryDirectory() as tmp, WorkbenchServer(Database(Path(tmp) / "smoke.sqlite3"), 0) as server:
        worker = Thread(target=server.serve_forever)
        worker.start()
        try:
            exercise(server.server_port, args.through)
        finally:
            server.shutdown()
            worker.join()
    if args.through == "migrate":
        exercise_migration()


if __name__ == "__main__":
    main()
