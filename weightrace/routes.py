import re
from urllib.parse import parse_qs, urlsplit

from .adjudication import record_decision
from .archives import freeze_release, get_release, withdraw_release
from .compare import compare_releases
from .demo import load_demo
from .errors import Problem
from .export import export_release
from .handoff import confirm_handoff, list_handoffs, record_invalidation, read_handoff
from .intake import accept_packet
from .replay import replay
from .sessions import create_session, list_sessions
from .standards import list_standards, register_standard
from .values import fields
from .workbench import read_workbench

PREFIX = "/weightrace/api/"
DETAIL = re.compile(r"sessions/([A-Za-z0-9][A-Za-z0-9_-]{0,47})(?:/(.*))?")
RELEASE = re.compile(r"releases/([1-9][0-9]{0,8})(?:/(replay|file|withdraw))?")
HANDOFF = re.compile(r"handoffs/([1-9][0-9]{0,8})(?:/(invalidate))?")


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
            if action == "handoffs":
                return 200, list_handoffs(db, key)
        elif action in ("packets", "decisions", "releases", "handoffs"):
            if action == "packets":
                result = accept_packet(db, key, item)
                return (200 if result["duplicate"] else 201), result
            if action == "decisions":
                return 201, record_decision(db, key, item)
            if action == "handoffs":
                return 201, confirm_handoff(db, key, item)
            result, created = freeze_release(db, key, item)
            return (201 if created else 200), result
        handoff = HANDOFF.fullmatch(action or "")
        if handoff:
            number, operation = int(handoff[1]), handoff[2]
            if method == "GET" and operation is None:
                return 200, read_handoff(db, key, number)
            if method == "POST" and operation == "invalidate":
                return 201, record_invalidation(db, key, number, item)
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
