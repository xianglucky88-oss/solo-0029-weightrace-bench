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

WORKFLOWS = ("catalog", "plan", "ingest", "evaluate", "freeze", "review", "compare", "replay", "export", "withdraw")


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
