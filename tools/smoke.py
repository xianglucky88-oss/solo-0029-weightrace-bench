"""Exercise the shipped HTTP workflows on a throwaway local database."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from weightrace.database import Database
from weightrace.demo import demo_data
from weightrace.httpd import WorkbenchServer

WORKFLOWS = ("catalog", "plan", "ingest", "evaluate", "freeze", "review", "compare", "replay", "export",
             "withdraw", "bulletin_catalog", "bulletin_plan", "bulletin_reissue", "bulletin_replay")


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
    assert len(api(session)["packets"]) == 1
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
    for pack in (first, mistimed):
        api("sessions/ORDER-CHECK/packets", pack, status=201)
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
    done("withdraw")

    def bulletin_limits(drift):
        return {"indication": 10, "hysteresis": 5, "repeatability": 5, "eccentricity": 6, "drift": drift}

    old_bulletin = {"id": "QC-LIMIT-1", "effective_from": "2026-11-01", "effective_until": "2026-12-01",
                    "limits_mg": bulletin_limits(3)}
    assert api("bulletins", old_bulletin, status=201) == old_bulletin
    assert api("bulletins", old_bulletin) == old_bulletin
    api("bulletins", {**old_bulletin, "limits_mg": bulletin_limits(2)}, status=409, error="bulletin_conflict")
    assert api("bulletins") == [old_bulletin]

    def bulletin_session(day):
        item = {"id": f"BLTN-{day[-2:]}", "bench": "公告台 · 01", "measured_on": day, "resolution_mg": 1,
                "judgement": "bulletin",
                "loads": {"low": [{"id": "LINDEN-100", "revision": 1}],
                          "high": [{"id": "LINDEN-100", "revision": 1}, {"id": "LINDEN-200", "revision": 2}]}}
        return api("sessions", item, status=201)["id"]

    def november_packets(day):
        month, dom = day[5:7], day[8:10]
        stamp = lambda h, m, s: f"2026-{month}-{dom}T{h:02d}:{m:02d}:{s:02d}Z"
        first = {"id": "BLTN-LOGGER-B", "rows": [
            {"id": "B-05", "step": "repeat_a", "observed_at": stamp(9, 0, 28), "indicated_mg": 300013},
            {"id": "B-06", "step": "repeat_b", "observed_at": stamp(9, 0, 40), "indicated_mg": 300013},
            {"id": "B-07", "step": "repeat_c", "observed_at": stamp(9, 0, 55), "indicated_mg": 300014},
            {"id": "B-08", "step": "offset_left", "observed_at": stamp(9, 1, 4), "indicated_mg": 300019},
            {"id": "B-09", "step": "offset_right", "observed_at": stamp(9, 1, 20), "indicated_mg": 300014},
            {"id": "B-10", "step": "zero_out", "observed_at": stamp(9, 1, 40), "indicated_mg": 4}]}
        second = {"id": "BLTN-LOGGER-A", "rows": [
            {"id": "B-01", "step": "zero_in", "observed_at": stamp(9, 0, 0), "indicated_mg": 2},
            {"id": "B-02", "step": "rise_low", "observed_at": stamp(9, 0, 5), "indicated_mg": 100007},
            {"id": "B-03", "step": "rise_high", "observed_at": stamp(9, 0, 15), "indicated_mg": 300015},
            {"id": "B-04", "step": "fall_low", "observed_at": stamp(9, 0, 20), "indicated_mg": 100007}]}
        return first, second

    gap_id = bulletin_session("2026-12-15")
    for packet in november_packets("2026-12-15"):
        api(f"sessions/{gap_id}/packets", packet, status=201)
    gap_view = api(f"sessions/{gap_id}")
    assert gap_view["result"]["outcome"] == "blocked"
    assert gap_view["result"]["issues"] == [{"code": "missing_bulletin", "measured_on": "2026-12-15"}]
    api(f"sessions/{gap_id}/releases", {"generation": 2}, status=409, error="release_basis")
    api("sessions", {"id": "BLTN-OWNCONF", "bench": "公告台 · 02", "measured_on": "2026-11-10", "resolution_mg": 1,
                     "judgement": "bulletin", "limits_mg": bulletin_limits(3),
                     "loads": {"low": [{"id": "LINDEN-100", "revision": 1}],
                               "high": [{"id": "LINDEN-100", "revision": 1}, {"id": "LINDEN-200", "revision": 2}]}},
        status=400, error="fields")

    s10 = bulletin_session("2026-11-10")
    s11 = bulletin_session("2026-11-11")
    for sid, day in ((s10, "2026-11-10"), (s11, "2026-11-11")):
        for packet in november_packets(day):
            api(f"sessions/{sid}/packets", packet, status=201)
    view10 = api(f"sessions/{s10}")
    assert view10["result"]["basis"]["bulletin"]["id"] == "QC-LIMIT-1"
    assert view10["result"]["metrics"]["drift"]["outcome"] == "pass"
    view11 = api(f"sessions/{s11}")
    assert view11["result"]["metrics"]["drift"]["outcome"] == "pass"
    if done("bulletin_catalog"):
        return

    rel10 = f"sessions/{s10}/releases"
    rel11 = f"sessions/{s11}/releases"
    api(rel10, {"generation": 2}, status=400, error="release_basis")
    r10 = api(rel10, {"generation": 2, "bulletin_id": "QC-LIMIT-1"}, status=201)
    assert r10["basis_id"] == "QC-LIMIT-1"
    r11 = api(rel11, {"generation": 2, "bulletin_id": "QC-LIMIT-1"}, status=201)
    assert r11["body"]["result"]["metrics"]["drift"]["outcome"] == "pass"
    # The frozen download keeps the limits actually in force at freeze time.
    file11 = api(f"{rel11}/1/file", binary=True)
    assert json.loads(file11)["body"]["result"]["basis"]["bulletin"]["limits_mg"]["drift"] == 3
    api(f"sessions/{s11}/releases", {"generation": 2, "bulletin_id": "QC-OTHER"}, status=404, error="missing_bulletin")
    if done("bulletin_plan"):
        return

    new_bulletin = {"id": "QC-LIMIT-2", "effective_from": "2026-11-11", "effective_until": "2026-12-01",
                    "limits_mg": bulletin_limits(2)}
    assert api("bulletins", new_bulletin, status=201) == new_bulletin
    reissued = api(f"sessions/{s11}")
    assert reissued["result"]["basis"]["bulletin"]["id"] == "QC-LIMIT-2"
    assert reissued["result"]["metrics"]["drift"]["outcome"] == "borderline"
    # Same readings, same adjudication: only the applicable bulletin changed.
    assert reissued["generation"] == 2
    # Re-checkout with the stale bulletin the reviewer had viewed is refused; an unknown id is a missing bulletin.
    api(rel11, {"generation": 2, "bulletin_id": "QC-LIMIT-1"}, status=409, error="bulletin_changed")
    r11_v2 = api(rel11, {"generation": 2, "bulletin_id": "QC-LIMIT-2"}, status=201)
    assert r11_v2["body"]["number"] == 2 and r11_v2["basis_id"] == "QC-LIMIT-2"
    assert r11_v2["body"]["result"]["metrics"]["drift"]["outcome"] == "borderline"
    # Same generation plus same applicable bulletin always returns the same single version.
    assert api(rel11, {"generation": 2, "bulletin_id": "QC-LIMIT-2"}) == r11_v2
    # The 10th measured day stays on the old bulletin and cannot be forced onto the new one.
    still10 = api(f"sessions/{s10}")
    assert still10["result"]["basis"]["bulletin"]["id"] == "QC-LIMIT-1"
    api(rel10, {"generation": 2, "bulletin_id": "QC-LIMIT-2"}, status=409, error="bulletin_changed")
    assert api(rel10, {"generation": 2, "bulletin_id": "QC-LIMIT-1"}) == r10
    if done("bulletin_reissue"):
        return

    diff = api(f"sessions/{s11}/compare?left=1&right=2")
    assert diff["basis"] == [{"mode": "bulletin", "bulletin_id": "QC-LIMIT-1"},
                             {"mode": "bulletin", "bulletin_id": "QC-LIMIT-2"}]
    assert diff["steps"] == [] and diff["packets_added"] == []
    assert [x["id"] for x in diff["metrics"]] == ["drift"]
    assert [x["after"]["limit_mg"] for x in diff["metrics"]] == [2]
    for number in (1, 2):
        assert api(f"{rel11}/{number}/replay")["verified"]
    # Old file bytes keep the old bulletin limits; the current bulletin must not recompute them.
    old_file = api(f"{rel11}/1/file", binary=True)
    assert old_file == file11
    assert json.loads(old_file)["body"]["result"]["basis"]["bulletin"]["id"] == "QC-LIMIT-1"
    assert json.loads(old_file)["body"]["result"]["metrics"]["drift"]["limit_mg"] == 3
    # A self-limit session never consults bulletins.
    own_view = api(session)
    assert "basis" not in own_view["result"]
    api(releases, {"generation": 6, "bulletin_id": "QC-LIMIT-2"}, status=400, error="fields")
    done("bulletin_replay")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--through", choices=WORKFLOWS, default="withdraw")
    args = parser.parse_args()
    with TemporaryDirectory() as tmp, WorkbenchServer(Database(Path(tmp) / "smoke.sqlite3"), 0) as server:
        worker = Thread(target=server.serve_forever)
        worker.start()
        try:
            exercise(server.server_port, args.through)
        finally:
            server.shutdown()
            worker.join()


if __name__ == "__main__":
    main()
