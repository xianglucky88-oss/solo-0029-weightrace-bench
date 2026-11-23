import re
from urllib.parse import parse_qs, unquote, urlsplit

from .adjudication import record_decision
from .archives import freeze_release, get_release, withdraw_release
from .compare import compare_releases
from .demo import load_demo
from .errors import Problem
from .export import export_release
from .intake import accept_packet, claim_pending, list_pending
from .replay import replay
from .sessions import create_session, list_sessions
from .standards import list_standards, register_standard
from .values import fields
from .workbench import read_workbench

PREFIX = "/weightrace/api/"
DETAIL = re.compile(r"sessions/([A-Za-z0-9][A-Za-z0-9_-]{0,47})(?:/(.*))?")
RELEASE = re.compile(r"releases/([1-9][0-9]{0,8})(?:/(replay|file|withdraw))?")
PENDING = re.compile(r"pending(?:/([^/]+))?(?:/(claim|retransmission|retransmit|close))?")


def compare_args(query):
    try:
        params = parse_qs(query, keep_blank_values=True, max_num_fields=4)
    except ValueError:
        params = {}
    if set(params) != {"left", "right"} or any(len(v) != 1 or not re.fullmatch(r"[1-9][0-9]{0,8}", v[0]) for v in params.values()):
        raise Problem("compare_args", "须指定两份交付版号")
    return int(params["left"][0]), int(params["right"][0])


def route_api(db, method, target, item):
    url = urlsplit(target)
    path = url.path.removeprefix(PREFIX)
    if path == "standards":
        if method == "GET":
            return 200, list_standards(db)
        content, created = register_standard(db, item)
        return (201 if created else 200), content
    if path == "sessions":
        return (200, list_sessions(db)) if method == "GET" else (201, create_session(db, item))
    if path == "demo" and method == "POST":
        fields(item)
        return 200, load_demo(db)
    match = DETAIL.fullmatch(path)
    if match:
        key, action = match.groups()
        if method == "GET":
            if action is None:
                return 200, read_workbench(db, key)
            if action == "compare":
                return 200, compare_releases(db, key, *compare_args(url.query))
            if action == "pending":
                return 200, list_pending(db, key)
        elif action in ("packets", "decisions", "releases"):
            if action == "packets":
                result = accept_packet(db, key, item)
                return (200 if result["duplicate"] else 201), result
            if action == "decisions":
                return 201, record_decision(db, key, item)
            result, created = freeze_release(db, key, item)
            return (201 if created else 200), result
        elif method == "POST":
            claimed = PENDING.fullmatch(action or "")
            if claimed:
                # POST pending                         -> receipt and round in the body
                # POST pending/{receipt}               -> receipt in the path
                # POST pending/{receipt}/{disposition} -> disposition in the path too
                receipt = unquote(claimed[1]) if claimed[1] else None
                path_disposition = claimed[2]
                if path_disposition:
                    item = {**(item or {}), "disposition": path_disposition}
                return 200, claim_pending(db, key, item, receipt)
        release = RELEASE.fullmatch(action or "")
        if release:
            number, operation = int(release[1]), release[2]
            if method == "GET":
                if operation == "replay":
                    return 200, replay(get_release(db, key, number))
                if operation == "file":
                    return 200, export_release(db, key, number)
                if operation is None:
                    return 200, get_release(db, key, number)
            elif operation == "withdraw":
                return 200, withdraw_release(db, key, number, item)
    raise Problem("not_found", "接口不存在", 404)
