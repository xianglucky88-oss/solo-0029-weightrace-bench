import argparse
import logging
import sqlite3

from .database import Database
from .demo import load_demo
from .errors import Problem
from .httpd import WorkbenchServer


def main():
    parser = argparse.ArgumentParser(description="衡迹 · 称量测次复核台")
    parser.add_argument("--db", default="weightrace.sqlite3", help="本地 SQLite 文件")
    parser.add_argument("--port", type=int, default=8837, help="本机端口，0 表示自动选择")
    parser.add_argument("--demo", action="store_true", help="首次运行时载入合成测次")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("端口须为 0 至 65535")
    try:
        db = Database(args.db)
        if args.demo:
            with db.transaction(write=True) as connection:
                load_demo(connection)
        with WorkbenchServer(db, args.port) as server:
            print(f"衡迹已启动：http://127.0.0.1:{server.server_port}/", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return
    except (OSError, sqlite3.Error, Problem, ValueError) as exc:
        logging.error("启动失败：%s", exc)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
