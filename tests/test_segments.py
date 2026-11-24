"""Focused checks for the segmented zero-curve and hand-off semantics.

The HTTP walkthrough lives in tools.smoke; these tests pin the pure computation
rules that a reviewer relies on when a bench clears its pan mid-shift.
"""

from fractions import Fraction
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from weightrace.adjudication import record_decision
from weightrace.archives import freeze_release
from weightrace.database import Database
from weightrace.errors import Problem
from weightrace.evaluation import evaluate
from weightrace.handoff import confirm_handoff
from weightrace.intake import accept_packet
from weightrace.protocol import BASE_KEYS, MID_ZERO_KEYS
from weightrace.sessions import create_session
from weightrace.standards import register_standard
from weightrace.zero_curve import segment_corrections

STANDARDS = [
    {"id": "W100", "revision": 1, "nominal_mg": 100000, "correction_mg": 0, "radius_mg": 0,
     "valid_from": "2026-01-01", "valid_until": "2027-01-01"},
    {"id": "W200", "revision": 1, "nominal_mg": 200000, "correction_mg": 0, "radius_mg": 0,
     "valid_from": "2026-01-01", "valid_until": "2027-01-01"},
]


def session_plan(**overrides):
    plan = {"id": "T", "bench": "台", "measured_on": "2026-09-18", "resolution_mg": 1,
            "loads": {"low": [{"id": "W100", "revision": 1}],
                      "high": [{"id": "W100", "revision": 1}, {"id": "W200", "revision": 1}]},
            "limits_mg": {"indication": 10, "hysteresis": 5, "repeatability": 5,
                          "eccentricity": 6, "drift": 12}}
    plan.update(overrides)
    return plan


def row(reading, step, seconds, value):
    return {"id": reading, "step": step, "observed_at": f"2026-09-18T09:{seconds:02d}:00Z",
            "indicated_mg": value}


def split_packets(jump=500, rise_drift=2, fall_drift=6):
    rise = {"id": "A", "rows": [
        row("1", "zero_in", 0, 0),
        row("2", "rise_low", 5, 100000 + rise_drift // 2),
        row("3", "rise_high", 10, 300000 + rise_drift),
        row("4", "zero_mid_before", 15, rise_drift)]}
    fall = {"id": "B", "rows": [
        row("5", "zero_mid_after", 30, jump),
        row("6", "fall_low", 35, 100000 + jump + fall_drift),
        row("7", "repeat_a", 40, 300000 + jump),
        row("8", "repeat_b", 42, 300000 + jump),
        row("9", "repeat_c", 44, 300000 + jump),
        row("10", "offset_left", 46, 300000 + jump),
        row("11", "offset_right", 48, 300000 + jump),
        row("12", "zero_out", 50, jump + fall_drift)]}
    return rise, fall


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "t.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, packets, plan=None):
        with self.db.transaction(write=True) as db:
            for standard in STANDARDS:
                register_standard(db, standard)
            create_session(db, plan or session_plan(mid_zero=True))
            for packet in packets:
                accept_packet(db, "T", packet)

    def evaluate(self):
        from weightrace.evaluation import working_input
        with self.db.transaction() as db:
            return evaluate(working_input(db, "T"))

    def generation(self):
        with self.db.transaction() as db:
            return db.execute("SELECT generation FROM sessions WHERE id='T'").fetchone()[0]


class PlanShapeTest(DatabaseCase):
    def test_base_plan_keeps_ten_steps(self):
        self.build([], plan=session_plan())
        with self.db.transaction() as db:
            from weightrace.sessions import get_session
            plan, _ = get_session(db, "T")
        self.assertFalse(plan["mid_zero"])
        self.assertEqual(len(plan["steps"]), len(BASE_KEYS))
        self.assertFalse(set(MID_ZERO_KEYS) & {step["id"] for step in plan["steps"]})

    def test_split_plan_inserts_two_pans(self):
        self.build([])
        with self.db.transaction() as db:
            from weightrace.sessions import get_session
            plan, _ = get_session(db, "T")
        ids = [step["id"] for step in plan["steps"]]
        self.assertEqual(ids[3:5], ["zero_mid_before", "zero_mid_after"])

    def test_mid_zero_must_be_boolean(self):
        with self.db.transaction(write=True) as db:
            with self.assertRaises(Problem) as caught:
                create_session(db, session_plan(mid_zero="yes"))
        self.assertEqual(caught.exception.code, "boolean")


class SegmentCorrectionTest(DatabaseCase):
    def test_each_segment_uses_its_own_pans(self):
        rise, fall = split_packets(jump=500)
        self.build([rise, fall])
        result = self.evaluate()
        self.assertNotEqual(result["outcome"], "blocked")
        # The +500 clear jump must not be read as drift in either segment.
        segments = {segment["id"]: segment["drift"]["mg"] for segment in result["segments"]}
        self.assertEqual(segments, {"rise": "2/1", "fall": "6/1"})

    def test_drift_is_judged_per_segment_worst_wins(self):
        rise, fall = split_packets(jump=500, rise_drift=15)
        self.build([rise, fall])
        result = self.evaluate()
        drift = result["metrics"]["drift"]
        self.assertEqual(len(drift["checks"]), 2)
        self.assertEqual(drift["outcome"], "fail")
        failing = [check for check in drift["checks"] if check["outcome"] == "fail"]
        self.assertEqual(failing[0]["steps"], ["zero_in", "zero_mid_before"])

    def test_hysteresis_compares_real_low_load_steps_across_segments(self):
        # rise_low err = 10, fall_low err = 0; the steps sit in different zero
        # segments and share no anchor, so the interval widens fully (4 * half = 2).
        rise = {"id": "A", "rows": [
            row("1", "zero_in", 0, 0), row("2", "rise_low", 5, 100010),
            row("3", "rise_high", 10, 300000), row("4", "zero_mid_before", 15, 0)]}
        fall = {"id": "B", "rows": [
            row("5", "zero_mid_after", 30, 0), row("6", "fall_low", 35, 100000),
            row("7", "repeat_a", 40, 300000), row("8", "repeat_b", 42, 300000),
            row("9", "repeat_c", 44, 300000), row("10", "offset_left", 46, 300000),
            row("11", "offset_right", 48, 300000), row("12", "zero_out", 50, 0)]}
        self.build([rise, fall])
        result = self.evaluate()
        check = result["metrics"]["hysteresis"]["checks"][0]
        upper = Fraction(*map(int, check["upper"]["mg"].split("/")))
        lower = Fraction(*map(int, check["lower"]["mg"].split("/")))
        self.assertEqual((upper - lower) / 2, 2)  # radius 4 * half, not the 2 * half shared case

    def test_reset_jump_never_enters_rise_correction(self):
        rise, fall = split_packets(jump=5000)
        self.build([rise, fall])
        corrections, _ = self._corrections()
        self.assertLess(abs(corrections["rise_high"]["error"]), 10)

    def _corrections(self):
        from weightrace.adjudication import list_decisions, list_readings
        from weightrace.alignment import align_steps
        from weightrace.sessions import get_session
        with self.db.transaction() as db:
            plan, _ = get_session(db, "T")
            steps, chosen, issues = align_steps(plan, list_readings(db, "T"), list_decisions(db, "T"))
        self.assertEqual(issues, [])
        return segment_corrections(plan, chosen)


class HandoffTest(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.rise, self.fall = split_packets()

    def claim(self, **overrides):
        value = {"reviewer": "甲", "zero_in": "1", "rise_low": "2", "rise_high": "3",
                 "zero_mid_before": "4", "generation": self.generation()}
        value.update(overrides)
        return value

    def confirm(self, **overrides):
        with self.db.transaction(write=True) as db:
            return confirm_handoff(db, "T", self.claim(**overrides))

    def test_handoff_needs_only_the_rise_segment(self):
        self.build([self.rise])
        record = self.confirm()
        self.assertTrue(record["status"]["valid"])
        self.assertEqual(record["document"]["scope"], "rise-segment")
        self.assertIn("不等于整场签出", record["document"]["caveat"])

    def test_handoff_refuses_non_segmented_session(self):
        with self.db.transaction(write=True) as db:
            for standard in STANDARDS:
                register_standard(db, standard)
            create_session(db, session_plan())
            accept_packet(db, "T", {"id": "F", "rows": [
                row("1", "zero_in", 0, 0), row("2", "rise_low", 5, 100000),
                row("3", "rise_high", 10, 300000), row("4", "fall_low", 15, 100000),
                row("5", "repeat_a", 20, 300000), row("6", "repeat_b", 22, 300000),
                row("7", "repeat_c", 24, 300000), row("8", "offset_left", 26, 300000),
                row("9", "offset_right", 28, 300000), row("10", "zero_out", 30, 0)]})
        with self.db.transaction(write=True) as db:
            with self.assertRaises(Problem) as caught:
                confirm_handoff(db, "T", {"reviewer": "甲", "zero_in": "1", "rise_low": "2",
                                          "rise_high": "3", "zero_mid_before": "1", "generation": 1})
        self.assertEqual(caught.exception.code, "not_mid_zero")

    def test_mismatched_reading_is_refused(self):
        self.build([self.rise])
        with self.assertRaises(Problem) as caught:
            self.confirm(rise_low="3")
        self.assertEqual(caught.exception.code, "handoff_mismatch")

    def test_release_requires_confirmed_handoff(self):
        self.build([self.rise, self.fall])
        with self.db.transaction(write=True) as db:
            with self.assertRaises(Problem) as caught:
                freeze_release(db, "T", {"generation": self.generation()})
        self.assertEqual(caught.exception.code, "handoff_required")

    def test_late_ambiguity_lapses_and_blocks_release(self):
        self.build([self.rise, self.fall])
        self.confirm()
        late = {"id": "LATE", "rows": [row("4b", "zero_mid_before", 16, 3)]}
        with self.db.transaction(write=True) as db:
            accept_packet(db, "T", late)
        with self.db.transaction() as db:
            from weightrace.workbench import read_workbench
            workbench = read_workbench(db, "T")
            self.assertEqual(workbench["handoffs"][0]["status"]["reason"], "step_ambiguous")
            self.assertEqual(workbench["invalidations"][0]["reason"], "step_ambiguous")
        with self.db.transaction(write=True) as db:
            with self.assertRaises(Problem) as caught:
                freeze_release(db, "T", {"generation": self.generation()})
        self.assertIn(caught.exception.code, {"release_blocked", "handoff_invalid"})

    def test_restoring_the_reading_still_requires_reconfirmation(self):
        self.build([self.rise, self.fall])
        self.confirm()
        with self.db.transaction(write=True) as db:
            accept_packet(db, "T", {"id": "LATE", "rows": [row("4b", "zero_mid_before", 16, 3)]})
        with self.db.transaction(write=True) as db:
            record_decision(db, "T", {"reading": "4b", "action": "exclude",
                                      "reason": "迟到候选", "generation": self.generation()})
        with self.db.transaction() as db:
            from weightrace.workbench import read_workbench
            workbench = read_workbench(db, "T")
        self.assertNotEqual(workbench["result"]["outcome"], "blocked")
        self.assertFalse(workbench["handoffs"][0]["status"]["valid"])
        self.assertEqual(workbench["invalidations"][0]["reason"], "step_ambiguous")
        with self.db.transaction(write=True) as db:
            with self.assertRaises(Problem) as caught:
                freeze_release(db, "T", {"generation": self.generation()})
        self.assertEqual(caught.exception.code, "handoff_invalid")
        # A fresh confirmation reuses the original reading and lets sign-off proceed.
        record = self.confirm()
        self.assertTrue(record["status"]["valid"])
        self.assertEqual(record["number"], 2)
        with self.db.transaction(write=True) as db:
            release, created = freeze_release(db, "T", {"generation": self.generation()})
        self.assertTrue(created)
        self.assertEqual(release["handoff"]["number"], 2)

    def test_redelivery_of_same_readings_keeps_handoff_valid(self):
        self.build([self.rise, self.fall])
        self.confirm()
        # A second origin carrying only the same rise rows is new evidence (a new
        # generation) but not a change of the readings the hand-off froze.
        with self.db.transaction(write=True) as db:
            accept_packet(db, "T", {"id": "REDELIVER", "rows": [
                dict(row) for row in self.rise["rows"]]})
        with self.db.transaction() as db:
            from weightrace.workbench import read_workbench
            workbench = read_workbench(db, "T")
        self.assertTrue(workbench["handoffs"][0]["status"]["valid"])
        self.assertEqual(workbench["invalidations"], [])

    def test_exclusion_of_confirmed_reading_lapses_handoff(self):
        self.build([self.rise, self.fall])
        self.confirm()
        with self.db.transaction(write=True) as db:
            record_decision(db, "T", {"reading": "3", "action": "exclude",
                                      "reason": "读数存疑", "generation": self.generation()})
        with self.db.transaction() as db:
            from weightrace.workbench import read_workbench
            workbench = read_workbench(db, "T")
        self.assertEqual(workbench["handoffs"][0]["status"]["reason"], "reading_excluded")


class ReplayTest(DatabaseCase):
    def test_release_embeds_and_replays_handoff(self):
        from weightrace.replay import replay
        rise, fall = split_packets()
        self.build([rise, fall])
        with self.db.transaction(write=True) as db:
            generation = self.generation()
            confirm_handoff(db, "T", {"reviewer": "甲", "zero_in": "1", "rise_low": "2",
                                      "rise_high": "3", "zero_mid_before": "4", "generation": generation})
        with self.db.transaction(write=True) as db:
            release, _ = freeze_release(db, "T", {"generation": self.generation()})
            from weightrace.archives import get_release
            record = get_release(db, "T", release["body"]["number"])
        self.assertEqual(release["handoff"]["number"], 1)
        self.assertTrue(replay(record)["verified"])

    def test_v1_engine_still_replays(self):
        from weightrace.codec import digest
        from weightrace import legacy
        from weightrace.protocol import steps_for
        from weightrace.replay import replay as replay_fn
        loads = {"zero": {"items": [], "reference_mg": 0, "radius_mg": 0},
                 "low": {"items": [], "reference_mg": 100000, "radius_mg": 0},
                 "high": {"items": [], "reference_mg": 300000, "radius_mg": 0}}
        plan = {"id": "T", "measured_on": "2026-09-18", "resolution_mg": 1,
                "limits_mg": {"indication": 10, "hysteresis": 5, "repeatability": 5,
                              "eccentricity": 6, "drift": 12},
                "steps": steps_for(loads)}
        readings, seconds = [], 0
        for step in plan["steps"]:
            readings.append(row(f"r{step['id']}", step["id"], seconds, step["reference_mg"]))
            seconds += 2
        snapshot = {"plan": plan, "generation": 1, "readings": readings, "decisions": []}
        frozen = legacy.evaluate(snapshot)
        self.assertEqual(frozen["engine"], "weightrace-linear-v1")
        body = {"format": "weightrace-evidence-v1", "session": "T", "number": 1, "published_at": "x",
                "input": snapshot, "packets": [], "result": frozen}
        record = {"body": body, "sha256": digest(body)}
        self.assertTrue(replay_fn(record)["verified"])


class MigrationTest(unittest.TestCase):
    def test_v1_database_upgrades_in_place(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.sqlite3"
            connection = sqlite3.connect(path)
            connection.executescript("""
                CREATE TABLE sessions (id TEXT PRIMARY KEY, plan TEXT NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE readings (session TEXT NOT NULL, id TEXT NOT NULL, step TEXT NOT NULL,
                    observed_at TEXT NOT NULL, indicated_mg INTEGER NOT NULL, origin_packet TEXT NOT NULL,
                    PRIMARY KEY (session, id));
                INSERT INTO sessions VALUES ('OLD', '{}', 0);
            """)
            connection.execute("PRAGMA user_version = 1")
            connection.commit()
            connection.close()
            database = Database(path)
            with database.transaction() as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
                tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertIn("handoffs", tables)
                self.assertIn("invalidations", tables)
                self.assertEqual(db.execute("SELECT id FROM sessions").fetchone()[0], "OLD")


if __name__ == "__main__":
    unittest.main()
