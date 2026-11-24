from pathlib import Path

from .codec import loads
from .intake import accept_packet
from .sessions import create_session
from .standards import register_standard

EXAMPLES = ("linden-shift.json", "alder-split.json")


def demo_datasets():
    root = Path(__file__).resolve().parent.parent / "examples"
    return [loads((root / name).read_bytes()) for name in EXAMPLES]


def demo_data():
    # The primary sample drives the shipped smoke walkthrough.
    return demo_datasets()[0]


def _load(db, data):
    key = data["session"]["id"]
    if not db.execute("SELECT 1 FROM sessions WHERE id=?", (key,)).fetchone():
        for item in data["standards"]:
            register_standard(db, item)
        create_session(db, data["session"])
        for packet in data["packets"]:
            accept_packet(db, key, packet)
    return key


def load_demo(db):
    keys = [_load(db, data) for data in demo_datasets()]
    return {"id": keys[0], "sessions": keys}
