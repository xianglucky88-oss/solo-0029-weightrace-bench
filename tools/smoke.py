"""Exercise the shipped HTTP workflows on a throwaway local database."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from weightrace.codec import digest as digest_json
from weightrace.database import Database
from weightrace.demo import demo_data
from weightrace.httpd import WorkbenchServer
from weightrace.replay import replay as replay_record

WORKFLOWS = ("catalog", "plan", "ingest", "evaluate", "freeze", "review", "compare", "replay", "export", "withdraw",
             "multiscale", "lineage")


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
    if done("withdraw"):
        return

    hell = json.loads((Path(__file__).resolve().parents[1] / "examples" / "multiscale-hell.json").read_bytes())
    for standard in hell["standards"]:
        api("standards", standard, status=201)
    hell_key = hell["session"]["id"]
    hell_session = f"sessions/{hell_key}"
    # 开测即锁定每档每格毫克数，单分度与多档字段互斥。
    api("sessions", {**hell["session"], "resolution_mg": 1}, status=400, error="fields")
    api("sessions", {k: v for k, v in hell["session"].items() if k != "scales"}, status=400, error="fields")
    duplicated = {**hell["session"], "id": "HELL-DUP", "scales": [{"id": "A", "grid_mg": 1}, {"id": "B", "grid_mg": 1}]}
    api("sessions", duplicated, status=400, error="scale_duplicate")
    hell_plan = api("sessions", hell["session"], status=201)
    assert [s["grid_mg"] for s in hell_plan["scales"]] == [1, 4] and "resolution_mg" not in hell_plan
    hell_packets = f"{hell_session}/packets"
    pa, pb = hell["packets"]
    assert api(hell_packets, pa, status=201)["generation"] == 1
    # 相同原始读数重发仍按旧规则幂等处理，不增代次。
    assert api(hell_packets, pa)["duplicate"] and api(hell_packets, pa)["generation"] == 1
    # 未知档、缺档、旧式行均整包拒绝，不能部分归集。
    unknown = {"id": "BAD-SCALE", "rows": [{**pa["rows"][0], "id": "X-1", "scale": "G9"}]}
    api(hell_packets, unknown, status=400, error="unknown_scale")
    missing = {"id": "NO-SCALE", "rows": [{**{k: v for k, v in pa["rows"][0].items() if k != "scale"}, "id": "X-2"}]}
    api(hell_packets, missing, status=400, error="fields")
    legacy_row = {"id": "LEGACY-ROW", "rows": [{"id": "X-3", "step": "zero_in",
                  "observed_at": "2026-11-23T09:00:00Z", "indicated_mg": 0}]}
    api(hell_packets, legacy_row, status=400, error="fields")
    # 同号读数从 4mg×26 格改成 1mg×104 格，即使都显示 104mg 也拒绝改写。
    same_mg = {"id": "REWRITE-MG", "rows": [{"id": "R-04", "step": "fall_low",
               "observed_at": "2026-11-23T09:00:03Z", "scale": "G1", "grids": 104}]}
    api(hell_packets, same_mg, status=409, error="row_conflict")
    # 被拒包不留痕：仍只有第一包，代次不变。
    assert len(api(hell_session)["packets"]) == 1
    assert api(hell_packets, pb, status=201)["generation"] == 2
    hell_result = api(hell_session)["result"]
    assert hell_result["engine"] == "weightrace-multigrid-v2"
    assert all(step["state"] == "matched" for step in hell_result["steps"])
    check = hell_result["metrics"]["hysteresis"]["checks"][0]
    # 升低 1mg/格、回低 4mg/格：回程差区间 0 至 3mg，限值 2mg 判临界。
    assert (check["lower"]["mg"], check["upper"]["mg"], check["outcome"]) == ("0/1", "3/1", "borderline")
    assert hell_result["outcome"] == "borderline"
    assert hell_result["metrics"]["drift"]["checks"][0]["upper"]["mg"] == "5/2"
    if done("multiscale"):
        return

    hell_releases = f"{hell_session}/releases"
    hell_release = api(hell_releases, {"generation": 2}, status=201)
    assert api(f"{hell_releases}/1/replay")["verified"]
    bundle = hell_release["body"]
    adopted = {row["id"]: row for row in bundle["input"]["readings"]}
    # 下载件必须追到所用读数的原始档位、格数与当次锁定分度。
    assert adopted["R-04"]["scale"] == "G4" and adopted["R-04"]["grids"] == 26
    assert {s["id"]: s["grid_mg"] for s in bundle["input"]["plan"]["scales"]} == {"G1": 1, "G4": 4}
    tampered = deepcopy(bundle)
    for packet in tampered["packets"]:
        for row in packet["payload"]["rows"]:
            if row["id"] == "R-04":
                row["scale"], row["grids"] = "G1", 104
        packet["digest"] = digest_json(packet["payload"])
    for row in tampered["input"]["readings"]:
        if row["id"] == "R-04":
            row["scale"], row["grids"] = "G1", 104
    tampered_record = {"body": tampered, "sha256": digest_json(tampered), "withdrawal": None}
    # 毫克示值与摘要自洽也不够：采用档位与原包不符即复算不通过。
    assert replay_record(tampered_record)["reason"] == "result_mismatch"
    disagree = deepcopy(bundle)
    for row in disagree["input"]["readings"]:
        if row["id"] == "R-04":
            row["scale"], row["grids"] = "G1", 104
    disagree_record = {"body": disagree, "sha256": digest_json(disagree), "withdrawal": None}
    assert replay_record(disagree_record)["reason"] == "provenance_mismatch"
    done("lineage")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--through", choices=WORKFLOWS, default="lineage")
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
