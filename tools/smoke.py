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
from weightrace.demo import demo_data, demo_datasets
from weightrace.httpd import WorkbenchServer

WORKFLOWS = ("catalog", "plan", "ingest", "evaluate", "freeze", "review", "compare", "replay",
             "export", "withdraw", "handoff")


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

    exercise_handoff(api, done, d)


def exercise_handoff(api, done, d):
    """Mid-shift reset: hand off the rise segment, invalidate, restore, re-confirm."""
    split = next(data for data in demo_datasets() if data["session"]["id"] == "ALDER-0920")
    key = split["session"]["id"]
    session = f"sessions/{key}"
    for standard in split["standards"]:
        api("standards", standard, status=201)
    api("sessions", split["session"], status=201)
    rise, fall = split["packets"]
    api(f"{session}/packets", rise, status=201)
    workbench = api(session)
    assert [step["id"] for step in workbench["plan"]["steps"]][:5] == [
        "zero_in", "rise_low", "rise_high", "zero_mid_before", "zero_mid_after"]
    assert workbench["result"]["outcome"] == "blocked" and workbench["handoffs"] == []

    handoffs = f"{session}/handoffs"
    claim = {"reviewer": "复核员乙", "zero_in": "ALDER-01", "rise_low": "ALDER-02",
             "rise_high": "ALDER-03", "zero_mid_before": "ALDER-04", "generation": workbench["generation"]}
    # The rise segment alone cannot satisfy a claim naming a reading that is not there.
    api(handoffs, {**claim, "rise_low": "ALDER-03"}, status=409, error="handoff_mismatch")
    handoff = api(handoffs, claim, status=201)
    assert handoff["status"]["valid"] and handoff["document"]["readings"]["rise_high"] == "ALDER-03"
    # The rise segment is corrected only against its own pans: the +607 reset jump
    # never enters the zero for rise_high, so its error stays small, not ~600 mg.
    rise_high = handoff["document"]["rise"]["rise_high"]
    numerator, denominator = (int(part) for part in rise_high["error"]["mg"].split("/"))
    assert abs(numerator / denominator) < 10, rise_high["error"]

    # A full release is refused without the fall segment, regardless of the hand-off.
    api(f"{session}/releases", {"generation": api(session)["generation"]}, status=409, error="release_blocked")
    api(f"{session}/packets", fall, status=201)
    workbench = api(session)
    assert workbench["result"]["outcome"] != "blocked"
    assert {segment["id"] for segment in workbench["result"]["segments"]} == {"rise", "fall"}
    # Each segment's drift is judged on its own pans; the +607 reset jump is never drift.
    drifts = {check["steps"][0]: check["upper"]["mg"] for check in workbench["result"]["metrics"]["drift"]["checks"]}
    assert drifts["zero_mid_after"] == "7/1" and drifts["zero_in"] == "3/1", drifts

    # A late candidate for the reset pan makes the hand-off ambiguous and blocks sign-off.
    late = {"id": "ALDER-LATE", "rows": [
        {"id": "ALDER-04-LATE", "step": "zero_mid_before",
         "observed_at": "2026-09-20T08:10:27Z", "indicated_mg": 6}]}
    api(f"{session}/packets", late, status=201)
    workbench = api(session)
    assert workbench["handoffs"][0]["status"]["reason"] == "step_ambiguous"
    api(f"{session}/releases", {"generation": workbench["generation"]}, status=409)
    # Excluding the late candidate restores the reading, but the hand-off stays lapsed.
    api(f"{session}/decisions", {"reading": "ALDER-04-LATE", "action": "exclude",
                                 "reason": "迟到候选", "generation": workbench["generation"]}, status=201)
    workbench = api(session)
    assert workbench["result"]["outcome"] != "blocked"
    assert not workbench["handoffs"][0]["status"]["valid"]
    assert workbench["invalidations"] and workbench["invalidations"][0]["reason"] == "step_ambiguous"
    api(f"{session}/releases", {"generation": workbench["generation"]}, status=409, error="handoff_invalid")

    # A fresh confirmation clears the way, and the release carries it and replays.
    again = api(handoffs, {**claim, "generation": workbench["generation"]}, status=201)
    assert again["number"] == 2
    workbench = api(session)
    release = api(f"{session}/releases", {"generation": workbench["generation"]}, status=201)
    assert release["handoff"]["number"] == 2
    assert api(f"{session}/releases/{release['body']['number']}/replay")["verified"]
    done("handoff")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--through", choices=WORKFLOWS, default="handoff")
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
